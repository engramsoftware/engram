"""
Web search gate — decides WHEN to search and WHAT to search for.

Keyword-only approach: search ONLY triggers when the user explicitly
asks to search ("search", "find", "look up", "google", "research", etc.).
No adaptive scoring, no time-sensitive detection, no knowledge-intensive
question detection. Simple and predictable.

Also reformulates the user's message into an optimized search query and
scrubs PII before any query leaves the system (OWASP LLM Top 10 2025).
"""

import re
import logging
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)


# ── PII detection patterns ───────────────────────────────────────────
# Multi-layered approach: regex for structured PII (emails, phones, SSNs,
# credit cards, IPs) + context-aware name detection from conversation.
# Follows the "sanitize at point of exit" principle from Kong/OWASP.

_PII_PATTERNS = {
    # Email addresses
    "email": re.compile(
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b"
    ),
    # US phone numbers (various formats)
    "phone": re.compile(
        r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)"
    ),
    # SSN (XXX-XX-XXXX)
    "ssn": re.compile(
        r"\b\d{3}-\d{2}-\d{4}\b"
    ),
    # Credit card numbers (13-19 digits, with optional separators)
    "credit_card": re.compile(
        r"\b(?:\d[ -]*?){13,19}\b"
    ),
    # IP addresses (v4)
    "ip_address": re.compile(
        r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    ),
    # Street addresses (number + street name pattern)
    "street_address": re.compile(
        r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}(?:St|Street|Ave|Avenue|Blvd|Boulevard|Dr|Drive|Ln|Lane|Rd|Road|Ct|Court|Way|Pl|Place)\.?\b",
        re.IGNORECASE,
    ),
    # Dates of birth (MM/DD/YYYY, MM-DD-YYYY)
    "dob": re.compile(
        r"\b(?:0[1-9]|1[0-2])[/\-](?:0[1-9]|[12]\d|3[01])[/\-](?:19|20)\d{2}\b"
    ),
    # US ZIP codes
    "zip_code": re.compile(
        r"\b\d{5}(?:-\d{4})?\b"
    ),
}


def scrub_pii(text: str, context_names: Optional[List[str]] = None) -> str:
    """
    Remove personally identifiable information from text before it leaves
    the system (e.g., before sending to an external search API).

    Uses a multi-layered approach:
    1. Regex patterns for structured PII (emails, phones, SSNs, etc.)
    2. Context-aware name removal — names extracted from conversation
       history or user profile are scrubbed so they don't leak to Brave.

    Args:
        text: The text to scrub (typically a search query).
        context_names: Optional list of names from conversation context
                       (user name, mentioned people) to also redact.

    Returns:
        Scrubbed text with PII replaced by generic placeholders.
    """
    scrubbed = text

    # Layer 1: Regex-based structured PII removal
    pii_found = []
    for pii_type, pattern in _PII_PATTERNS.items():
        matches = pattern.findall(scrubbed)
        if matches:
            pii_found.append(f"{pii_type}({len(matches)})")
            scrubbed = pattern.sub("", scrubbed)

    # Layer 2: Context-aware name removal
    # Names from the user's profile or conversation are scrubbed so
    # queries like "What's John Smith's net worth" don't leak "John Smith"
    # when John Smith is the actual user.
    if context_names:
        for name in context_names:
            if not name or len(name) < 2:
                continue
            # Case-insensitive whole-word replacement
            name_pattern = re.compile(
                r"\b" + re.escape(name) + r"\b", re.IGNORECASE
            )
            scrubbed = name_pattern.sub("", scrubbed)

    # Layer 3: Possessive personal references that might carry context
    # "my husband's" → "" , "my doctor" → "doctor"
    scrubbed = re.sub(
        r"\b(my|our)\s+(husband|wife|partner|son|daughter|mom|dad|"
        r"mother|father|brother|sister|boss|doctor|therapist|lawyer|"
        r"accountant|friend|neighbor)('s)?\b",
        r"\2",
        scrubbed,
        flags=re.IGNORECASE,
    )

    # Clean up extra whitespace left by removals
    scrubbed = re.sub(r"\s+", " ", scrubbed).strip()

    if pii_found:
        logger.info(f"PII scrubbed from search query: {', '.join(pii_found)}")

    return scrubbed


