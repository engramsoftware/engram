"""
Curriculum Engine — Proposes new skills to learn based on gaps in the library.

Inspired by Voyager's automatic curriculum that maximizes exploration.
Instead of Minecraft tech tree milestones, we use query type coverage:
- Identifies which query types have no skills or low-confidence skills
- Generates candidate skills from successful conversation patterns
- Composes existing skills into more complex multi-step strategies
- Proposes "practice" evaluations to verify candidate skills

The curriculum runs periodically (not on every message) to avoid overhead.
It uses the local LLM when available, or rule-based generation as fallback.

Curriculum progression:
  Level 1 (Basic): Single-source retrieval skills
  Level 2 (Intermediate): Multi-source combination skills
  Level 3 (Advanced): Composed skills with verification loops
  Level 4 (Expert): Adaptive skills that change strategy mid-response
"""

import re
import json
import time
import uuid
import logging
import asyncio
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from .skill_store import SkillStore, Skill
from .query_classifier import QueryClassifier, KEYWORD_TAXONOMY

logger = logging.getLogger(__name__)

# Skill templates for each query type — used as seeds when no skills exist
SKILL_TEMPLATES: Dict[str, Dict[str, Dict[str, Any]]] = {
    "factual": {
        "definition": {
            "name": "concise_definition",
            "strategy": "Provide a clear, concise definition first (1-2 sentences), then elaborate with context and examples. Use authoritative language.",
            "trigger_patterns": ["what is", "define", "meaning of", "what are"],
        },
        "comparison": {
            "name": "structured_comparison",
            "strategy": "Format the comparison as a structured table or side-by-side analysis. Cover: key differences, similarities, use cases, and recommendation. Include pros/cons for each.",
            "trigger_patterns": ["compare", "versus", "vs", "difference between", "better than"],
        },
        "lookup": {
            "name": "fact_lookup",
            "strategy": "Provide the direct answer first, then supporting context. Cite sources when available. If uncertain, state confidence level.",
            "trigger_patterns": ["who is", "when did", "where is", "how many"],
        },
    },
    "research": {
        "deep_dive": {
            "name": "deep_research",
            "strategy": "Structure as: Overview → Key Concepts → Details → Examples → Summary. Use headers for navigation. Aim for comprehensive but scannable output.",
            "trigger_patterns": ["explain in detail", "deep dive", "comprehensive", "thorough explanation"],
        },
        "multi_source": {
            "name": "multi_source_synthesis",
            "strategy": "Search multiple sources (web + memories + documents). Synthesize findings into a coherent narrative. Number sources [1]-[5] for citation. Highlight agreements and contradictions between sources.",
            "trigger_patterns": ["find everything", "research", "all about", "investigate"],
        },
        "current_events": {
            "name": "current_events_search",
            "strategy": "Always use web search for time-sensitive queries. Lead with the most recent information. Include dates. Flag if information may be outdated. Cross-reference multiple sources.",
            "trigger_patterns": ["latest", "recent news", "current", "today", "this week"],
        },
    },
    "creative": {
        "writing": {
            "name": "creative_writing",
            "strategy": "Match the requested format exactly (poem, story, essay). Use vivid language and varied sentence structure. Include a compelling opening and satisfying conclusion.",
            "trigger_patterns": ["write a poem", "write a story", "compose", "draft an essay"],
        },
        "brainstorm": {
            "name": "brainstorm_generator",
            "strategy": "Generate 5-10 diverse ideas. Range from conventional to creative. For each idea: one-line pitch + brief explanation. Organize by feasibility or category.",
            "trigger_patterns": ["ideas for", "brainstorm", "suggest", "come up with"],
        },
    },
    "technical": {
        "code_debug": {
            "name": "debug_assistant",
            "strategy": "1) Identify the error type. 2) Explain root cause. 3) Provide the fix with code. 4) Explain why the fix works. 5) Suggest prevention. Always show before/after code.",
            "trigger_patterns": ["fix this error", "debug", "not working", "exception", "traceback"],
        },
        "code_generate": {
            "name": "code_generator",
            "strategy": "1) Clarify requirements from the query. 2) Choose appropriate approach. 3) Write clean, commented code. 4) Include error handling. 5) Add usage example. Follow the user's language/framework.",
            "trigger_patterns": ["write a function", "implement", "create a script", "build a"],
        },
    },
    "conversational": {
        "follow_up": {
            "name": "context_aware_followup",
            "strategy": "Reference the previous conversation context explicitly. Connect the follow-up to prior points. If the reference is ambiguous, ask a clarifying question before answering.",
            "trigger_patterns": ["what about", "and also", "how about", "can you also"],
        },
        "clarification": {
            "name": "adaptive_explainer",
            "strategy": "Restate the concept using different words and analogies. Start simpler than the original. Use concrete examples. Offer to go even simpler or more detailed.",
            "trigger_patterns": ["explain differently", "simpler", "eli5", "rephrase"],
        },
    },
}

