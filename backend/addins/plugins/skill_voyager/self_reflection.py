"""
Self-Reflection Engine — Analyzes WHY a skill failed and evolves the strategy.

Missing from our initial implementation, this is one of Voyager's core loops:
  1. Skill applied → response evaluated → score < threshold
  2. Reflection: LLM analyzes the (query, strategy, response, score) and explains
     WHAT went wrong and HOW to fix the strategy
  3. Evolution: The skill's strategy text is rewritten based on reflection
  4. Optional retry: Re-run the query with the evolved strategy

Also implements:
- Exploration bonus: Tracks which query types are under-explored and boosts
  novelty-seeking in the curriculum
- Skill versioning: Keeps history of strategy revisions for each skill

Inspired by:
- Voyager's iterative prompting with environment feedback
- SELF-REFINE (iterative self-feedback without external supervision)
- STaR (Self-Taught Reasoner — learn from own reasoning traces)
"""

import json
import time
import uuid
import logging
import asyncio
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field

from .skill_store import SkillStore, Skill, SkillEvaluation

logger = logging.getLogger(__name__)

# Reflection prompt — asks LLM to diagnose the failure and propose a fix
REFLECTION_PROMPT = """You are a strategy improvement analyst. A response strategy was applied but scored poorly.

ORIGINAL QUERY: {query}
STRATEGY APPLIED: {strategy}
AI RESPONSE (first 600 chars): {response_snippet}
EVALUATION SCORE: {score}/5
EVALUATION REASONING: {reasoning}

Analyze what went wrong and propose an improved strategy.

Respond with ONLY this JSON:
{{
  "failure_diagnosis": "<1-2 sentences explaining what went wrong>",
  "root_cause": "<one of: wrong_format, missing_info, too_verbose, off_topic, wrong_approach, incomplete>",
  "improved_strategy": "<the full revised strategy text, 2-4 sentences>",
  "confidence_in_fix": <0.0-1.0 how confident you are this fix will work>
}}"""

# Exploration tracking prompt
EXPLORATION_PROMPT = """Given these query type coverage statistics, which areas need more exploration?

Coverage: {coverage}

List the 3 most under-explored areas as JSON array:
[{{"type": "<primary/sub>", "reason": "<why>", "exploration_priority": <0.0-1.0>}}]"""


@dataclass
class Reflection:
    """A reflection on why a skill failed."""
    id: str
    skill_id: str
    evaluation_id: str
    failure_diagnosis: str
    root_cause: str
    improved_strategy: str
    confidence_in_fix: float
    applied: bool = False  # Whether the improvement was applied to the skill
    created_at: float = 0.0


@dataclass
class SkillRevision:
    """A version history entry for a skill's strategy."""
    revision_number: int
    strategy_before: str
    strategy_after: str
    reflection_id: str
    reason: str
    created_at: float = 0.0


@dataclass
class ExplorationState:
    """Tracks exploration coverage across query types."""
    # query_type -> count of times we've seen this type
    type_counts: Dict[str, int] = field(default_factory=dict)
    # query_type -> count of successful skill applications
    type_successes: Dict[str, int] = field(default_factory=dict)
    # query_type -> timestamp of last seen
    type_last_seen: Dict[str, float] = field(default_factory=dict)
    # Total messages processed
    total_messages: int = 0