# ── Explicit search keyword patterns ─────────────────────────────────
# Search ONLY triggers when the user explicitly asks to search.
# No adaptive scoring, no guessing, no time-sensitive detection.

_SEARCH_KEYWORDS = [
    r"\bsearch\b",                          # "search", "search for", "search this"
    r"\blook\s+(up|into|for)\b",             # "look up", "look into", "look for"
    r"\bgoogle\b",                           # "google it", "google this"
    r"\bfind\b",                             # "find", "find me", "find info"
    r"\bbrowse\b",                           # "browse the web"
    r"\bresearch\b",                         # "research this"
    r"\bweb\s+search\b",                     # "web search"
    r"\brun\s+a\s+(web\s+)?search\b",        # "run a search"
    r"\bcheck\s+(online|the\s+web|the\s+internet)\b",  # "check online"
]

# ── Tool intent exclusions ────────────────────────────────────────────
# When the user's message matches another tool's intent, web search
# should NOT trigger even if a search keyword is present.
# "search my email" → email tool, NOT web search
# "find my budget" → budget tool, NOT web search
# "check my schedule" → schedule tool, NOT web search
# This implements priority-based intent routing (Arize best practice).
_TOOL_EXCLUSION_PATTERNS = [
    # Email intent — "search my email", "find email from", "check inbox"
    re.compile(
        r"\b(email|inbox|mail|gmail|e-mail)"
        r"|\b(search|check|find|look|read).{0,10}(email|inbox|mail)"
        r"|\b(email|inbox|mail).{0,10}(search|check|find|look|read)",
        re.IGNORECASE,
    ),
    # Schedule intent — "search my calendar", "find appointment"
    re.compile(
        r"\b(calendar|schedule|appointment|agenda)"
        r"|\b(search|check|find).{0,10}(calendar|schedule|appointment)"
        r"|\bwhat.{0,8}(today|tomorrow|this week|next week)",
        re.IGNORECASE,
    ),
    # Budget intent — "find my expenses", "search spending"
    re.compile(
        r"\b(budget|expense|spending|spent)"
        r"|\b(search|check|find).{0,10}(budget|expense|spending)",
        re.IGNORECASE,
    ),
]

# Words to strip from search queries (conversational filler)
_FILLER_WORDS = re.compile(
    r"\b(please|can you|could you|would you|i want to know|tell me|"
    r"i need|help me|i'm curious|i was wondering|do you know|"
    r"hey|hi|hello|thanks|thank you|actually|basically|literally|"
    r"just|really|very|so|like|um|uh|well|anyway|btw|fyi)\b",
    re.IGNORECASE,
)


def _has_search_keyword(text: str) -> bool:
    """Check if text contains any explicit search keyword.

    Args:
        text: The user's message.

    Returns:
        True if the message contains an explicit search trigger word.
    """
    for pattern in _SEARCH_KEYWORDS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _matches_tool_intent(text: str) -> Optional[str]:
    """Check if text matches another tool's intent (email, schedule, budget).

    When the user says 'search my email' or 'find my expenses',
    the query should route to the specific tool, NOT to web search.

    Args:
        text: The user's message.

    Returns:
        Tool name string if matched ('email', 'schedule', 'budget'),
        or None if no tool intent detected.
    """
    tool_names = ["email", "schedule", "budget"]
    for pattern, name in zip(_TOOL_EXCLUSION_PATTERNS, tool_names):
        if pattern.search(text):
            return name
    return None


def should_web_search(
    message: str,
    conversation_history: Optional[list] = None,
    threshold: float = 0.40,
) -> Tuple[bool, float, str]:
    """Decide whether a user message warrants a web search.

    Keyword-only: search triggers ONLY when the user explicitly uses a
    search keyword (search, find, look up, google, research, browse, etc.).
    No adaptive scoring, no guessing.

    Priority routing: if the message matches another tool's intent
    (email, schedule, budget), web search is SKIPPED even if search
    keywords are present. 'search my email' → email tool, not web.

    Args:
        message: The user's current message.
        conversation_history: Unused, kept for API compatibility.
        threshold: Unused, kept for API compatibility.

    Returns:
        Tuple of (should_search, score, reason).
    """
    # Priority check: another tool handles this query
    tool_match = _matches_tool_intent(message)
    if tool_match:
        logger.info(
            f"Web search gate: NO (routed to {tool_match} tool) "
            f"query='{message[:80]}'"
        )
        return False, 0.0, f"routed_to_{tool_match}"

    if _has_search_keyword(message):
        logger.info(
            f"Web search gate: YES (explicit keyword) "
            f"query='{message[:80]}'"
        )
        return True, 1.0, "explicit_keyword"

    logger.debug(
        f"Web search gate: NO (no search keyword) "
        f"query='{message[:80]}'"
    )
    return False, 0.0, "no_keyword"