# Composition templates: how to combine Level 1 skills into Level 2+
COMPOSITION_RULES: List[Dict[str, Any]] = [
    {
        "name": "search_then_compare",
        "parents": ["multi_source_synthesis", "structured_comparison"],
        "strategy": "First search multiple sources for information on both items, then structure a comparison table from the gathered data. Cite sources for each claim.",
        "skill_type": "retrieval_combo",
        "level": 2,
        "trigger_patterns": ["compare using latest data", "research and compare", "which is better based on"],
    },
    {
        "name": "debug_with_search",
        "parents": ["debug_assistant", "current_events_search"],
        "strategy": "1) Analyze the error locally. 2) Search for the specific error message online. 3) Cross-reference Stack Overflow / GitHub issues. 4) Synthesize a solution from multiple sources. 5) Provide tested fix with explanation.",
        "skill_type": "retrieval_combo",
        "level": 2,
        "trigger_patterns": ["search for this error", "find solution online", "anyone else had this"],
    },
    {
        "name": "research_then_explain_simply",
        "parents": ["deep_research", "adaptive_explainer"],
        "strategy": "First gather comprehensive information, then distill it into an ELI5 explanation. Start with a one-sentence summary, then build complexity gradually. Use analogies from everyday life.",
        "skill_type": "response_format",
        "level": 2,
        "trigger_patterns": ["explain like i'm five", "simple explanation of complex", "break down"],
    },
    {
        "name": "iterative_code_with_verification",
        "parents": ["code_generator", "debug_assistant"],
        "strategy": "1) Generate initial code. 2) Mentally trace through it for bugs. 3) If issues found, fix them before presenting. 4) Include test cases. 5) Note any edge cases the user should be aware of.",
        "skill_type": "response_format",
        "level": 3,
        "trigger_patterns": ["write and test", "implement with tests", "robust implementation"],
    },
]


@dataclass
class CurriculumProposal:
    """A proposed new skill for the library."""
    skill: Skill
    reason: str
    priority: float  # 0-1, higher = more important to learn
    level: int  # 1=basic, 2=intermediate, 3=advanced, 4=expert


