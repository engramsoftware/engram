"""
Abstract base class for LLM providers.
All providers must implement this interface.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, AsyncGenerator
from pydantic import BaseModel
from dataclasses import dataclass


@dataclass
class StreamChunk:
    """A single chunk from streaming response."""
    content: str
    is_done: bool = False
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class LLMResponse(BaseModel):
    """Complete response from LLM."""
    content: str
    model: str
    provider: str
    usage: Dict[str, int] = {}
    finish_reason: Optional[str] = None


class ModelInfo(BaseModel):
    """Information about an available model."""
    id: str
    name: str
    context_length: Optional[int] = None
    supports_streaming: bool = True
    supports_functions: bool = False
    supports_vision: bool = False


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    Each provider implementation must:
    1. Implement list_models() to auto-detect available models
    2. Implement generate() for non-streaming responses
    3. Implement stream() for SSE streaming responses
    4. Implement test_connection() to verify API connectivity
    """
    
    provider_name: str = "base"
    
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        """
        Initialize provider with credentials.
        
        Args:
            api_key: API key for authentication (if required)
            base_url: Base URL for API requests
        """
        self.api_key = api_key
        self.base_url = base_url
    
    @abstractmethod
    async def list_models(self) -> List[ModelInfo]:
        """
        Auto-detect and list available models.
        
        Returns:
            List of ModelInfo objects for available models
        """
        pass
    
    @abstractmethod
    async def generate(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> LLMResponse:
        """
        Generate a complete response (non-streaming).
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model identifier to use
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens in response
            **kwargs: Provider-specific options
            
        Returns:
            LLMResponse with complete generated text
        """
        pass
    
    @abstractmethod
    async def stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncGenerator[StreamChunk, None]:
        """
        Stream response chunks via SSE.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model identifier to use
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens in response
            **kwargs: Provider-specific options
            
        Yields:
            StreamChunk objects with partial content
        """
        pass
    
    @abstractmethod
    async def test_connection(self) -> bool:
        """
        Test if the provider is reachable and credentials are valid.
        
        Returns:
            True if connection successful, False otherwise
        """
        pass
    
    # ── Approximate token estimation ──────────────────────────────────
    # ~4 chars per token is a safe heuristic across models.  Avoids
    # requiring tiktoken (not always installed) while staying close
    # enough for budget decisions.
    _CHARS_PER_TOKEN = 4

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token count from character length (~4 chars/token)."""
        return len(text) // 4 if text else 0

    @staticmethod
    def _truncate_to_budget(text: str, max_tokens: int) -> str:
        """Truncate text to fit within a token budget, cutting at last newline."""
        max_chars = max_tokens * 4
        if len(text) <= max_chars:
            return text
        # Cut at last newline before the limit to avoid mid-sentence breaks
        truncated = text[:max_chars]
        last_nl = truncated.rfind("\n")
        if last_nl > max_chars // 2:
            truncated = truncated[:last_nl]
        return truncated + "\n[...truncated to fit context budget]"

    def format_messages_with_context(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        search_results: Optional[List[Dict[str, Any]]] = None,
        memories: Optional[List[str]] = None,
        web_search_context: Optional[str] = None,
        # ── New categorized context inputs ──
        auto_memories: Optional[List[str]] = None,
        notes_context: Optional[str] = None,
        rag_context: Optional[str] = None,
        graph_context: Optional[str] = None,
        live_data_context: Optional[str] = None,
        context_budget: int = 8000,
        has_web_search: bool = False,
    ) -> List[Dict[str, str]]:
        """
        Format messages with budget-aware, structurally separated context.

        Assembles the system prompt from categorized retrieval sources,
        respecting a token budget so the persona and conversation history
        are never starved.  Sections are ordered per "Lost in the Middle"
        research: highest-signal context at the top and bottom of the
        system prompt, lower-signal in the middle.

        Args:
            messages: Conversation history messages.
            system_prompt: Base persona / system prompt (never truncated).
            search_results: Hybrid search hits from chat history.
            memories: User's manual memories (already filtered by caller).
            web_search_context: Formatted Brave Search results (if any).
            auto_memories: Autonomous memory strings.
            notes_context: Pre-formatted notes block.
            rag_context: Pre-formatted RAG document chunks.
            graph_context: Pre-formatted knowledge graph context.
            context_budget: Max tokens for all injected context sections
                (excludes persona and conversation history).

        Returns:
            Formatted messages list with system prompt + conversation.
        """
        # ── Prompt caching support ────────────────────────────────
        # Anthropic prompt caching is PREFIX-based: everything before
        # a cache_control marker is cached across requests.
        #
        # To maximize cache hits, we structure the system prompt as:
        #   [STABLE PREFIX]  persona + always-on capability instructions
        #   <!-- CACHE_BREAK -->
        #   [DYNAMIC SUFFIX]  date/time, retrieval context, conditional instructions
        #
        # The Anthropic provider splits on CACHE_BREAK and marks the
        # stable prefix with cache_control.  Other providers ignore it
        # (it's an HTML comment, invisible to the LLM).
        #
        # Cache savings: 90% cost reduction on the stable prefix
        # (typically 1000-2000 tokens of persona + capabilities).
        CACHE_BREAK = "\n<!-- CACHE_BREAK -->\n"

        # ── 1. Build STABLE prefix (persona + always-on capabilities) ──
        # These rarely change between turns, making them ideal for caching.
        stable_parts: List[str] = []
        if system_prompt:
            stable_parts.append(system_prompt)

        # Always-included capability instructions go in the cached prefix
        # because they're identical on every turn.
        stable_cap_parts: List[str] = []
        stable_cap_parts.append(
            "## Your Capabilities\n"
            "You are Engram \u2014 the user's personal AI assistant with "
            "a persistent knowledge base."
        )

        if has_web_search:
            # Brave Search is configured — tell the LLM it CAN search
            # so it doesn't falsely claim "I can't search the web."
            stable_cap_parts.append(
                "\n### Web Search\n"
                "You have web search capability via Brave Search. "
                "Web search is triggered automatically when your system "
                "detects the user wants current information. If the user "
                "explicitly asks you to search, web search WILL run on "
                "their next message. Never tell the user you cannot "
                "search the web — you can."
            )

        # Notes instructions — always included since the user can
        # ask to save a note at any time
        stable_cap_parts.append(
            "\n### Notes System\n"
            "You can create notes by including this marker in your "
            "response (it will be hidden from the user):\n"
            "```\n"
            "[SAVE_NOTE: Title]\n"
            "Content in markdown.\n"
            "[/SAVE_NOTE]\n"
            "```\n"
            "Confirm saves naturally (e.g. \"Done, saved.\"). "
            "Reference any notes shown in context above."
        )

        # Schedule instructions — always included so the user can
        # ask Engram to add events to the shared calendar
        stable_cap_parts.append(
            "\n### Shared Schedule / Calendar\n"
            "You can add events to the shared calendar (visible to all users):\n"
            "```\n"
            "[ADD_SCHEDULE: Event Title | 2026-02-15 14:00]\n"
            "Optional description or notes about the event.\n"
            "[/ADD_SCHEDULE]\n"
            "```\n"
            "The datetime must be ISO format (YYYY-MM-DD HH:MM). "
            "Use the current date/time from the system prompt to calculate relative times "
            "('tomorrow at 3pm' → compute the actual date). "
            "These markers are hidden from the user.\n"
            "Use this when the user asks to 'add to calendar', 'schedule', "
            "'remind me about an event', or mentions appointments, meetings, etc.\n"
            "Confirm naturally (e.g. \"Added to the calendar for Feb 15 at 2pm.\")."
        )

        # Email capabilities - reading AND sending
        stable_cap_parts.append(
            "\n### Email\n"
            "You have FULL email access. You can both READ and SEND emails.\n\n"
            "**Reading email:** When the user asks to check, read, or search "
            "their email, their inbox is automatically searched and the "
            "results are injected into your context below. Look for the "
            "'Relevant Emails' or 'Email Results' section. Summarize what "
            "you find, highlight important messages, and answer questions "
            "about email content. NEVER say you cannot access email. "
            "You CAN and DO have access.\n\n"
            "**Sending email to the user (self):**\n"
            "```\n"
            "[SEND_EMAIL: Subject Line]\n"
            "Email body in plain text.\n"
            "[/SEND_EMAIL]\n"
            "```\n\n"
            "**Sending email to someone else:**\n"
            "```\n"
            "[SEND_EMAIL: Subject Line | recipient@example.com]\n"
            "Email body in plain text.\n"
            "[/SEND_EMAIL]\n"
            "```\n"
            "When the user says 'email John at john@gmail.com' or "
            "'send an email to sarah@company.com', put the recipient "
            "address after a pipe character in the marker.\n\n"
            "**Scheduling email for later:**\n"
            "```\n"
            "[SCHEDULE_EMAIL: Subject Line | 2026-02-08 15:00]\n"
            "Email body in plain text.\n"
            "[/SCHEDULE_EMAIL]\n"
            "```\n"
            "The datetime can be ISO format, relative ('in 2 hours', "
            "'in 30 minutes'), or natural ('tomorrow at 3pm'). "
            "These markers are hidden from the user.\n"
            "Use SEND_EMAIL for immediate delivery. "
            "Use SCHEDULE_EMAIL when the user says 'remind me at/in...' "
            "or wants a future notification.\n"
            "Confirm naturally (e.g. \"Done, I'll email you at 3pm.\" "
            "or \"Sent! Check your inbox.\")."
        )

        # Budget tracking — auto-track expenses from conversation
        stable_cap_parts.append(
            "\n### Budget Tracking\n"
            "You can track the user's expenses. When the user mentions "
            "spending money (e.g. 'I spent $5 on lunch', 'paid $200 for groceries', "
            "'bought a $50 shirt'), ALWAYS log it using this hidden marker:\n"
            "```\n"
            "[ADD_EXPENSE: 5.00 | food]\n"
            "Lunch at cafe\n"
            "[/ADD_EXPENSE]\n"
            "```\n"
            "The format is: [ADD_EXPENSE: amount | category]description[/ADD_EXPENSE]\n"
            "Categories should be lowercase freeform (food, groceries, transport, "
            "entertainment, shopping, bills, health, etc.).\n"
            "The marker is hidden from the user. After logging, confirm naturally "
            "(e.g. \"Got it, tracked $5 for lunch.\").\n"
            "If the user asks about their budget or spending, their recent expenses "
            "will appear in the context below."
        )

        stable_cap_text = "\n".join(stable_cap_parts)
        stable_parts.append(f"\n\n{stable_cap_text}")

        # ── 2. Build DYNAMIC suffix (changes every message) ──────
        dynamic_parts: List[str] = []

        # Inject current local time so the LLM knows "now"
        try:
            from config import get_settings
            from datetime import datetime as _dt, timezone as _tz
            _settings = get_settings()
            if _settings.timezone:
                import zoneinfo
                _local_tz = zoneinfo.ZoneInfo(_settings.timezone)
            else:
                _local_tz = _dt.now().astimezone().tzinfo
            _now = _dt.now(_local_tz)
            _tz_name = _settings.timezone or str(_local_tz)
            _iso = _now.strftime('%Y-%m-%d')
            _time = _now.strftime('%I:%M %p')
            _day = _now.strftime('%A')
            _week = _now.isocalendar()[1]
            dynamic_parts.append(
                f"## Current Date & Time\n"
                f"**Now:** {_day}, {_now.strftime('%B %d, %Y')} at {_time} ({_tz_name})\n"
                f"**ISO date:** {_iso} | **Week:** {_week}\n\n"
                f"Messages in this conversation have [YYYY-MM-DD HH:MM] timestamps. "
                f"Use them to understand when things were said — compare against today's "
                f"date to say 'yesterday', '3 days ago', 'last week', etc. "
                f"Memories and notes also have dates. Always ground your time references "
                f"against the current date above. When the user says 'in 2 minutes', "
                f"calculate from this exact time."
            )
        except Exception:
            pass  # If timezone detection fails, omit rather than crash

        # ── 3. Build context sections in priority order ──────────
        # Per "Lost in the Middle" (Liu et al. 2023) and Anthropic's
        # context engineering guide (2025): put highest-signal context
        # at the TOP (primacy) and BOTTOM (recency) of the system
        # prompt.  Lower-signal goes in the middle.
        context_sections: List[tuple] = []  # (label, content, priority)

        if web_search_context:
            context_sections.append(("web_search", web_search_context, 1))

        if notes_context:
            context_sections.append((
                "notes",
                f"## Reference: User's Notes\n{notes_context}",
                2,
            ))

        if rag_context:
            context_sections.append((
                "documents",
                f"## Reference: Uploaded Documents\n{rag_context}",
                3,
            ))

        # Combine manual + auto memories into one section
        all_memory_lines: List[str] = []
        if memories:
            for m in memories:
                all_memory_lines.append(f"- {m}")
        if auto_memories:
            for m in auto_memories:
                all_memory_lines.append(f"- {m}")
        if all_memory_lines:
            context_sections.append((
                "memories",
                "## User Profile & Knowledge\n"
                "These are facts learned from past conversations. Use them to personalize "
                "your responses, but NEVER tell the user 'you mentioned this before' or "
                "'you asked about this previously' unless the CURRENT conversation history "
                "above explicitly shows it. Memories are background context, not conversation history.\n"
                + "\n".join(all_memory_lines),
                4,
            ))

        if graph_context:
            context_sections.append(("graph", graph_context, 5))

        # Live data from intent-based retrievals (email, schedule, budget)
        # High priority (2) because users expect real-time data answers
        if live_data_context:
            context_sections.append(("live_data", live_data_context, 2))

        if search_results:
            hits = search_results[:10]
            lines = ["## Relevant Past Conversations"]
            lines.append(
                "These are messages from OTHER conversations that may provide useful context. "
                "IMPORTANT: Do NOT tell the user 'you asked this before' or reference these "
                "past conversations directly. The user may not remember them or may be asking "
                "fresh. Use this context silently to give better answers, but respond as if "
                "this is a new question unless the user explicitly says otherwise."
            )
            current_title = None
            for r in hits:
                ts = r.get("timestamp", "unknown date")
                role = r.get("role", "user")
                title = r.get("conversation_title", "")
                content = r.get("content", "")
                # Truncate individual results to keep context manageable
                if len(content) > 500:
                    content = content[:500] + "..."
                # Group by conversation title
                if title and title != current_title:
                    lines.append(f"\n**Conversation: {title}**")
                    current_title = title
                role_label = "User" if role == "user" else "Assistant"
                lines.append(f"  [{ts}] {role_label}: {content}")
            context_sections.append(("history_search", "\n".join(lines), 3))

        # ── 4. Budget-aware assembly of dynamic context ───────────
        # Persona + capabilities are in the stable prefix (free of budget).
        # Only dynamic retrieval context counts against the budget.
        #
        # Web search gets a DEDICATED budget (up to 4000 tokens) that
        # does NOT compete with memories/notes/graph.
        WEB_SEARCH_MAX_BUDGET = 4000
        remaining_budget = context_budget
        injected_labels: List[str] = []

        # Inject web search first with its own dedicated budget
        web_sections = [s for s in context_sections if s[0] == "web_search"]
        other_sections = [s for s in context_sections if s[0] != "web_search"]

        for label, content, _priority in web_sections:
            section_tokens = self._estimate_tokens(content)
            web_budget = min(section_tokens, WEB_SEARCH_MAX_BUDGET)
            if section_tokens <= WEB_SEARCH_MAX_BUDGET:
                dynamic_parts.append(f"\n\n{content}")
                remaining_budget -= section_tokens
                injected_labels.append(label)
            else:
                # Truncate web results to fit dedicated budget
                truncated = self._truncate_to_budget(content, WEB_SEARCH_MAX_BUDGET)
                dynamic_parts.append(f"\n\n{truncated}")
                remaining_budget -= WEB_SEARCH_MAX_BUDGET
                injected_labels.append(f"{label}(truncated)")

        # Inject remaining sections with the leftover budget
        for label, content, _priority in other_sections:
            section_tokens = self._estimate_tokens(content)
            if section_tokens <= remaining_budget:
                dynamic_parts.append(f"\n\n{content}")
                remaining_budget -= section_tokens
                injected_labels.append(label)
            elif remaining_budget > 200:
                # Partial injection — truncate to fit
                truncated = self._truncate_to_budget(content, remaining_budget)
                dynamic_parts.append(f"\n\n{truncated}")
                remaining_budget = 0
                injected_labels.append(f"{label}(truncated)")
                break
            else:
                # Budget exhausted — skip remaining sections
                break

        # ── 4b. Web search citation instructions (dynamic) ────────
        # Only injected when web search results are present in this
        # specific turn — can't be in the cached prefix.
        if "web_search" in injected_labels or "web_search(truncated)" in injected_labels:
            dynamic_parts.append(
                "\n\n## Web Search Citation Instructions\n"
                "The section above contains LIVE web search results from multiple "
                "sources (Brave, DuckDuckGo, Wikipedia). Each source is numbered [1], [2], etc.\n\n"
                "**How to use them:**\n"
                "- **Lead with the answer.** Don't start with 'According to search results...' — "
                "just answer the question directly, then support with evidence.\n"
                "- **Cite with numbers.** Use inline citations like [1], [2] or [1][3] after claims. "
                "Every non-trivial fact must have a citation.\n"
                "- **Synthesize across sources.** Compare and combine information from multiple "
                "results to give a complete answer. Don't just summarize one source.\n"
                "- **Extract specifics.** Pull out exact numbers, names, prices, dates, specs — "
                "not vague summaries. The user wants concrete data.\n"
                "- **Note conflicts.** If sources disagree, say so and explain which seems more reliable.\n"
                "- **Fill gaps.** If the search results don't fully answer the question, say what's "
                "missing and supplement with your own knowledge (clearly marked as such).\n"
                "- **Include source URLs.** At the end of your response, list the most useful sources "
                "as clickable links so the user can read more."
            )

        # ── 5. Assemble final system prompt ───────────────────────
        # Format: [stable prefix] CACHE_BREAK [dynamic suffix]
        # Anthropic provider splits on CACHE_BREAK and marks the
        # stable prefix with cache_control for 90% cost savings.
        # Other providers see it as an invisible HTML comment.
        stable_text = "\n".join(stable_parts) if stable_parts else ""
        dynamic_text = "\n".join(dynamic_parts) if dynamic_parts else ""

        if stable_text and dynamic_text:
            final_system = stable_text + CACHE_BREAK + dynamic_text
        elif stable_text:
            final_system = stable_text
        elif dynamic_text:
            final_system = dynamic_text
        else:
            final_system = None

        formatted: List[Dict[str, str]] = []
        if final_system:
            formatted.append({"role": "system", "content": final_system})

        for msg in messages:
            if msg.get("role") != "system":
                formatted.append(msg)

        return formatted

    @staticmethod
    def inject_images_into_messages(
        messages: List[Dict[str, Any]],
        images: List[Dict[str, str]],
        supports_vision: bool,
        provider_name: str = "openai",
        backend_url: str = "http://localhost:8000",
    ) -> List[Dict[str, Any]]:
        """Inject image attachments into the last user message for the LLM.

        Handles three provider formats:
          - **OpenAI / LM Studio / Ollama**: image_url content blocks with
            base64 data URIs (works locally without public URLs).
          - **Anthropic API**: source blocks with base64 + media_type
            (Anthropic rejects image_url format).
          - **Text-only models**: appends "[User attached image(s)]" note.

        Args:
            messages: Formatted message list (already has system prompt injected).
            images: List of image dicts with 'url', 'filename', 'content_type'.
            supports_vision: Whether the target model accepts images.
            provider_name: LLM provider identifier for format selection.
            backend_url: Base URL for resolving relative image paths.

        Returns:
            Updated messages list.
        """
        if not images:
            return messages

        # Find the last user message
        last_user_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                last_user_idx = i
                break

        if last_user_idx is None:
            return messages

        msg = messages[last_user_idx]
        text_content = msg.get("content", "")

        if not supports_vision:
            img_names = ", ".join(img.get("filename", "image") for img in images)
            messages[last_user_idx] = {
                "role": "user",
                "content": f"{text_content}\n\n[User attached image(s): {img_names}. "
                           f"This model does not support image input.]",
            }
            return messages

        # Read image files and encode as base64 for the API
        import base64
        from pathlib import Path

        # Resolve upload directory from the URL path
        upload_dir = Path(__file__).parent.parent.parent / "data" / "uploads"

        b64_images: List[str] = []  # raw base64 strings for Ollama
        image_blocks: List[Dict[str, Any]] = []  # content blocks for OpenAI/Anthropic

        for img in images:
            url = img.get("url", "")
            content_type = img.get("content_type", "image/jpeg")

            # Read the file from disk and base64 encode
            filename = url.split("/")[-1] if "/" in url else url
            file_path = upload_dir / filename
            if not file_path.exists():
                continue

            b64_data = base64.b64encode(file_path.read_bytes()).decode("utf-8")
            b64_images.append(b64_data)

            if provider_name == "anthropic":
                # Anthropic format: source block with base64 + media_type
                image_blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": content_type,
                        "data": b64_data,
                    },
                })
            else:
                # OpenAI / LM Studio: data URI in image_url block
                image_blocks.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{content_type};base64,{b64_data}",
                    },
                })

        if provider_name == "ollama":
            # Ollama uses a separate "images" array of raw base64 strings
            # on the message object, NOT OpenAI-style content blocks.
            messages[last_user_idx] = {
                "role": "user",
                "content": text_content,
                "images": b64_images,
            }
        else:
            # OpenAI / Anthropic / LM Studio: multimodal content array
            content_parts: List[Dict[str, Any]] = [
                {"type": "text", "text": text_content},
            ]
            content_parts.extend(image_blocks)
            messages[last_user_idx] = {
                "role": "user",
                "content": content_parts,
            }

        return messages
