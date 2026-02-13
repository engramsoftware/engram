"""
Response Evaluator — Uses local LLM to score response quality and
determine if the applied skill was successful.

Evaluation pipeline:
1. Receive (query, response, skill_used) triple
2. Call local LLM with a compact evaluation prompt (~500 tokens)
3. Parse structured score (1-5) + reasoning
4. Feed result back to SkillStore for confidence evolution

Falls back to heuristic scoring when no local LLM is available:
- Response length relative to query complexity
- Presence of citations/sources for research queries
- Code block presence for technical queries
- Follow-up invitation for conversational queries

Inspired by Voyager's self-verification module and SELF-REFINE
(iterative self-feedback without external supervision).
"""

import re
import json
import time
import uuid
import logging
import asyncio
from typing import Dict, Any, Optional, Tuple

from .skill_store import SkillStore, Skill, SkillEvaluation

logger = logging.getLogger(__name__)

# Compact evaluation prompt — designed to work with small local models
EVAL_PROMPT = """You are a response quality evaluator. Score this AI response.

USER QUERY: {query}
SKILL APPLIED: {skill_name} — {skill_description}
AI RESPONSE (first 800 chars): {response_snippet}

Score 1-5:
1 = Wrong/harmful/irrelevant
2 = Partially relevant but incomplete or inaccurate
3 = Adequate but could be better
4 = Good, addresses the query well
5 = Excellent, comprehensive and well-structured

Respond with ONLY this JSON:
{{"score": <1-5>, "reasoning": "<one sentence>"}}"""


class ResponseEvaluator:
    """
    Evaluates response quality to provide feedback for skill evolution.
    Supports both LLM-based and heuristic evaluation modes.
    """

    def __init__(self, skill_store: SkillStore):
        self.skill_store = skill_store
        self._llm_available = False
        self._llm_base_url: Optional[str] = None

    def set_llm_endpoint(self, base_url: str) -> None:
        """
        Configure the local LLM endpoint for evaluation.
        Typically LM Studio (localhost:1234) or Ollama (localhost:11434).

        Args:
            base_url: The base URL of the local LLM API.
        """
        self._llm_base_url = base_url
        self._llm_available = True
        logger.info(f"Evaluator LLM endpoint set: {base_url}")

    async def evaluate(
        self,
        query: str,
        response: str,
        skill: Skill,
        message_id: str = "",
        conversation_id: str = "",
    ) -> SkillEvaluation:
        """
        Evaluate a response where a skill was applied.

        Tries LLM-based evaluation first, falls back to heuristics.

        Args:
            query: The user's original query.
            response: The LLM's response text.
            skill: The skill that was applied.
            message_id: ID of the message being evaluated.
            conversation_id: ID of the conversation.

        Returns:
            SkillEvaluation with score and reasoning.
        """
        score = 3.0
        reasoning = "Default score — no evaluation method available"

        # Try LLM-based evaluation first
        if self._llm_available and self._llm_base_url:
            try:
                score, reasoning = await self._llm_evaluate(query, response, skill)
            except Exception as e:
                logger.warning(f"LLM evaluation failed, falling back to heuristics: {e}")
                score, reasoning = self._heuristic_evaluate(query, response, skill)
        else:
            score, reasoning = self._heuristic_evaluate(query, response, skill)

        evaluation = SkillEvaluation(
            id=str(uuid.uuid4()),
            skill_id=skill.id,
            message_id=message_id,
            conversation_id=conversation_id,
            score=score,
            reasoning=reasoning,
            query_text=query[:200],
            response_snippet=response[:500],
            evaluated_at=time.time(),
        )

        # Persist evaluation
        self.skill_store.record_evaluation(evaluation)

        # Update skill confidence based on result
        success = score >= 3.5
        new_confidence = self.skill_store.update_confidence(skill.id, success)
        logger.info(
            f"Skill '{skill.name}' evaluated: score={score:.1f} "
            f"success={success} new_confidence={new_confidence:.3f}"
        )

        return evaluation

    async def _llm_evaluate(
        self, query: str, response: str, skill: Skill
    ) -> Tuple[float, str]:
        """
        Call local LLM for evaluation. Uses OpenAI-compatible API format.

        Returns:
            Tuple of (score, reasoning).
        """
        import httpx

        prompt = EVAL_PROMPT.format(
            query=query[:300],
            skill_name=skill.name,
            skill_description=skill.description[:200],
            response_snippet=response[:800],
        )

        payload = {
            "model": "local-model",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 100,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self._llm_base_url}/v1/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["choices"][0]["message"]["content"].strip()

        # Parse JSON from response (handle markdown code blocks)
        json_match = re.search(r"\{[^}]+\}", content)
        if json_match:
            parsed = json.loads(json_match.group())
            score = float(parsed.get("score", 3))
            reasoning = parsed.get("reasoning", "LLM evaluation")
            score = max(1.0, min(5.0, score))
            return score, reasoning

        logger.warning(f"Could not parse LLM evaluation response: {content[:100]}")
        return 3.0, "LLM response unparseable, defaulting to neutral"

    def _heuristic_evaluate(
        self, query: str, response: str, skill: Skill
    ) -> Tuple[float, str]:
        """
        Heuristic-based evaluation when no LLM is available.
        Scores based on structural quality signals.

        Returns:
            Tuple of (score, reasoning).
        """
        signals = []
        score = 3.0  # Start neutral

        query_words = len(query.split())
        response_words = len(response.split())

        # Signal 1: Response length proportional to query complexity
        if query_words > 10 and response_words > 100:
            score += 0.3
            signals.append("good_length")
        elif response_words < 20:
            score -= 0.5
            signals.append("too_short")
        elif response_words > 50:
            score += 0.1
            signals.append("adequate_length")

        # Signal 2: For research/factual skills, check for structure
        if skill.skill_type in ("search_strategy", "retrieval_combo"):
            # Sources/citations present?
            if re.search(r"\[\d+\]|https?://|source:|according to", response, re.I):
                score += 0.5
                signals.append("has_citations")
            # Bullet points or numbered lists?
            if re.search(r"^\s*[-*•]\s|^\s*\d+[\.\)]\s", response, re.M):
                score += 0.2
                signals.append("has_structure")

        # Signal 3: For technical skills, check for code blocks
        if skill.skill_type == "response_format" and "code" in skill.name.lower():
            if "```" in response:
                score += 0.5
                signals.append("has_code_block")

        # Signal 4: For error_recovery skills, check if response acknowledges the issue
        if skill.skill_type == "error_recovery":
            if re.search(r"sorry|unfortunately|instead|alternative|however", response, re.I):
                score += 0.3
                signals.append("acknowledges_issue")

        # Signal 5: Response shouldn't just repeat the query
        if response_words > 5:
            query_set = set(query.lower().split())
            response_set = set(response.lower().split()[:50])
            overlap = len(query_set & response_set) / max(len(query_set), 1)
            if overlap > 0.8:
                score -= 0.5
                signals.append("mostly_repeats_query")

        score = max(1.0, min(5.0, score))
        reasoning = f"Heuristic eval: {', '.join(signals) if signals else 'neutral'}"

        return round(score, 1), reasoning
