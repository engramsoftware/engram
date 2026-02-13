"""
LLM-based entity and relationship extraction for the knowledge graph.

Replaces the old GLiNER + spaCy pipeline with LLM-based structured output
extraction that works with ANY LLM provider (OpenAI, Anthropic, LM Studio,
Ollama).

Architecture:
1. Single LLM call extracts entities AND relationships as JSON
2. Entities are normalized (lowercase, trimmed, deduplicated)
3. Relationships use semantic labels (lives_in, prefers, works_at)
4. Provider-agnostic: uses the same LLMProvider interface as chat

The prompt uses JSON-in-prompt (not function calling) so it works with
local LLMs that don't support tool use.
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


# ============================================================
# Data classes (backward-compatible with old Entity/Relationship)
# ============================================================

@dataclass
class Entity:
    """An entity extracted from conversational text.

    Attributes:
        text: Canonical entity name (e.g. "Kauai", "Gordon Ramsay").
        type: Semantic type assigned by the LLM (e.g. "person", "location").
        confidence: Extraction confidence (0.0-1.0).
        source: Always "llm" for this extractor.
    """
    text: str
    type: str
    confidence: float = 0.9
    source: str = "llm"


@dataclass
class Relationship:
    """A relationship between two entities.

    Attributes:
        subject: Source entity name.
        predicate: Semantic relationship label (e.g. "lives_in", "prefers").
        object: Target entity name.
        confidence: Extraction confidence (0.0-1.0).
        source: Always "llm" for this extractor.
    """
    subject: str
    predicate: str
    object: str
    confidence: float = 0.9
    source: str = "llm"


# ============================================================
# Extraction prompt
# ============================================================

_EXTRACTION_SYSTEM = (
    "You are a knowledge graph extraction engine. "
    "You extract entities and relationships from conversations and output ONLY valid JSON."
)

_EXTRACTION_USER_TEMPLATE = (
    "Extract entities and relationships from the conversation below.\n"
    "\n"
    "RULES:\n"
    "- Extract ONLY named entities that are specific and meaningful "
    "(people, places, organizations, technologies, products, events, decisions, preferences)\n"
    "- Do NOT extract generic words (time, people, things, stuff, way, something)\n"
    "- Do NOT extract pronouns (he, she, it, they, this, that)\n"
    "- Do NOT extract sentence fragments or phrases longer than 4 words\n"
    "- Do NOT extract prices, dates, or numbers as entities\n"
    "- Do NOT extract markdown artifacts (bullets, headers, formatting)\n"
    "- Normalize entity names: proper capitalization, full names not abbreviations\n"
    "- If the same entity appears with different names, pick the most specific one\n"
    "- For relationships, use short snake_case verbs "
    "(lives_in, prefers, works_at, visited, wants_to_visit, uses, built_with)\n"
    "- Only create relationships where BOTH subject and object are in your entity list\n"
    "- Extract 0-15 entities max. Quality over quantity. Skip if nothing meaningful.\n"
    "\n"
    "ENTITY TYPES (pick the best fit):\n"
    "person, location, organization, technology, product, event, "
    "concept, decision, preference, project, framework, tool\n"
    "\n"
    "OUTPUT FORMAT - respond with ONLY this JSON, no other text:\n"
    '{{\n'
    '  "entities": [\n'
    '    {{"name": "Entity Name", "type": "type"}}\n'
    '  ],\n'
    '  "relationships": [\n'
    '    {{"subject": "Entity A", "predicate": "relationship_verb", "object": "Entity B"}}\n'
    '  ]\n'
    '}}\n'
    "\n"
    "If there is nothing meaningful to extract, respond with:\n"
    '{{"entities": [], "relationships": []}}\n'
    "\n"
    "CONVERSATION:\n"
    "User: {user_query}\n"
    "Assistant: {assistant_response}"
)

# Maximum text length sent to the LLM for extraction (chars).
# Longer texts are truncated to avoid blowing the context window
# on the cheap extraction model.
_MAX_EXTRACTION_TEXT = 4000

# Allowed entity types — reject anything the LLM hallucinates outside this set
_ALLOWED_TYPES = {
    "person", "location", "organization", "technology", "product",
    "event", "concept", "decision", "preference", "project",
    "framework", "tool",
}

# Minimum entity name length
_MIN_ENTITY_LENGTH = 2

# Maximum entity name length (rejects sentence fragments)
_MAX_ENTITY_LENGTH = 50


# ============================================================
# JSON parsing helpers
# ============================================================

def _extract_json(text: str) -> Optional[Dict]:
    """Extract JSON from LLM response, handling markdown fences and preamble.

    LLMs often wrap JSON in ```json ... ``` or add explanatory text before/after.
    This function robustly extracts the JSON object.

    Args:
        text: Raw LLM response text.

    Returns:
        Parsed dict or None if parsing fails.
    """
    if not text or not text.strip():
        return None

    # Strip markdown code fences
    text = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text.strip(), flags=re.MULTILINE)

    # Try direct parse first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # Find the first { ... } block (greedy)
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    logger.debug(f"Failed to parse JSON from LLM response: {text[:200]}")
    return None


def _is_valid_entity_name(name: str) -> bool:
    """Validate that an entity name is meaningful, not noise.

    Rejects generic words, pronouns, markdown artifacts, numbers,
    and sentence fragments that NER models used to let through.

    Args:
        name: Entity name to validate.

    Returns:
        True if the entity name is valid.
    """
    if not name or not name.strip():
        return False

    name = name.strip()

    # Length checks
    if len(name) < _MIN_ENTITY_LENGTH or len(name) > _MAX_ENTITY_LENGTH:
        return False

    # Reject pure numbers / prices
    if re.match(r"^[\d$€£¥,.%+\-/\s]+$", name):
        return False

    # Reject markdown artifacts
    if name.startswith(("-", "*", "#", ">", "|", "```")):
        return False
    if name.endswith(("**", "```", "|")):
        return False

    # Reject strings with unbalanced parens/brackets (sentence fragments)
    if name.count("(") != name.count(")"):
        return False
    if name.count("[") != name.count("]"):
        return False

    # Reject if it contains pipe characters (table fragments)
    if "|" in name:
        return False

    # Reject common noise words that LLMs sometimes still extract
    _NOISE = {
        "i", "me", "my", "you", "your", "we", "us", "our",
        "he", "she", "it", "they", "them", "his", "her", "its", "their",
        "this", "that", "these", "those", "the", "a", "an",
        "something", "someone", "anyone", "everyone", "nothing",
        "people", "things", "stuff", "way", "time", "place",
        "yes", "no", "ok", "okay", "sure", "thanks", "hello", "hi",
        "one", "some", "many", "few", "all", "none", "other",
        "user", "assistant", "system", "message", "response",
    }
    if name.lower().strip() in _NOISE:
        return False

    # Reject if contains code-like operators (=, ->, =>, ++, etc.)
    if re.search(r"[=<>!]{1,2}|->|=>|\+\+|--|&&|\|\|", name):
        return False

    # Reject if mostly non-alphanumeric (code fragments, symbols)
    alpha_ratio = sum(c.isalpha() or c.isspace() for c in name) / max(len(name), 1)
    if alpha_ratio < 0.6:
        return False

    return True


# ============================================================
# Main extractor class
# ============================================================

class LLMEntityExtractor:
    """LLM-based entity and relationship extractor.

    Uses any LLMProvider to extract structured knowledge from conversations.
    Designed to work with cheap models (GPT-4o-mini, Claude Haiku, local LLMs).

    Usage:
        extractor = LLMEntityExtractor()
        entities, relationships = await extractor.extract(
            user_query="I'm planning a trip to Kauai",
            assistant_response="Great choice! Kauai has amazing beaches...",
            provider=llm_provider,
            model="gpt-4o-mini",
        )
    """

    def __init__(self) -> None:
        """Initialize the extractor. No models to load — uses LLM provider."""
        self._initialized = True
        logger.info("LLMEntityExtractor initialized (uses LLM provider for extraction)")

    @property
    def is_available(self) -> bool:
        """Always available — depends on LLM provider passed at call time."""
        return self._initialized

    async def extract(
        self,
        user_query: str,
        assistant_response: str,
        provider: Any,
        model: Optional[str] = None,
    ) -> Tuple[List[Entity], List[Relationship]]:
        """Extract entities and relationships from a conversation turn.

        Makes a single LLM call to extract both entities and relationships
        as structured JSON. The LLM understands conversational context far
        better than NER models for informal text.

        Args:
            user_query: The user's message.
            assistant_response: The assistant's response.
            provider: Any LLMProvider instance (OpenAI, Anthropic, LM Studio, etc.).
            model: Model name to use. If None, provider picks its default.

        Returns:
            Tuple of (entities, relationships). Empty lists if extraction
            fails or nothing meaningful is found.
        """
        if not provider:
            logger.warning("No LLM provider for entity extraction")
            return [], []

        # Truncate long texts to stay within cheap model context limits
        user_text = user_query[:_MAX_EXTRACTION_TEXT // 2] if user_query else ""
        asst_text = assistant_response[:_MAX_EXTRACTION_TEXT // 2] if assistant_response else ""

        if not user_text.strip() and not asst_text.strip():
            return [], []

        # Build the extraction prompt
        user_prompt = _EXTRACTION_USER_TEMPLATE.format(
            user_query=user_text,
            assistant_response=asst_text,
        )

        try:
            response = await provider.generate(
                messages=[
                    {"role": "system", "content": _EXTRACTION_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                model=model,
                temperature=0.1,
                max_tokens=1500,
            )

            raw = response.content if hasattr(response, "content") else str(response)
            parsed = _extract_json(raw)

            if not parsed:
                logger.debug("Entity extraction returned no parseable JSON")
                return [], []

            entities = self._parse_entities(parsed.get("entities", []))
            relationships = self._parse_relationships(
                parsed.get("relationships", []), entities
            )

            logger.info(
                f"LLM extracted {len(entities)} entities, "
                f"{len(relationships)} relationships"
            )
            return entities, relationships

        except Exception as e:
            logger.error(f"LLM entity extraction failed: {e}")
            return [], []

    def _parse_entities(self, raw_entities: List[Dict]) -> List[Entity]:
        """Parse and validate entities from LLM JSON output.

        Deduplicates by normalized name, validates types, rejects noise.

        Args:
            raw_entities: List of dicts from LLM JSON (name, type).

        Returns:
            Validated and deduplicated list of Entity objects.
        """
        seen: Dict[str, Entity] = {}

        for item in raw_entities:
            if not isinstance(item, dict):
                continue

            name = str(item.get("name", "")).strip()
            etype = str(item.get("type", "")).strip().lower()

            if not _is_valid_entity_name(name):
                continue

            # Normalize type to allowed set, default to "concept"
            if etype not in _ALLOWED_TYPES:
                etype = "concept"

            # Deduplicate by lowercase name — keep first occurrence
            key = name.lower()
            if key not in seen:
                seen[key] = Entity(
                    text=name,
                    type=etype,
                    confidence=0.9,
                    source="llm",
                )

        return list(seen.values())

    def _parse_relationships(
        self,
        raw_rels: List[Dict],
        entities: List[Entity],
    ) -> List[Relationship]:
        """Parse and validate relationships from LLM JSON output.

        Only keeps relationships where both subject and object match
        an extracted entity (case-insensitive).

        Args:
            raw_rels: List of dicts from LLM JSON (subject, predicate, object).
            entities: Validated entity list to cross-reference.

        Returns:
            Validated list of Relationship objects.
        """
        # Build entity name lookup (lowercase)
        entity_names = {e.text.lower() for e in entities}

        relationships: List[Relationship] = []
        seen_keys: set = set()

        for item in raw_rels:
            if not isinstance(item, dict):
                continue

            subject = str(item.get("subject", "")).strip()
            predicate = str(item.get("predicate", "")).strip().lower()
            obj = str(item.get("object", "")).strip()

            if not subject or not predicate or not obj:
                continue

            # Both endpoints must be in our entity list
            if subject.lower() not in entity_names:
                continue
            if obj.lower() not in entity_names:
                continue

            # No self-loops
            if subject.lower() == obj.lower():
                continue

            # Normalize predicate: snake_case, strip spaces
            predicate = re.sub(r"[^a-z0-9_]", "_", predicate)
            predicate = re.sub(r"_+", "_", predicate).strip("_")
            if not predicate:
                predicate = "relates_to"

            # Deduplicate
            key = (subject.lower(), predicate, obj.lower())
            if key in seen_keys:
                continue
            seen_keys.add(key)

            relationships.append(Relationship(
                subject=subject,
                predicate=predicate,
                object=obj,
                confidence=0.9,
                source="llm",
            ))

        return relationships

    # Keep backward-compatible method name used by outlet.py
    async def extract_entities_and_relations(
        self,
        text: str,
        provider: Any = None,
        model: Optional[str] = None,
    ) -> Tuple[List[Entity], List[Relationship]]:
        """Backward-compatible wrapper that splits text into user/assistant parts.

        Args:
            text: Combined "user_query\\nassistant_response" text.
            provider: LLM provider instance.
            model: Model name.

        Returns:
            Tuple of (entities, relationships).
        """
        # Split on first newline to separate user query from assistant response
        parts = text.split("\n", 1)
        user_query = parts[0] if parts else text
        assistant_response = parts[1] if len(parts) > 1 else ""
        return await self.extract(user_query, assistant_response, provider, model)


# ============================================================
# Module-level singleton
# ============================================================

_llm_entity_extractor: Optional[LLMEntityExtractor] = None


def get_llm_entity_extractor() -> LLMEntityExtractor:
    """Get or create the singleton LLMEntityExtractor instance.

    Returns:
        LLMEntityExtractor singleton.
    """
    global _llm_entity_extractor
    if _llm_entity_extractor is None:
        _llm_entity_extractor = LLMEntityExtractor()
    return _llm_entity_extractor
