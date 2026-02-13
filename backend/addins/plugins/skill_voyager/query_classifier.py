"""
Query Classifier — Categorizes incoming user messages into query types
so the skill library can match the right strategy.

Uses a combination of:
1. Regex-based pattern matching (fast, no LLM cost)
2. Keyword taxonomy (domain-specific signals)
3. Optional LLM-based classification (when local LLM available)

Query types form a hierarchy:
  factual
    ├── definition ("what is X")
    ├── lookup ("when did X happen")
    └── comparison ("X vs Y")
  research
    ├── deep_dive ("explain how X works in detail")
    ├── multi_source ("find everything about X")
    └── current_events ("latest news on X")
  creative
    ├── writing ("write a poem about X")
    ├── brainstorm ("ideas for X")
    └── roleplay ("pretend you are X")
  technical
    ├── code_debug ("fix this error")
    ├── code_generate ("write a function that")
    └── system_admin ("how to configure X")
  conversational
    ├── follow_up ("what about Y" after prior context)
    ├── clarification ("can you explain that differently")
    └── meta ("how do you work")
"""

import re
import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class QueryClassification:
    """Result of classifying a user query."""
    primary_type: str       # Top-level: factual, research, creative, technical, conversational
    sub_type: str           # Specific sub-category
    confidence: float       # 0.0 - 1.0
    signals: List[str]      # Which signals triggered this classification
    keywords: List[str]     # Extracted keywords from the query


# Pattern definitions: (regex, primary_type, sub_type, confidence_boost)
PATTERNS: List[Tuple[str, str, str, float]] = [
    # Factual - definitions
    (r"\b(?:what is|what are|define|definition of|meaning of)\b", "factual", "definition", 0.8),
    (r"\b(?:who is|who was|who are)\b", "factual", "lookup", 0.8),
    (r"\b(?:when did|when was|when is|what year)\b", "factual", "lookup", 0.8),
    (r"\b(?:where is|where was|where are)\b", "factual", "lookup", 0.7),

    # Factual - comparison
    (r"\b(?:compare|versus|vs\.?|difference between|better than|pros and cons)\b",
     "factual", "comparison", 0.85),

    # Research
    (r"\b(?:explain|in detail|deep dive|comprehensive|thorough|elaborate)\b",
     "research", "deep_dive", 0.7),
    (r"\b(?:find everything|research|investigate|all about|tell me everything)\b",
     "research", "multi_source", 0.75),
    (r"\b(?:latest|recent|news|current|today|this week|2025|2026)\b",
     "research", "current_events", 0.7),

    # Creative
    (r"\b(?:write|compose|draft|create|generate)\s+(?:a |an |the )?(?:poem|story|essay|article|blog|email|letter)\b",
     "creative", "writing", 0.85),
    (r"\b(?:ideas? for|brainstorm|suggest|come up with|think of)\b",
     "creative", "brainstorm", 0.7),
    (r"\b(?:pretend|roleplay|act as|you are a|imagine you)\b",
     "creative", "roleplay", 0.8),

    # Technical - code
    (r"\b(?:fix|debug|error|bug|exception|traceback|stack trace)\b",
     "technical", "code_debug", 0.8),
    (r"\b(?:write|create|implement|build|code)\s+(?:a |an |the )?(?:function|class|script|program|api|endpoint)\b",
     "technical", "code_generate", 0.85),
    (r"\b(?:how to (?:install|configure|setup|deploy|run))\b",
     "technical", "system_admin", 0.7),

    # Conversational
    (r"\b(?:what about|and also|how about|what if)\b",
     "conversational", "follow_up", 0.5),
    (r"\b(?:explain that|rephrase|say that again|differently|simpler|eli5)\b",
     "conversational", "clarification", 0.7),
    (r"\b(?:how do you work|what can you do|your capabilities|help me understand you)\b",
     "conversational", "meta", 0.8),
]

# Keyword taxonomy for secondary signal boosting
KEYWORD_TAXONOMY: Dict[str, Dict[str, List[str]]] = {
    "factual": {
        "definition": ["meaning", "define", "what", "explain briefly"],
        "lookup": ["who", "when", "where", "how many", "how much", "how old"],
        "comparison": ["compare", "versus", "better", "worse", "difference", "similar"],
    },
    "research": {
        "deep_dive": ["detail", "thorough", "comprehensive", "explain", "how does"],
        "multi_source": ["everything", "research", "investigate", "all sources"],
        "current_events": ["latest", "news", "recent", "today", "update"],
    },
    "creative": {
        "writing": ["write", "compose", "draft", "poem", "story", "essay"],
        "brainstorm": ["ideas", "brainstorm", "suggest", "options", "alternatives"],
        "roleplay": ["pretend", "roleplay", "character", "persona", "act as"],
    },
    "technical": {
        "code_debug": ["error", "fix", "bug", "debug", "traceback", "exception"],
        "code_generate": ["implement", "function", "class", "code", "script", "api"],
        "system_admin": ["install", "configure", "deploy", "setup", "docker", "server"],
    },
    "conversational": {
        "follow_up": ["also", "what about", "and", "too", "as well"],
        "clarification": ["rephrase", "simpler", "again", "clarify", "eli5"],
        "meta": ["capabilities", "how do you", "what can you"],
    },
}


