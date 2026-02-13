"""
Skill Extractor — Observes successful conversations and extracts new skills.

This is the "learning from experience" component, inspired by:
- Voyager's skill library that grows from successful programs
- Mem0's memory extraction from conversations
- SELF-REFINE's iterative feedback without external supervision

The extractor watches the outlet (post-LLM) pipeline and:
1. Classifies the query that was just answered
2. Checks if an existing skill was applied
3. If NO skill was applied but the response was good → extract a new candidate skill
4. If a skill WAS applied → evaluate and update confidence

Uses local LLM when available for high-quality extraction,
falls back to template-based extraction from structural patterns.
"""

import re
import json
import time
import uuid
import logging
from typing import List, Dict, Any, Optional, Tuple

from .skill_store import SkillStore, Skill
from .query_classifier import QueryClassifier, QueryClassification

logger = logging.getLogger(__name__)

# LLM prompt for extracting a skill from a successful conversation
EXTRACT_PROMPT = """Analyze this successful conversation exchange and extract a reusable response strategy.

USER QUERY: {query}
QUERY TYPE: {query_type}/{query_subtype}
AI RESPONSE (first 1000 chars): {response_snippet}

Extract a reusable strategy that could be applied to similar queries.
Respond with ONLY this JSON:
{{
  "name": "<short_snake_case_name>",
  "description": "<one sentence description>",
  "strategy": "<2-4 sentence instruction for the AI on how to handle this type of query>",
  "trigger_patterns": ["<pattern1>", "<pattern2>", "<pattern3>"]
}}"""