def reformulate_search_query(message: str) -> str:
    """
    Reformulate a conversational message into an optimized search query.

    Strips conversational filler, politeness markers, and self-references
    to produce a concise, keyword-rich query that works well with search
    APIs.

    Args:
        message: The user's raw message.

    Returns:
        A cleaned-up search query string.
    """
    query = message.strip()

    # Remove filler words
    query = _FILLER_WORDS.sub("", query)

    # Remove leading question words that add noise for search engines
    query = re.sub(
        r"^(what is|what are|what's|who is|who are|where is|where are|"
        r"how do i|how can i|how to|how does|why is|why are|why does|"
        r"is there|are there|can i|should i|do i need)\s+",
        "",
        query,
        flags=re.IGNORECASE,
    )

    # Collapse whitespace
    query = re.sub(r"\s+", " ", query).strip()

    # Remove trailing punctuation
    query = query.rstrip("?.!,;:")

    # If the query got too short after cleaning, fall back to original
    if len(query.split()) < 2:
        query = message.strip().rstrip("?.!,;:")

    # Truncate very long queries (search APIs work best with < 200 chars)
    if len(query) > 200:
        query = query[:200].rsplit(" ", 1)[0]

    return query


# ── LLM-based context-aware query reformulation ─────────────────────
# The regex reformulator above works for self-contained queries like
# "What's the weather in NYC?" but fails on anaphoric references like
# "search it", "look that up", "find the size" where the actual topic
# lives in earlier conversation turns.  This function uses a cheap LLM
# call to resolve pronouns and references against recent history.

_REFORMULATE_PROMPT = """You are a search query optimizer. Given a conversation snippet and the user's latest message, produce a single concise web search query that captures what the user actually wants to find.

Rules:
- Output ONLY the search query, nothing else. No quotes, no explanation.
- Resolve all pronouns and references ("it", "that", "the size") using conversation context.
- Keep it under 10 words. Be specific and keyword-rich.
- Include brand names, model numbers, and technical terms when relevant.
- Do NOT include filler words like "please", "can you", "search for".

Conversation (most recent last):
{conversation}

User's latest message: {message}

Search query:"""


async def reformulate_query_with_context(
    message: str,
    recent_history: list,
    llm_provider,
    llm_model: str,
) -> Optional[str]:
    """Use an LLM to build a search query from conversation context.

    Resolves anaphoric references like "search it", "look that up",
    "find the size" by reading recent conversation history and
    extracting the actual topic the user wants searched.

    Args:
        message: The user's current message (e.g. "search it").
        recent_history: Recent messages as dicts with 'role' and 'content'.
                        Should be in reverse-chronological order (newest first).
        llm_provider: An initialized LLM provider instance.
        llm_model: Model name to use (should be a cheap/fast model).

    Returns:
        A concise search query string, or None if the LLM call fails.
    """
    if not llm_provider or not recent_history:
        return None

    try:
        # Build a compact conversation snippet (last 4 turns, newest last)
        turns = []
        for msg in reversed(recent_history[:4]):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            # Truncate long messages to save tokens
            if len(content) > 300:
                content = content[:300] + "..."
            turns.append(f"{role}: {content}")
        conversation = "\n".join(turns)

        prompt = _REFORMULATE_PROMPT.format(
            conversation=conversation,
            message=message,
        )

        response = await llm_provider.generate(
            messages=[{"role": "user", "content": prompt}],
            model=llm_model,
            temperature=0.0,
            max_tokens=50,
        )

        query = response.content.strip().strip('"\'')
        # Sanity check: reject empty or overly long results
        if not query or len(query) > 200 or len(query.split()) < 2:
            logger.warning(f"LLM reformulation produced unusable query: '{query}'")
            return None

        logger.info(f"LLM reformulated search query: '{message}' → '{query}'")
        return query

    except Exception as e:
        logger.warning(f"LLM query reformulation failed: {e}")
        return None