class SelfReflectionEngine:
    """
    Reflects on skill failures, evolves strategies, and tracks exploration.

    Three responsibilities:
    1. Reflection: Diagnose why a skill failed
    2. Evolution: Rewrite the skill strategy based on reflection
    3. Exploration: Track coverage and compute novelty bonuses
    """

    def __init__(self, skill_store: SkillStore):
        self.skill_store = skill_store
        self._llm_available = False
        self._llm_base_url: Optional[str] = None
        self._reflections: List[Reflection] = []
        self._revisions: Dict[str, List[SkillRevision]] = {}  # skill_id -> revisions
        self._exploration = ExplorationState()
        self._max_revisions_per_skill = 5  # Don't endlessly rewrite

    def set_llm_endpoint(self, base_url: str) -> None:
        """Configure the local LLM endpoint for reflection."""
        self._llm_base_url = base_url
        self._llm_available = True

    # ── Reflection ────────────────────────────────────────────

    async def reflect_on_failure(
        self,
        skill: Skill,
        evaluation: SkillEvaluation,
        query: str,
        response: str,
    ) -> Optional[Reflection]:
        """
        Analyze why a skill application failed and propose an improvement.

        Only triggers when:
        - Evaluation score < 3.0 (below adequate)
        - Skill has been used at least once before (not first-time noise)
        - Skill hasn't been revised too many times already

        Args:
            skill: The skill that was applied.
            evaluation: The evaluation result.
            query: Original user query.
            response: LLM response that was evaluated.

        Returns:
            Reflection with diagnosis and improved strategy, or None.
        """
        # Guard: only reflect on actual failures
        if evaluation.score >= 3.0:
            return None

        # Guard: don't reflect on brand new skills (need baseline data)
        if skill.times_used < 1:
            return None

        # Guard: don't endlessly revise the same skill
        revision_count = len(self._revisions.get(skill.id, []))
        if revision_count >= self._max_revisions_per_skill:
            logger.info(
                f"Skill '{skill.name}' hit max revisions ({self._max_revisions_per_skill}), "
                f"skipping reflection"
            )
            return None

        reflection: Optional[Reflection] = None

        if self._llm_available and self._llm_base_url:
            try:
                reflection = await self._llm_reflect(skill, evaluation, query, response)
            except Exception as e:
                logger.warning(f"LLM reflection failed: {e}")

        if not reflection:
            reflection = self._heuristic_reflect(skill, evaluation, query, response)

        if reflection:
            self._reflections.append(reflection)
            logger.info(
                f"Reflected on skill '{skill.name}' failure: "
                f"root_cause={reflection.root_cause}, "
                f"confidence_in_fix={reflection.confidence_in_fix:.2f}"
            )

        return reflection

    async def _llm_reflect(
        self,
        skill: Skill,
        evaluation: SkillEvaluation,
        query: str,
        response: str,
    ) -> Optional[Reflection]:
        """Use local LLM to generate a reflection on the failure."""
        import httpx

        prompt = REFLECTION_PROMPT.format(
            query=query[:300],
            strategy=skill.strategy[:400],
            response_snippet=response[:600],
            score=evaluation.score,
            reasoning=evaluation.reasoning[:200],
        )

        payload = {
            "model": "local-model",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 300,
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{self._llm_base_url}/v1/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"].strip()

        # Parse JSON
        import re
        json_match = re.search(r"\{[^}]+\}", content, re.DOTALL)
        if not json_match:
            return None

        try:
            parsed = json.loads(json_match.group())
        except json.JSONDecodeError:
            return None

        return Reflection(
            id=str(uuid.uuid4()),
            skill_id=skill.id,
            evaluation_id=evaluation.id,
            failure_diagnosis=parsed.get("failure_diagnosis", "Unknown failure"),
            root_cause=parsed.get("root_cause", "wrong_approach"),
            improved_strategy=parsed.get("improved_strategy", ""),
            confidence_in_fix=max(0.0, min(1.0, float(parsed.get("confidence_in_fix", 0.5)))),
            created_at=time.time(),
        )

    def _heuristic_reflect(
        self,
        skill: Skill,
        evaluation: SkillEvaluation,
        query: str,
        response: str,
    ) -> Reflection:
        """
        Rule-based reflection when no LLM is available.
        Analyzes structural mismatches between query expectations and response.
        """
        import re

        response_words = len(response.split())
        query_words = len(query.split())

        diagnosis = "Response did not adequately address the query"
        root_cause = "wrong_approach"
        improved_strategy = skill.strategy

        # Diagnose: too short?
        if response_words < 30:
            diagnosis = "Response was too brief for the query complexity"
            root_cause = "incomplete"
            improved_strategy = skill.strategy + " Provide detailed, comprehensive responses. Aim for at least 100 words."

        # Diagnose: missing structure for research queries?
        elif skill.skill_type in ("search_strategy", "retrieval_combo"):
            has_citations = bool(re.search(r"\[\d+\]|source:", response, re.I))
            has_structure = bool(re.search(r"^#+\s|^\s*[-*]\s", response, re.M))
            if not has_citations:
                diagnosis = "Response lacked source citations for a research-type query"
                root_cause = "missing_info"
                improved_strategy = skill.strategy + " Always cite sources with numbered references [1], [2], etc."
            elif not has_structure:
                diagnosis = "Response lacked structural organization"
                root_cause = "wrong_format"
                improved_strategy = skill.strategy + " Use headers and bullet points for better readability."

        # Diagnose: too verbose?
        elif response_words > 500 and query_words < 10:
            diagnosis = "Response was excessively long for a simple query"
            root_cause = "too_verbose"
            improved_strategy = skill.strategy + " Match response length to query complexity. Be concise for simple questions."

        # Diagnose: code missing for technical queries?
        elif skill.skill_type == "error_recovery" and "```" not in response:
            diagnosis = "Technical response missing code examples"
            root_cause = "missing_info"
            improved_strategy = skill.strategy + " Always include code examples with before/after comparison."

        return Reflection(
            id=str(uuid.uuid4()),
            skill_id=skill.id,
            evaluation_id=evaluation.id,
            failure_diagnosis=diagnosis,
            root_cause=root_cause,
            improved_strategy=improved_strategy,
            confidence_in_fix=0.5,
            created_at=time.time(),
        )

    # ── Skill Evolution ───────────────────────────────────────

    def evolve_skill(self, skill: Skill, reflection: Reflection) -> bool:
        """
        Apply a reflection to evolve a skill's strategy.

        Instead of deprecating the skill and creating a v2, this edits
        the strategy in-place (like Voyager editing code) and tracks
        the revision history.

        Only applies if:
        - The reflection has a non-empty improved strategy
        - The confidence in the fix is reasonable (>= 0.3)
        - The improved strategy is actually different

        Args:
            skill: The skill to evolve.
            reflection: The reflection with the improved strategy.

        Returns:
            True if the skill was evolved.
        """
        if not reflection.improved_strategy:
            return False

        if reflection.confidence_in_fix < 0.3:
            logger.debug(
                f"Skipping evolution for '{skill.name}': "
                f"confidence_in_fix={reflection.confidence_in_fix:.2f} too low"
            )
            return False

        if reflection.improved_strategy.strip() == skill.strategy.strip():
            return False

        # Record revision history
        revision_num = len(self._revisions.get(skill.id, [])) + 1
        revision = SkillRevision(
            revision_number=revision_num,
            strategy_before=skill.strategy,
            strategy_after=reflection.improved_strategy,
            reflection_id=reflection.id,
            reason=reflection.failure_diagnosis,
            created_at=time.time(),
        )

        if skill.id not in self._revisions:
            self._revisions[skill.id] = []
        self._revisions[skill.id].append(revision)

        # Apply the evolution
        old_strategy = skill.strategy
        skill.strategy = reflection.improved_strategy
        skill.last_evaluated_at = time.time()

        # Slight confidence boost for evolving (optimism that the fix helps)
        skill.confidence = min(skill.confidence + 0.05, 0.7)

        # Revert state to verified if it was mastered (needs re-proving)
        if skill.state == "mastered":
            skill.state = "verified"

        success = self.skill_store.update_skill(skill)
        if success:
            reflection.applied = True
            logger.info(
                f"Evolved skill '{skill.name}' (revision {revision_num}): "
                f"root_cause={reflection.root_cause}"
            )

        return success

    def get_revision_history(self, skill_id: str) -> List[Dict[str, Any]]:
        """Get the revision history for a skill."""
        revisions = self._revisions.get(skill_id, [])
        return [
            {
                "revision": r.revision_number,
                "strategy_before": r.strategy_before[:200],
                "strategy_after": r.strategy_after[:200],
                "reason": r.reason,
                "created_at": r.created_at,
            }
            for r in revisions
        ]

    # ── Exploration Tracking ──────────────────────────────────

    def record_query_type(self, primary_type: str, sub_type: str, success: bool) -> None:
        """
        Track a query type observation for exploration scoring.

        Args:
            primary_type: Top-level query type (factual, research, etc.)
            sub_type: Specific sub-type (definition, deep_dive, etc.)
            success: Whether a skill was successfully applied.
        """
        key = f"{primary_type}/{sub_type}"
        self._exploration.type_counts[key] = self._exploration.type_counts.get(key, 0) + 1
        if success:
            self._exploration.type_successes[key] = self._exploration.type_successes.get(key, 0) + 1
        self._exploration.type_last_seen[key] = time.time()
        self._exploration.total_messages += 1

    def get_exploration_bonus(self, primary_type: str, sub_type: str) -> float:
        """
        Compute an exploration bonus for a query type.

        Uses Upper Confidence Bound (UCB1) style scoring:
        - Under-explored types get higher bonus
        - Types not seen recently get a recency bonus
        - Types with low success rates get a "needs work" bonus

        Returns:
            Exploration bonus in [0.0, 1.0]. Higher = more should be explored.
        """
        key = f"{primary_type}/{sub_type}"
        total = max(self._exploration.total_messages, 1)
        count = self._exploration.type_counts.get(key, 0)
        successes = self._exploration.type_successes.get(key, 0)
        last_seen = self._exploration.type_last_seen.get(key, 0)

        # UCB1-style exploration term: sqrt(2 * ln(total) / count)
        import math
        if count == 0:
            ucb_bonus = 1.0  # Never seen = maximum exploration
        else:
            ucb_bonus = min(1.0, math.sqrt(2 * math.log(total + 1) / count))

        # Recency bonus: types not seen in a while need exploration
        time_since = time.time() - last_seen if last_seen > 0 else 86400
        recency_bonus = min(0.3, time_since / 86400 * 0.3)  # Up to 0.3 after 24h

        # Success rate penalty: high success = less need to explore
        if count > 0:
            success_rate = successes / count
            success_penalty = (1.0 - success_rate) * 0.2
        else:
            success_penalty = 0.2

        bonus = min(1.0, ucb_bonus * 0.5 + recency_bonus + success_penalty)
        return round(bonus, 3)

    def get_exploration_map(self) -> Dict[str, Dict[str, Any]]:
        """
        Get the full exploration coverage map.

        Returns:
            Dict of query_type -> {count, successes, success_rate, bonus, last_seen}.
        """
        all_types = [
            "factual/definition", "factual/lookup", "factual/comparison",
            "research/deep_dive", "research/multi_source", "research/current_events",
            "creative/writing", "creative/brainstorm",
            "technical/code_debug", "technical/code_generate",
            "conversational/follow_up", "conversational/clarification",
        ]

        result = {}
        for key in all_types:
            parts = key.split("/")
            primary, sub = parts[0], parts[1]
            count = self._exploration.type_counts.get(key, 0)
            successes = self._exploration.type_successes.get(key, 0)
            result[key] = {
                "count": count,
                "successes": successes,
                "success_rate": round(successes / max(count, 1), 2),
                "exploration_bonus": self.get_exploration_bonus(primary, sub),
                "last_seen": self._exploration.type_last_seen.get(key, 0),
            }

        return result

    # ── Introspection ─────────────────────────────────────────

    def get_recent_reflections(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent reflections for the dashboard."""
        recent = self._reflections[-limit:]
        return [
            {
                "id": r.id,
                "skill_id": r.skill_id,
                "failure_diagnosis": r.failure_diagnosis,
                "root_cause": r.root_cause,
                "confidence_in_fix": r.confidence_in_fix,
                "applied": r.applied,
                "created_at": r.created_at,
            }
            for r in reversed(recent)
        ]