class SkillExtractor:
    """
    Extracts new skill candidates from successful conversations.
    Runs in the outlet (post-response) pipeline.
    """

    def __init__(self, skill_store: SkillStore, classifier: QueryClassifier):
        self.skill_store = skill_store
        self.classifier = classifier
        self._llm_available = False
        self._llm_base_url: Optional[str] = None
        # Track recent extractions to avoid duplicates
        self._recent_extractions: List[str] = []
        self._max_recent = 50

    def set_llm_endpoint(self, base_url: str) -> None:
        """Configure local LLM for high-quality extraction."""
        self._llm_base_url = base_url
        self._llm_available = True

    async def maybe_extract(
        self,
        query: str,
        response: str,
        classification: QueryClassification,
        skill_was_applied: bool,
        message_id: str = "",
        conversation_id: str = "",
    ) -> Optional[Skill]:
        """
        Decide whether to extract a new skill from this conversation turn.

        Extraction criteria:
        - No existing skill was applied (novel situation)
        - The response appears to be good quality (heuristic pre-check)
        - The query type is classifiable (not just follow-up noise)
        - We haven't recently extracted a similar skill

        Args:
            query: User's query text.
            response: LLM's response text.
            classification: How the query was classified.
            skill_was_applied: Whether an existing skill was used.
            message_id: Message ID for tracking.
            conversation_id: Conversation ID for tracking.

        Returns:
            New Skill if extracted, None otherwise.
        """
        # Don't extract if a skill was already applied (that path goes to evaluation)
        if skill_was_applied:
            return None

        # Don't extract from low-confidence classifications
        if classification.confidence < 0.5:
            return None

        # Don't extract from simple follow-ups or meta queries
        if classification.primary_type == "conversational" and classification.sub_type in ("follow_up", "meta"):
            return None

        # Pre-check response quality (quick heuristic)
        if not self._response_looks_good(query, response):
            return None

        # Check for duplicate extraction
        dedup_key = f"{classification.primary_type}/{classification.sub_type}"
        if dedup_key in self._recent_extractions:
            return None

        # Try LLM extraction first, fall back to template
        skill: Optional[Skill] = None
        if self._llm_available and self._llm_base_url:
            try:
                skill = await self._llm_extract(query, response, classification)
            except Exception as e:
                logger.warning(f"LLM extraction failed: {e}")

        if not skill:
            skill = self._template_extract(query, response, classification)

        if skill:
            # Check for near-duplicate in existing library
            existing = self.skill_store.find_matching_skills(query, min_confidence=0.0, limit=1)
            if existing and self._is_duplicate(skill, existing[0]):
                logger.debug(f"Skipping duplicate skill extraction: {skill.name}")
                return None

            # Add to store
            success = self.skill_store.add_skill(skill)
            if success:
                self._recent_extractions.append(dedup_key)
                if len(self._recent_extractions) > self._max_recent:
                    self._recent_extractions.pop(0)
                logger.info(
                    f"Extracted new skill: {skill.name} "
                    f"(type={skill.skill_type}, source=observed)"
                )
                return skill

        return None

    async def _llm_extract(
        self,
        query: str,
        response: str,
        classification: QueryClassification,
    ) -> Optional[Skill]:
        """Use local LLM to extract a skill from the conversation."""
        import httpx

        prompt = EXTRACT_PROMPT.format(
            query=query[:400],
            query_type=classification.primary_type,
            query_subtype=classification.sub_type,
            response_snippet=response[:1000],
        )

        payload = {
            "model": "local-model",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
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
        json_match = re.search(r"\{[^}]+\}", content, re.DOTALL)
        if not json_match:
            return None

        try:
            parsed = json.loads(json_match.group())
        except json.JSONDecodeError:
            return None

        name = parsed.get("name", "").strip()
        if not name or len(name) < 3:
            return None

        return Skill(
            id=str(uuid.uuid4()),
            name=name,
            skill_type=self._classify_to_skill_type(classification),
            description=parsed.get("description", "LLM-extracted skill"),
            strategy=parsed.get("strategy", ""),
            trigger_patterns=parsed.get("trigger_patterns", []),
            confidence=0.5,
            state="candidate",
            source="observed",
            created_at=time.time(),
        )

    def _template_extract(
        self,
        query: str,
        response: str,
        classification: QueryClassification,
    ) -> Optional[Skill]:
        """
        Template-based extraction when no LLM is available.
        Analyzes the response structure to infer what strategy was used.
        """
        strategy_parts = []
        name_parts = [classification.sub_type]

        # Analyze response structure
        has_headers = bool(re.search(r"^#+\s", response, re.M))
        has_bullets = bool(re.search(r"^\s*[-*•]\s", response, re.M))
        has_numbered = bool(re.search(r"^\s*\d+[\.\)]\s", response, re.M))
        has_code = "```" in response
        has_citations = bool(re.search(r"\[\d+\]|source:", response, re.I))
        has_table = "|" in response and "---" in response

        if has_headers:
            strategy_parts.append("Use markdown headers to organize sections")
        if has_bullets:
            strategy_parts.append("Use bullet points for key items")
        if has_numbered:
            strategy_parts.append("Use numbered steps for sequential information")
            name_parts.append("step_by_step")
        if has_code:
            strategy_parts.append("Include code blocks with syntax highlighting")
            name_parts.append("with_code")
        if has_citations:
            strategy_parts.append("Cite sources with numbered references")
            name_parts.append("cited")
        if has_table:
            strategy_parts.append("Use tables for structured comparisons")
            name_parts.append("tabular")

        if not strategy_parts:
            return None  # Can't infer a useful strategy

        # Build the skill
        name = "_".join(name_parts)
        # Ensure uniqueness
        name = f"{name}_{uuid.uuid4().hex[:6]}"

        strategy = (
            f"For {classification.primary_type}/{classification.sub_type} queries: "
            + ". ".join(strategy_parts) + "."
        )

        # Extract trigger patterns from the query's keywords
        triggers = classification.keywords[:3]
        if classification.sub_type not in triggers:
            triggers.insert(0, classification.sub_type)

        return Skill(
            id=str(uuid.uuid4()),
            name=name,
            skill_type=self._classify_to_skill_type(classification),
            description=f"Observed pattern for {classification.primary_type}/{classification.sub_type}",
            strategy=strategy,
            trigger_patterns=triggers,
            confidence=0.45,  # Slightly below threshold — needs one success to verify
            state="candidate",
            source="observed",
            created_at=time.time(),
        )

    def _response_looks_good(self, query: str, response: str) -> bool:
        """Quick heuristic check if the response is worth extracting from."""
        response_words = len(response.split())
        query_words = len(query.split())

        # Too short responses are unlikely to contain a useful strategy
        if response_words < 30:
            return False

        # Very long responses for very short queries → probably good
        if query_words <= 5 and response_words > 100:
            return True

        # Responses with structure are likely good
        has_structure = bool(
            re.search(r"^#+\s|^\s*[-*•]\s|^\s*\d+[\.\)]\s|```", response, re.M)
        )
        if has_structure and response_words > 50:
            return True

        # Moderate length responses are probably fine
        if response_words >= 80:
            return True

        return False

    @staticmethod
    def _is_duplicate(new_skill: Skill, existing: Skill) -> bool:
        """Check if a newly extracted skill is essentially the same as an existing one."""
        # Same name = definite duplicate
        if new_skill.name == existing.name:
            return True

        # High overlap in trigger patterns
        new_triggers = set(t.lower() for t in new_skill.trigger_patterns)
        existing_triggers = set(t.lower() for t in existing.trigger_patterns)
        if new_triggers and existing_triggers:
            overlap = len(new_triggers & existing_triggers)
            if overlap / max(len(new_triggers), 1) > 0.6:
                return True

        return False

    @staticmethod
    def _classify_to_skill_type(classification: QueryClassification) -> str:
        """Map query classification to skill type."""
        type_map = {
            "factual": "search_strategy",
            "research": "retrieval_combo",
            "creative": "response_format",
            "technical": "response_format",
            "conversational": "conversation_pattern",
        }
        return type_map.get(classification.primary_type, "search_strategy")