class CurriculumEngine:
    """
    Proposes new skills based on gaps in the skill library.
    Runs periodically to grow the library progressively.
    """

    def __init__(self, skill_store: SkillStore, classifier: QueryClassifier):
        self.skill_store = skill_store
        self.classifier = classifier
        self._last_run: float = 0.0
        self._min_interval: float = 300.0  # 5 minutes between curriculum runs

    def should_run(self) -> bool:
        """Check if enough time has passed since last curriculum run."""
        return (time.time() - self._last_run) >= self._min_interval

    async def generate_proposals(self) -> List[CurriculumProposal]:
        """
        Analyze the skill library and propose new skills to learn.

        Strategy:
        1. Check coverage: which query types have no skills?
        2. Check confidence: which existing skills are underperforming?
        3. Check composition: which Level 2+ skills can be composed?
        4. Prioritize by estimated impact.

        Returns:
            List of CurriculumProposal sorted by priority.
        """
        self._last_run = time.time()
        proposals: List[CurriculumProposal] = []

        existing_skills = self.skill_store.get_all_skills()
        existing_names = {s.name for s in existing_skills}
        existing_by_type: Dict[str, List[Skill]] = {}
        for s in existing_skills:
            existing_by_type.setdefault(s.skill_type, []).append(s)

        # Phase 1: Seed missing basic skills from templates
        proposals.extend(self._seed_missing_skills(existing_names))

        # Phase 2: Propose compositions for Level 2+ skills
        proposals.extend(self._propose_compositions(existing_names, existing_skills))

        # Phase 3: Propose replacements for deprecated skills
        proposals.extend(self._propose_replacements(existing_skills))

        # Sort by priority (highest first)
        proposals.sort(key=lambda p: p.priority, reverse=True)

        logger.info(f"Curriculum generated {len(proposals)} proposals")
        return proposals

    async def auto_seed(self, max_seeds: int = 5) -> int:
        """
        Automatically add seed skills from templates if library is empty or sparse.
        Called on first run to bootstrap the skill library.

        Args:
            max_seeds: Maximum number of skills to seed at once.

        Returns:
            Number of skills actually added.
        """
        proposals = await self.generate_proposals()
        added = 0

        for proposal in proposals[:max_seeds]:
            if proposal.level <= 1:  # Only seed Level 1 skills automatically
                success = self.skill_store.add_skill(proposal.skill)
                if success:
                    added += 1
                    logger.info(f"Auto-seeded skill: {proposal.skill.name}")

        return added

    def _seed_missing_skills(self, existing_names: set) -> List[CurriculumProposal]:
        """Generate proposals for missing basic skills from templates."""
        proposals = []

        for primary_type, subs in SKILL_TEMPLATES.items():
            for sub_type, template in subs.items():
                if template["name"] not in existing_names:
                    skill = Skill(
                        id=str(uuid.uuid4()),
                        name=template["name"],
                        skill_type=self._map_type(primary_type, sub_type),
                        description=f"Auto-generated {primary_type}/{sub_type} skill",
                        strategy=template["strategy"],
                        trigger_patterns=template["trigger_patterns"],
                        confidence=0.5,
                        state="candidate",
                        source="curriculum",
                        created_at=time.time(),
                    )
                    proposals.append(CurriculumProposal(
                        skill=skill,
                        reason=f"No skill exists for {primary_type}/{sub_type} queries",
                        priority=0.8,
                        level=1,
                    ))

        return proposals

    def _propose_compositions(
        self, existing_names: set, existing_skills: List[Skill]
    ) -> List[CurriculumProposal]:
        """Propose composed skills when their parents exist and are verified."""
        proposals = []
        skill_name_map = {s.name: s for s in existing_skills}

        for rule in COMPOSITION_RULES:
            if rule["name"] in existing_names:
                continue  # Already exists

            # Check if all parent skills exist and are at least verified
            parents_ready = True
            parent_ids = []
            for parent_name in rule["parents"]:
                parent = skill_name_map.get(parent_name)
                if not parent or parent.state not in ("verified", "mastered"):
                    parents_ready = False
                    break
                parent_ids.append(parent.id)

            if parents_ready:
                skill = Skill(
                    id=str(uuid.uuid4()),
                    name=rule["name"],
                    skill_type=rule["skill_type"],
                    description=f"Composed from: {', '.join(rule['parents'])}",
                    strategy=rule["strategy"],
                    trigger_patterns=rule["trigger_patterns"],
                    confidence=0.5,
                    parent_skill_ids=parent_ids,
                    state="candidate",
                    source="composed",
                    created_at=time.time(),
                )
                proposals.append(CurriculumProposal(
                    skill=skill,
                    reason=f"Parents {rule['parents']} are verified — ready to compose",
                    priority=0.7,
                    level=rule["level"],
                ))

        return proposals

    def _propose_replacements(self, existing_skills: List[Skill]) -> List[CurriculumProposal]:
        """Propose replacement skills for deprecated ones."""
        proposals = []

        for skill in existing_skills:
            if skill.state == "deprecated" and skill.times_used >= 3:
                # The deprecated skill was used enough to matter — propose an improved version
                new_skill = Skill(
                    id=str(uuid.uuid4()),
                    name=f"{skill.name}_v2",
                    skill_type=skill.skill_type,
                    description=f"Improved version of deprecated '{skill.name}'",
                    strategy=skill.strategy + "\n\n[IMPROVEMENT NEEDED: Previous version failed. Adjust strategy based on evaluation feedback.]",
                    trigger_patterns=skill.trigger_patterns,
                    confidence=0.5,
                    parent_skill_ids=[skill.id],
                    state="candidate",
                    source="curriculum",
                    created_at=time.time(),
                )
                proposals.append(CurriculumProposal(
                    skill=new_skill,
                    reason=f"Skill '{skill.name}' was deprecated after {skill.times_failed} failures",
                    priority=0.6,
                    level=1,
                ))

        return proposals

    @staticmethod
    def _map_type(primary: str, sub: str) -> str:
        """Map query type hierarchy to skill_type enum."""
        type_map = {
            ("factual", "comparison"): "response_format",
            ("research", "multi_source"): "retrieval_combo",
            ("research", "current_events"): "search_strategy",
            ("technical", "code_debug"): "error_recovery",
            ("technical", "code_generate"): "response_format",
            ("conversational", "follow_up"): "conversation_pattern",
            ("conversational", "clarification"): "conversation_pattern",
        }
        return type_map.get((primary, sub), "search_strategy")