class QueryClassifier:
    """
    Multi-signal query classifier.
    Combines regex patterns, keyword taxonomy, and structural features
    to classify user queries without requiring an LLM call.
    """

    def classify(self, query: str, conversation_history: Optional[List[Dict]] = None) -> QueryClassification:
        """
        Classify a user query into a type hierarchy.

        Args:
            query: The user's message text.
            conversation_history: Recent messages for follow-up detection.

        Returns:
            QueryClassification with type, sub-type, confidence, and signals.
        """
        query_lower = query.lower().strip()
        signals: List[str] = []
        scores: Dict[str, Dict[str, float]] = {}

        # Signal 1: Regex pattern matching
        for pattern, primary, sub, confidence in PATTERNS:
            if re.search(pattern, query_lower):
                key = f"{primary}/{sub}"
                if primary not in scores:
                    scores[primary] = {}
                scores[primary][sub] = max(scores[primary].get(sub, 0), confidence)
                signals.append(f"pattern:{key}")

        # Signal 2: Keyword taxonomy overlap
        query_words = set(query_lower.split())
        for primary, subs in KEYWORD_TAXONOMY.items():
            for sub, keywords in subs.items():
                overlap = sum(1 for kw in keywords if kw in query_lower)
                if overlap > 0:
                    kw_score = min(overlap * 0.2, 0.6)
                    if primary not in scores:
                        scores[primary] = {}
                    scores[primary][sub] = max(scores[primary].get(sub, 0), kw_score)
                    if kw_score >= 0.2:
                        signals.append(f"keywords:{primary}/{sub}")

        # Signal 3: Structural features
        structural_signals = self._structural_features(query_lower, query_words)
        for sig_name, primary, sub, boost in structural_signals:
            if primary not in scores:
                scores[primary] = {}
            scores[primary][sub] = max(scores[primary].get(sub, 0), boost)
            signals.append(f"structure:{sig_name}")

        # Signal 4: Follow-up detection from conversation history
        if conversation_history and len(conversation_history) >= 2:
            is_follow_up = self._detect_follow_up(query_lower, conversation_history)
            if is_follow_up:
                if "conversational" not in scores:
                    scores["conversational"] = {}
                scores["conversational"]["follow_up"] = max(
                    scores["conversational"].get("follow_up", 0), 0.6
                )
                signals.append("context:follow_up")

        # Pick the best classification
        best_primary = ""
        best_sub = ""
        best_score = 0.0

        for primary, subs in scores.items():
            for sub, score in subs.items():
                if score > best_score:
                    best_score = score
                    best_primary = primary
                    best_sub = sub

        # Default fallback
        if not best_primary:
            best_primary = "conversational"
            best_sub = "follow_up"
            best_score = 0.3
            signals.append("fallback:default")

        # Extract keywords
        keywords = self._extract_keywords(query_lower)

        return QueryClassification(
            primary_type=best_primary,
            sub_type=best_sub,
            confidence=round(best_score, 3),
            signals=signals,
            keywords=keywords,
        )

    def _structural_features(
        self, query_lower: str, query_words: set
    ) -> List[Tuple[str, str, str, float]]:
        """Extract structural signals from query shape."""
        features = []

        # Question mark → likely factual or research
        if "?" in query_lower:
            features.append(("has_question_mark", "factual", "definition", 0.3))

        # Long query (>20 words) → likely research or technical
        if len(query_words) > 20:
            features.append(("long_query", "research", "deep_dive", 0.3))

        # Code markers (backticks, function-like patterns)
        if "`" in query_lower or "```" in query_lower:
            features.append(("has_code", "technical", "code_debug", 0.5))

        # URL or file path
        if re.search(r"https?://|/[\w/]+\.\w+", query_lower):
            features.append(("has_url", "research", "multi_source", 0.3))

        # Short imperative ("do X", "make X")
        if len(query_words) <= 5 and query_lower.split()[0] in {
            "do", "make", "create", "build", "show", "list", "get", "find"
        }:
            features.append(("short_imperative", "technical", "code_generate", 0.3))

        return features

    def _detect_follow_up(
        self, query_lower: str, history: List[Dict]
    ) -> bool:
        """Detect if query is a follow-up to the previous conversation turn."""
        # Short messages after a conversation are likely follow-ups
        if len(query_lower.split()) <= 4:
            return True

        # Pronouns referencing prior context
        follow_up_markers = {"it", "that", "this", "those", "them", "they", "its"}
        first_words = set(query_lower.split()[:3])
        if first_words & follow_up_markers:
            return True

        return False

    @staticmethod
    def _extract_keywords(query_lower: str) -> List[str]:
        """Extract meaningful keywords from the query (strip stopwords)."""
        stopwords = {
            "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "can", "shall", "to", "of", "in", "for",
            "on", "with", "at", "by", "from", "as", "into", "through", "about",
            "it", "its", "i", "me", "my", "you", "your", "we", "our", "they",
            "them", "their", "this", "that", "these", "those", "and", "or", "but",
            "if", "then", "so", "not", "no", "what", "how", "when", "where",
            "who", "which", "why", "please", "just", "also", "very", "really",
        }
        words = re.findall(r"\b[a-z]{2,}\b", query_lower)
        return [w for w in words if w not in stopwords][:10]
