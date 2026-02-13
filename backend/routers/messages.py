"""
Messages router.
Handles message creation with LLM streaming and search context injection.
"""

import logging
import json
import re
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from bson import ObjectId

from database import get_database
from routers.auth import get_current_user
from models.message import MessageCreate, MessageResponse
from llm.factory import create_provider
from search.hybrid_wrapper import HybridSearchWrapper
from search.search_interface import SearchFilters
from utils.encryption import decrypt_api_key
from memory.memory_store import MemoryStore
from memory.memory_extractor import MemoryExtractor
from memory.conflict_resolver import ConflictResolver
from negative_knowledge.extractor import NegativeKnowledgeExtractor
from negative_knowledge.store import NegativeKnowledgeStore
from pipeline.outlet import process_response
from knowledge_graph.graph_store import get_graph_store
from config import get_settings
from addins.registry import get_registry

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize search
search_engine = HybridSearchWrapper()

# Cache preflight check results per provider so we don't HTTP-check every message.
# Key: "provider:base_url", Value: {"ts": float, "error": Optional[str]}
_preflight_cache: Dict[str, Dict] = {}

# Keep track of background tasks to prevent garbage collection
_background_tasks = set()


async def get_user_llm_settings(user_id: str) -> dict:
    """Fetch user's LLM settings from database."""
    db = get_database()
    settings = await db.llm_settings.find_one({"userId": user_id})
    return settings or {}


async def get_user_persona(user_id: str) -> Optional[str]:
    """Get user's default persona system prompt."""
    db = get_database()
    persona = await db.personas.find_one({
        "userId": user_id,
        "isDefault": True
    })
    return persona.get("systemPrompt") if persona else None


async def get_user_memories(user_id: str) -> List[str]:
    """Get user's enabled manual memories with dates.

    Each memory is returned with its last-updated date so the LLM
    can reason about how recent the information is.
    """
    db = get_database()
    memories = []
    async for mem in db.memories.find({"userId": user_id, "enabled": True}):
        content = mem["content"]
        updated = mem.get("updatedAt") or mem.get("createdAt")
        if updated:
            content = f"({updated.strftime('%Y-%m-%d %H:%M')}) {content}"
        memories.append(content)
    return memories


async def get_relevant_notes(user_id: str, query: str, limit: int = 5) -> List[dict]:
    """Search user's notes for content relevant to the current query.

    Uses MongoDB text search on title + content, then falls back to
    recent pinned notes if text search returns nothing.

    Args:
        user_id: Owner's user ID.
        query: The user's message to match against.
        limit: Max notes to return.

    Returns:
        List of dicts with 'title' and 'content' keys.
    """
    db = get_database()
    notes: List[dict] = []

    # Try text search first (LIKE-based keyword matching)
    try:
        cursor = (
            db.notes.find(
                {"userId": user_id, "isFolder": False, "$text": {"$search": query}},
            )
            .limit(limit)
        )
        async for doc in cursor:
            updated = doc.get("updatedAt") or doc.get("createdAt")
            date_str = updated.strftime("%Y-%m-%d %H:%M") if updated else ""
            notes.append({
                "title": doc["title"],
                "content": doc.get("content", ""),
                "date": date_str,
            })
    except Exception as e:
        logger.debug(f"Notes text search failed: {e}")

    # If text search returned nothing, fall back to pinned + recent notes
    if not notes:
        cursor = (
            db.notes.find({"userId": user_id, "isFolder": False})
            .sort([("isPinned", -1), ("updatedAt", -1)])
            .limit(limit)
        )
        async for doc in cursor:
            updated = doc.get("updatedAt") or doc.get("createdAt")
            date_str = updated.strftime("%Y-%m-%d %H:%M") if updated else ""
            notes.append({
                "title": doc["title"],
                "content": doc.get("content", ""),
                "date": date_str,
            })

    return notes


async def handle_slash_command(
    content: str, user_id: str, conversation_id: str, db
) -> Optional[str]:
    """Parse and execute slash commands typed in chat.

    Supported commands:
        /note save <title> — save the last assistant response as a note
        /note list — list recent notes (titles only)
        /note search <query> — search notes

    Args:
        content: Raw user message text.
        user_id: Current user's ID.
        conversation_id: Active conversation ID.
        db: MongoDB database instance.

    Returns:
        A response string if a command was handled, or None to continue
        normal LLM processing.
    """
    text = content.strip()
    if not text.startswith("/"):
        return None

    parts = text.split(maxsplit=2)
    cmd = parts[0].lower()

    # ── /note ────────────────────────────────────────────────
    if cmd == "/note":
        sub = parts[1].lower() if len(parts) > 1 else "list"

        if sub == "save":
            title = parts[2] if len(parts) > 2 else "Untitled"
            # Grab last assistant message in this conversation
            last_msg = await db.messages.find_one(
                {"conversationId": conversation_id, "role": "assistant"},
                sort=[("timestamp", -1)],
            )
            note_content = last_msg["content"] if last_msg else "(no assistant response yet)"
            await db.notes.insert_one({
                "userId": user_id,
                "title": title,
                "content": note_content,
                "folder": None,
                "parentId": None,
                "tags": ["from-chat"],
                "isFolder": False,
                "isPinned": False,
                "createdAt": datetime.utcnow(),
                "updatedAt": datetime.utcnow(),
                "lastEditedBy": "user",
            })
            return f"Saved note **{title}** with the last assistant response."

        if sub == "list":
            cursor = (
                db.notes.find({"userId": user_id, "isFolder": False})
                .sort([("isPinned", -1), ("updatedAt", -1)])
                .limit(10)
            )
            lines = []
            async for doc in cursor:
                pin = "📌 " if doc.get("isPinned") else ""
                lines.append(f"- {pin}**{doc['title']}**")
            if not lines:
                return "No notes yet. Create one with `/note save <title>`."
            return "**Your recent notes:**\n" + "\n".join(lines)

        if sub == "search" and len(parts) > 2:
            query = parts[2]
            results = await get_relevant_notes(user_id, query, limit=5)
            if not results:
                return f"No notes matching *{query}*."
            lines = [f"- **{r['title']}**: {r['content'][:100]}..." for r in results]
            return f"**Notes matching '{query}':**\n" + "\n".join(lines)

        return "Usage: `/note save <title>`, `/note list`, `/note search <query>`"

    # ── /digest ───────────────────────────────────────────────
    if cmd == "/digest":
        try:
            from notifications.daily_digest import generate_daily_digest
            digest = await generate_daily_digest(user_id=user_id)
            return digest.get("summary", "No digest available.")
        except Exception as e:
            return f"Failed to generate digest: {e}"

    # ── /budget ──────────────────────────────────────────────
    if cmd == "/budget":
        sub = parts[1].lower() if len(parts) > 1 else "summary"

        if sub == "add" and len(parts) > 2:
            # Parse: /budget add $50 groceries lunch at Costco
            raw = parts[2]
            import re as _re
            amt_match = _re.search(r'\$?([\d,]+\.?\d*)', raw)
            if not amt_match:
                return "Usage: `/budget add $50 groceries description`"
            amount = float(amt_match.group(1).replace(",", ""))
            # Rest of the string after the amount
            remainder = raw[amt_match.end():].strip()
            # Category is freeform — first word after amount, rest is description
            tokens = remainder.split(maxsplit=1)
            category = tokens[0].lower() if tokens else "uncategorized"
            description = tokens[1] if len(tokens) > 1 else ""
            await db.expenses.insert_one({
                "userId": user_id,
                "amount": amount,
                "category": category,
                "description": description,
                "date": datetime.utcnow().isoformat(),
                "createdAt": datetime.utcnow().isoformat(),
            })
            return f"✅ Added **${amount:.2f}** ({category}){': ' + description if description else ''}"

        if sub == "summary":
            from datetime import timedelta
            cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
            cursor = db.expenses.find({
                "userId": user_id,
                "date": {"$gte": cutoff},
            })
            by_cat = {}
            total = 0.0
            count = 0
            async for doc in cursor:
                cat = doc.get("category", "other")
                amt = doc.get("amount", 0)
                by_cat[cat] = by_cat.get(cat, 0) + amt
                total += amt
                count += 1
            if count == 0:
                return "No expenses tracked yet. Add one with `/budget add $50 groceries lunch`"
            lines = [f"## 💰 Budget Summary (Last 30 Days)\n"]
            lines.append(f"**Total:** ${total:.2f} across {count} expense(s)\n")
            lines.append("| Category | Spent |")
            lines.append("|----------|------:|")
            for cat, amt in sorted(by_cat.items(), key=lambda x: -x[1]):
                lines.append(f"| {cat.title()} | ${amt:.2f} |")
            return "\n".join(lines)

        return "Usage: `/budget summary`, `/budget add $50 groceries description`"

    # ── /schedule ──────────────────────────────────────────────
    if cmd == "/schedule":
        sub = parts[1].lower() if len(parts) > 1 else "upcoming"

        if sub == "add" and len(parts) > 2:
            # Parse: /schedule add 2026-02-15 14:00 Doctor appointment
            raw = parts[2]
            import re as _re
            # Try to extract datetime from the beginning
            dt_match = _re.match(r'(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})?\s*(.*)', raw)
            if not dt_match:
                return "Usage: `/schedule add 2026-02-15 14:00 Event title`"
            date_part = dt_match.group(1)
            time_part = dt_match.group(2) or "00:00"
            title = dt_match.group(3).strip() or "Untitled event"
            start_time = f"{date_part}T{time_part}"
            await db.schedule_events.insert_one({
                "title": title,
                "startTime": start_time,
                "endTime": None,
                "description": "",
                "location": "",
                "category": "general",
                "recurring": None,
                "allDay": not dt_match.group(2),
                "source": "manual",
                "createdBy": user_id,
                "createdAt": datetime.utcnow().isoformat(),
            })
            return f"📅 Added **{title}** on {date_part} at {time_part}"

        if sub == "upcoming":
            from datetime import timedelta
            now = datetime.utcnow()
            end = (now + timedelta(days=7)).isoformat()
            events = []
            async for doc in db.schedule_events.find({
                "startTime": {"$gte": now.isoformat(), "$lte": end}
            }).sort("startTime", 1).limit(10):
                t = doc.get("title", "Untitled")
                st = doc.get("startTime", "")
                src = doc.get("source", "manual")
                events.append(f"- **{t}** — {st} ({src})")
            if not events:
                return "📅 No upcoming events in the next 7 days."
            return "## 📅 Upcoming Schedule (Next 7 Days)\n\n" + "\n".join(events)

        if sub == "from-email":
            # Import events from Gmail — uses the email reader to find calendar-like emails
            settings = await db.llm_settings.find_one({"userId": user_id})
            if not settings or not settings.get("email", {}).get("enabled"):
                return "📧 Email not configured. Go to **Settings → Email** first."
            email_cfg = settings.get("email", {})
            if not email_cfg.get("username") or not email_cfg.get("password"):
                return "📧 Email credentials not set. Configure in **Settings → Email**."
            try:
                from utils.encryption import decrypt_api_key
                from email_reader import get_email_reader_from_settings
                password = decrypt_api_key(email_cfg["password"])
                reader = get_email_reader_from_settings(email_cfg, password)
                if not reader:
                    return "📧 Could not connect to email server."
                try:
                    # Search for calendar-related emails
                    emails = reader.search(query="calendar OR appointment OR meeting OR event OR reminder OR schedule", count=10)
                    if not emails:
                        return "📧 No calendar-related emails found."
                    lines = ["## 📅 Calendar-related Emails\n",
                             "Tell me which ones to add to the schedule:\n"]
                    for i, em in enumerate(emails, 1):
                        subj = em.get("subject", "(no subject)")
                        frm = em.get("from", "")
                        date = em.get("date", "")
                        lines.append(f"{i}. **{subj}**\n   From: {frm} · {date}")
                    lines.append("\nSay something like: *\"Add #1 and #3 to the calendar\"*")
                    return "\n".join(lines)
                finally:
                    reader.disconnect()
            except Exception as e:
                return f"📧 Email error: {e}"

        return "Usage: `/schedule upcoming`, `/schedule add 2026-02-15 14:00 Title`, `/schedule from-email`"

    # ── /email ───────────────────────────────────────────────
    if cmd == "/email":
        sub = parts[1].lower() if len(parts) > 1 else "recent"
        query = parts[2] if len(parts) > 2 else ""

        # Load email settings
        settings = await db.llm_settings.find_one({"userId": user_id})
        if not settings or not settings.get("email", {}).get("enabled"):
            return "📧 Email not configured. Go to **Settings → Email** and add your email + app password."

        email_cfg = settings.get("email", {})
        if not email_cfg.get("username") or not email_cfg.get("password"):
            return "📧 Email username or app password not set. Configure in **Settings → Email**."

        try:
            from utils.encryption import decrypt_api_key
            from email_reader import get_email_reader_from_settings
            password = decrypt_api_key(email_cfg["password"])
            reader = get_email_reader_from_settings(email_cfg, password)
            if not reader:
                return "📧 Could not connect to email server. Check your app password in Settings."

            try:
                if sub == "search" and query:
                    emails = reader.search(query=query, count=10)
                else:
                    emails = reader.list_recent(count=10)

                if not emails:
                    return "No emails found." if sub == "search" else "No recent emails."

                lines = [f"## 📧 {'Search: ' + query if sub == 'search' else 'Recent Emails'}\n"]
                for em in emails:
                    subj = em.get("subject", "(no subject)")
                    frm = em.get("from", "")
                    date = em.get("date", "")
                    lines.append(f"- **{subj}**\n  From: {frm} · {date}")
                return "\n".join(lines)
            finally:
                reader.disconnect()
        except Exception as e:
            return f"📧 Email error: {e}"

    return None


# Regex to match [SAVE_NOTE: title]content[/SAVE_NOTE] blocks in LLM output
_SAVE_NOTE_PATTERN = re.compile(
    r"\[SAVE_NOTE:\s*(.+?)\]\s*\n(.*?)\n?\[/SAVE_NOTE\]",
    re.DOTALL,
)

# Regex to match [SEND_EMAIL: subject]body[/SEND_EMAIL] blocks in LLM output
_SEND_EMAIL_PATTERN = re.compile(
    r"\[SEND_EMAIL:\s*(.+?)\]\s*\n(.*?)\n?\[/SEND_EMAIL\]",
    re.DOTALL,
)

# Regex to match [SCHEDULE_EMAIL: subject | datetime]body[/SCHEDULE_EMAIL]
# The datetime part is flexible — Engram can write "2026-02-08 15:00",
# "tomorrow at 3pm", "in 2 hours", etc.  We parse it with dateutil.
_SCHEDULE_EMAIL_PATTERN = re.compile(
    r"\[SCHEDULE_EMAIL:\s*(.+?)\s*\|\s*(.+?)\]\s*\n(.*?)\n?\[/SCHEDULE_EMAIL\]",
    re.DOTALL,
)

# Regex to match [ADD_EXPENSE: amount | category]description[/ADD_EXPENSE]
# The LLM uses this to track expenses from natural language like "I spent $5 on lunch".
# Format: [ADD_EXPENSE: 5.00 | food]Lunch at cafe[/ADD_EXPENSE]
_ADD_EXPENSE_PATTERN = re.compile(
    r"\[ADD_EXPENSE:\s*\$?([\d,]+\.?\d*)\s*\|\s*(.+?)\]\s*\n?(.*?)\n?\[/ADD_EXPENSE\]",
    re.DOTALL,
)

# Regex to match [ADD_SCHEDULE: title | datetime]description[/ADD_SCHEDULE]
# The LLM uses this to add events to the shared calendar.
# Format: [ADD_SCHEDULE: Doctor appointment | 2026-02-15 14:00]Annual checkup[/ADD_SCHEDULE]
# Optional fields after description: location, category, end_time separated by pipes.
_ADD_SCHEDULE_PATTERN = re.compile(
    r"\[ADD_SCHEDULE:\s*(.+?)\s*\|\s*(.+?)\]\s*\n?(.*?)\n?\[/ADD_SCHEDULE\]",
    re.DOTALL,
)

# Regex to match [SEARCH_EMAIL: query]...[/SEARCH_EMAIL] blocks in LLM output.
# The LLM uses this to search the user's email when asked conversationally
# (e.g. "search my email for the Amazon receipt").
_SEARCH_EMAIL_PATTERN = re.compile(
    r"\[SEARCH_EMAIL:\s*(.+?)\]\s*\n?(.*?)\n?\[/SEARCH_EMAIL\]",
    re.DOTALL,
)


def _get_local_now() -> datetime:
    """Get the current time in the user's configured timezone.

    Falls back to OS-detected local time if TIMEZONE is not set in .env.

    Returns:
        Timezone-aware datetime in the user's local timezone.
    """
    try:
        from config import get_settings
        settings = get_settings()
        if settings.timezone:
            import zoneinfo
            local_tz = zoneinfo.ZoneInfo(settings.timezone)
        else:
            local_tz = datetime.now().astimezone().tzinfo
        return datetime.now(local_tz)
    except Exception:
        return datetime.now().astimezone()


def _parse_scheduled_time(time_str: str) -> Optional[datetime]:
    """Parse a flexible datetime string from the LLM into a local datetime.

    Handles ISO formats, natural language like 'tomorrow at 3pm',
    and relative times like 'in 2 hours'.  Uses the user's configured
    timezone (TIMEZONE in .env) so scheduled times are correct.

    Args:
        time_str: The datetime string from the LLM marker.

    Returns:
        A datetime object in the user's local timezone, or None if parsing fails.
    """
    import re as _re
    time_str = time_str.strip()

    # Handle relative times: "in X minutes/hours/days"
    relative_match = _re.match(
        r"in\s+(\d+)\s+(minute|minutes|min|mins|hour|hours|hr|hrs|day|days)",
        time_str,
        _re.IGNORECASE,
    )
    if relative_match:
        amount = int(relative_match.group(1))
        unit = relative_match.group(2).lower()
        from datetime import timedelta
        now = _get_local_now()
        if unit.startswith("min"):
            return now + timedelta(minutes=amount)
        elif unit.startswith("h"):
            return now + timedelta(hours=amount)
        elif unit.startswith("d"):
            return now + timedelta(days=amount)

    # Try dateutil for everything else (ISO, natural language, etc.)
    try:
        from dateutil import parser as dateutil_parser
        parsed = dateutil_parser.parse(time_str, fuzzy=True)
        # If no timezone info, assume it's in the user's local timezone
        if parsed.tzinfo is None:
            local_now = _get_local_now()
            parsed = parsed.replace(tzinfo=local_now.tzinfo)
        return parsed
    except Exception:
        pass

    # Last resort: try basic ISO format
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(time_str, fmt)
            local_now = _get_local_now()
            return parsed.replace(tzinfo=local_now.tzinfo)
        except ValueError:
            continue

    return None


async def extract_and_search_emails(
    response_text: str, user_id: str, db,
) -> Tuple[str, List[str]]:
    """Parse [SEARCH_EMAIL] markers from LLM output, execute email search, inject results.

    The LLM outputs [SEARCH_EMAIL: query][/SEARCH_EMAIL] when the user asks
    to search their email. We execute the search and replace the marker with
    formatted results so the user sees the emails inline.

    Args:
        response_text: Raw LLM response that may contain markers.
        user_id: User ID for email settings lookup.
        db: Database instance.

    Returns:
        Tuple of (cleaned_text_with_results, list_of_search_queries).
    """
    matches = list(_SEARCH_EMAIL_PATTERN.finditer(response_text))
    if not matches:
        return response_text, []

    queries = []
    for match in matches:
        query = match.group(1).strip()
        if not query:
            continue
        queries.append(query)

        # Load email settings
        settings = await db.llm_settings.find_one({"userId": user_id})
        if not settings or not settings.get("email", {}).get("enabled"):
            replacement = f"\n\n📧 **Email not configured.** Go to Settings → Email to connect your account.\n\n"
            response_text = response_text.replace(match.group(0), replacement)
            continue

        email_cfg = settings.get("email", {})
        if not email_cfg.get("username") or not email_cfg.get("password"):
            replacement = f"\n\n📧 **Email credentials not set.** Configure in Settings → Email.\n\n"
            response_text = response_text.replace(match.group(0), replacement)
            continue

        try:
            from utils.encryption import decrypt_api_key
            from email_reader import get_email_reader_from_settings
            password = decrypt_api_key(email_cfg["password"])
            reader = get_email_reader_from_settings(email_cfg, password)
            if not reader:
                replacement = f"\n\n📧 Could not connect to email server.\n\n"
                response_text = response_text.replace(match.group(0), replacement)
                continue

            try:
                emails = reader.search(query=query, count=10)
                if not emails:
                    replacement = f"\n\n📧 No emails found matching \"{query}\".\n\n"
                else:
                    lines = [f"\n\n📧 **Email results for \"{query}\":**\n"]
                    for i, em in enumerate(emails, 1):
                        subj = em.get("subject", "(no subject)")
                        frm = em.get("from", "")
                        date = em.get("date", "")
                        body_preview = em.get("body", "")[:150]
                        lines.append(f"**{i}. {subj}**")
                        lines.append(f"   From: {frm} · {date}")
                        if body_preview:
                            lines.append(f"   {body_preview}...")
                        lines.append("")
                    replacement = "\n".join(lines) + "\n"
                response_text = response_text.replace(match.group(0), replacement)
                logger.info(f"Email search for '{query}' returned {len(emails)} results")
            finally:
                reader.disconnect()
        except Exception as e:
            logger.warning(f"Email search failed for '{query}': {e}")
            replacement = f"\n\n📧 Email search error: {e}\n\n"
            response_text = response_text.replace(match.group(0), replacement)

    return response_text, queries


async def extract_and_save_expenses(
    response_text: str, user_id: str, db,
) -> Tuple[str, int]:
    """Parse [ADD_EXPENSE] markers from LLM output and save to budget.

    Format: [ADD_EXPENSE: 5.00 | food]Lunch at cafe[/ADD_EXPENSE]

    The LLM generates these when the user mentions spending money in
    natural conversation (e.g. "I spent $5 on lunch today").

    Args:
        response_text: Raw LLM response that may contain markers.
        user_id: User ID of the owner.
        db: Database instance.

    Returns:
        Tuple of (cleaned_text, number_of_expenses_added).
    """
    matches = list(_ADD_EXPENSE_PATTERN.finditer(response_text))
    if not matches:
        return response_text, 0

    added = 0
    for match in matches:
        amount_str = match.group(1).strip().replace(",", "")
        category = match.group(2).strip().lower()
        description = match.group(3).strip()

        try:
            amount = float(amount_str)
        except ValueError:
            logger.warning(f"Could not parse expense amount: '{amount_str}'")
            continue

        if amount <= 0:
            continue

        doc = {
            "userId": user_id,
            "amount": amount,
            "category": category,
            "description": description,
            "date": datetime.utcnow().isoformat(),
            "store": None,
            "createdAt": datetime.utcnow().isoformat(),
        }
        await db.expenses.insert_one(doc)
        added += 1
        logger.info(f"LLM tracked expense: ${amount:.2f} ({category}) for user {user_id}")

    # Strip markers from response
    cleaned = _ADD_EXPENSE_PATTERN.sub("", response_text).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned, added


async def extract_and_save_schedule_events(
    response_text: str, user_id: str, db,
) -> Tuple[str, int]:
    """Parse [ADD_SCHEDULE] markers from LLM output and save to schedule.

    Format: [ADD_SCHEDULE: Title | 2026-02-15 14:00]Optional description[/ADD_SCHEDULE]

    Args:
        response_text: Raw LLM response that may contain markers.
        user_id: User ID of the creator.
        db: Database instance.

    Returns:
        Tuple of (cleaned_text, number_of_events_added).
    """
    matches = list(_ADD_SCHEDULE_PATTERN.finditer(response_text))
    if not matches:
        return response_text, 0

    added = 0
    for match in matches:
        title = match.group(1).strip()
        time_str = match.group(2).strip()
        description = match.group(3).strip()

        if not title or not time_str:
            continue

        # Parse the datetime
        parsed_time = _parse_scheduled_time(time_str)
        if not parsed_time:
            # Try basic ISO formats as fallback
            for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
                try:
                    parsed_time = datetime.strptime(time_str, fmt)
                    break
                except ValueError:
                    continue

        if not parsed_time:
            logger.warning(f"Could not parse schedule time: '{time_str}' for '{title}'")
            continue

        # Save to schedule_events collection (shared between all users)
        doc = {
            "title": title,
            "startTime": parsed_time.isoformat(),
            "endTime": None,
            "description": description,
            "location": "",
            "category": "general",
            "recurring": None,
            "allDay": False,
            "source": "llm",
            "createdBy": user_id,
            "createdAt": datetime.utcnow().isoformat(),
        }
        await db.schedule_events.insert_one(doc)
        added += 1
        logger.info(f"LLM added schedule event: '{title}' at {parsed_time.isoformat()}")

    # Strip markers from response
    cleaned = _ADD_SCHEDULE_PATTERN.sub("", response_text).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned, added


async def extract_and_send_emails(
    response_text: str, user_id: str, db,
    conversation_id: Optional[str] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Parse [SEND_EMAIL] and [SCHEDULE_EMAIL] markers, send/schedule, strip.

    [SEND_EMAIL: Subject]body[/SEND_EMAIL] — sends immediately and logs.
    [SCHEDULE_EMAIL: Subject | datetime]body[/SCHEDULE_EMAIL] — schedules.

    Both types are saved to the notifications collection for history.

    Args:
        response_text: Raw LLM response that may contain markers.
        user_id: Owner's user ID.
        db: MongoDB database instance.
        conversation_id: Conversation that triggered this (for linking).

    Returns:
        Tuple of (cleaned_text, list_of_notification_summaries).
        Each summary dict has: subject, status, scheduled_at (ISO str or None).
    """
    now = _get_local_now()
    notif_summaries: List[Dict[str, Any]] = []

    # ── Handle scheduled emails first ──
    schedule_matches = list(_SCHEDULE_EMAIL_PATTERN.finditer(response_text))
    for match in schedule_matches:
        subject = match.group(1).strip()
        time_str = match.group(2).strip()
        body = match.group(3).strip()

        if not subject or not body:
            continue

        scheduled_at = _parse_scheduled_time(time_str)
        if not scheduled_at:
            logger.warning(f"Could not parse scheduled time '{time_str}', sending immediately")
            scheduled_at = now  # fallback: send now

        # Make both timezone-aware for comparison
        # If scheduled_at is naive, attach local timezone
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=now.tzinfo)

        # If scheduled time is in the past, treat as immediate (pending for scheduler)
        is_future = scheduled_at > now
        if not is_future:
            scheduled_at = now

        await db.notifications.insert_one({
            "userId": user_id,
            "subject": subject,
            "body": body,
            "status": "pending",
            "scheduledAt": scheduled_at,
            "sentAt": None,
            "createdAt": now,
            "conversationId": conversation_id,
            "error": None,
            "read": False,
        })
        notif_summaries.append({
            "subject": subject,
            "status": "scheduled" if is_future else "sent",
            "scheduled_at": scheduled_at.isoformat() if is_future else None,
        })
        logger.info(
            f"Engram scheduled email: '{subject}' at {scheduled_at.isoformat()} "
            f"for user {user_id}"
        )

    # Strip schedule markers
    response_text = _SCHEDULE_EMAIL_PATTERN.sub("", response_text)

    # ── Handle immediate emails ──
    send_matches = list(_SEND_EMAIL_PATTERN.finditer(response_text))
    if send_matches:
        # Load user's email settings once (not per-match)
        settings = await db.llm_settings.find_one({"userId": user_id})
        email_cfg = settings.get("email", {}) if settings else {}
        can_send = (
            email_cfg.get("enabled")
            and email_cfg.get("username")
            and email_cfg.get("password")
        )

        # Create email service once outside the loop to reuse SMTP connection
        service = None
        recipient = None
        if can_send:
            try:
                from notifications.email_service import EmailService, build_notification_html
                from utils.encryption import decrypt_api_key

                smtp_password = decrypt_api_key(email_cfg["password"])
                service = EmailService(
                    smtp_host=email_cfg.get("smtpHost", "smtp.gmail.com"),
                    smtp_port=email_cfg.get("smtpPort", 587),
                    username=email_cfg["username"],
                    password=smtp_password,
                    from_name=email_cfg.get("fromName", "Engram"),
                )
                recipient = email_cfg.get("recipient") or email_cfg["username"]
            except Exception as e:
                logger.error(f"Failed to initialize email service: {e}")
                can_send = False

        for match in send_matches:
            subject = match.group(1).strip()
            body = match.group(2).strip()

            if not subject or not body:
                continue

            # Always log to notifications collection
            notif_doc = {
                "userId": user_id,
                "subject": subject,
                "body": body,
                "status": "pending",
                "scheduledAt": now,  # immediate = scheduled for now
                "sentAt": None,
                "createdAt": now,
                "conversationId": conversation_id,
                "error": None,
                "read": False,
            }

            if can_send and service:
                try:
                    from notifications.email_service import build_notification_html

                    html_body = build_notification_html(
                        title=subject,
                        body=f"<p>{'</p><p>'.join(body.split(chr(10) + chr(10)))}</p>",
                    )

                    success = await service.send(
                        to=recipient,
                        subject=f"Engram — {subject}",
                        body=body,
                        html_body=html_body,
                    )

                    if success:
                        notif_doc["status"] = "sent"
                        notif_doc["sentAt"] = datetime.utcnow()
                        logger.info(f"Engram sent email: '{subject}' to {recipient}")
                    else:
                        notif_doc["status"] = "failed"
                        notif_doc["error"] = "SMTP send failed"
                except Exception as e:
                    notif_doc["status"] = "failed"
                    notif_doc["error"] = str(e)
                    logger.error(f"Failed to send email '{subject}': {e}")
            else:
                notif_doc["status"] = "failed"
                notif_doc["error"] = "Email not configured or disabled"
                logger.warning(f"Email markers found but email not configured for user {user_id}")

            await db.notifications.insert_one(notif_doc)
            notif_summaries.append({
                "subject": subject,
                "status": notif_doc["status"],
                "scheduled_at": None,
            })

    # Strip send markers
    response_text = _SEND_EMAIL_PATTERN.sub("", response_text).strip()
    response_text = re.sub(r"\n{3,}", "\n\n", response_text)

    return response_text, notif_summaries


async def extract_and_save_notes(
    response_text: str, user_id: str, db
) -> Tuple[str, int]:
    """Parse [SAVE_NOTE] markers from LLM output, save notes, strip markers.

    The LLM is instructed to wrap note content in markers like:
        [SAVE_NOTE: My Title]
        Note content here...
        [/SAVE_NOTE]

    This function extracts all such blocks, saves each as a note in MongoDB
    (tagged 'from-assistant'), and returns the cleaned response with markers
    removed.

    Args:
        response_text: Raw LLM response that may contain markers.
        user_id: Owner's user ID.
        db: MongoDB database instance.

    Returns:
        Tuple of (cleaned_text, notes_saved_count).
    """
    matches = list(_SAVE_NOTE_PATTERN.finditer(response_text))
    if not matches:
        return response_text, 0

    saved = 0
    for match in matches:
        title = match.group(1).strip()
        content = match.group(2).strip()

        if not title or not content:
            continue

        # Upsert: if a note with the same title exists, update it
        existing = await db.notes.find_one({
            "userId": user_id,
            "title": title,
            "isFolder": False,
        })

        now = datetime.utcnow()
        if existing:
            await db.notes.update_one(
                {"_id": existing["_id"]},
                {"$set": {
                    "content": content,
                    "updatedAt": now,
                    "lastEditedBy": "assistant",
                }},
            )
        else:
            await db.notes.insert_one({
                "userId": user_id,
                "title": title,
                "content": content,
                "folder": None,
                "parentId": None,
                "tags": ["from-assistant"],
                "isFolder": False,
                "isPinned": False,
                "createdAt": now,
                "updatedAt": now,
                "lastEditedBy": "assistant",
            })
        saved += 1
        logger.info(f"Engram saved note: '{title}' for user {user_id}")

    # Strip the marker blocks from the response so the user sees clean text
    cleaned = _SAVE_NOTE_PATTERN.sub("", response_text).strip()
    # Clean up any double blank lines left behind
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned, saved


def _build_autonomous_stores(db):
    """
    Create MemoryStore / NegativeKnowledgeStore wired to MongoDB + ChromaDB.
    Stores are optional; they gracefully no-op if ChromaDB isn't available.
    """
    memory_store = MemoryStore(mongo_db=db)
    negative_store = NegativeKnowledgeStore(mongo_db=db)
    return memory_store, negative_store


@router.post("")
async def send_message(
    data: MessageCreate,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """
    Send a message and stream LLM response.
    
    Pipeline:
    1. Save user message to database
    2. Search chat history for relevant context
    3. Build system prompt with persona + memories + search results
    4. Stream LLM response via SSE
    5. Save assistant response to database
    """
    db = get_database()
    user_id = current_user["id"]
    logger.info(f"=== SEND_MESSAGE called: user={user_id}, conv={data.conversation_id}, content={data.content[:50]}... ===")
    
    # Verify conversation exists and belongs to user
    conv = await db.conversations.find_one({
        "_id": ObjectId(data.conversation_id),
        "userId": user_id
    })
    if not conv:
        logger.error(f"Conversation {data.conversation_id} not found for user {user_id}")
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Save user message (skip if regenerating - the original user message already exists)
    if not data.is_regeneration:
        user_msg = {
            "conversationId": data.conversation_id,
            "userId": user_id,
            "role": "user",
            "content": data.content,
            "images": [img.model_dump() for img in data.images] if data.images else [],
            "timestamp": datetime.utcnow(),
            "metadata": {}
        }
        result = await db.messages.insert_one(user_msg)

        # Index user message in vector store for hybrid search
        try:
            await search_engine.index_message(
                message_id=str(result.inserted_id),
                conversation_id=data.conversation_id,
                user_id=user_id,
                content=data.content,
                role="user",
                timestamp=datetime.utcnow(),
            )
        except Exception as idx_err:
            logger.warning(f"User message indexing failed: {idx_err}")

    # Update conversation timestamp
    await db.conversations.update_one(
        {"_id": ObjectId(data.conversation_id)},
        {"$set": {"updatedAt": datetime.utcnow()}}
    )

    # ── Slash command handling (before any LLM work) ──────
    slash_response = await handle_slash_command(
        data.content, user_id, data.conversation_id, db
    )
    if slash_response is not None:
        # Return the response directly without calling the LLM
        assistant_msg = {
            "conversationId": data.conversation_id,
            "userId": user_id,
            "role": "assistant",
            "content": slash_response,
            "timestamp": datetime.utcnow(),
            "metadata": {"provider": "system", "model": "slash-command"},
        }
        await db.messages.insert_one(assistant_msg)

        async def _slash_stream():
            yield f"data: {json.dumps({'content': slash_response})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"

        return StreamingResponse(
            _slash_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    # Get LLM settings
    llm_settings = await get_user_llm_settings(user_id)

    # ── Optimization settings ──────────────────────────────────
    # response_validation: skip the post-stream hallucination check
    # history_limit: 0 = full history (default), N = last N messages only
    _opt = llm_settings.get("optimization", {})
    _response_validation_enabled = _opt.get("responseValidation", True)
    _history_limit = _opt.get("historyLimit", 0)

    provider_name = conv.get("modelProvider") or llm_settings.get("defaultProvider")
    model_name = conv.get("modelName") or llm_settings.get("defaultModel")
    
    # If no provider set, try to find an enabled one
    if not provider_name:
        providers = llm_settings.get("providers", {})
        for pname, pconfig in providers.items():
            if pconfig.get("enabled"):
                provider_name = pname
                break
        if not provider_name:
            provider_name = "lmstudio"  # Default fallback
    
    # Get provider config
    providers = llm_settings.get("providers", {})
    provider_config = providers.get(provider_name, {})
    
    # If no model specified, try to get first available model for this provider
    if not model_name:
        available_models = provider_config.get("availableModels", [])
        if available_models:
            model_name = available_models[0]
    
    # Hardcoded fallback defaults per provider (when DB has no models cached)
    if not model_name:
        _FALLBACK_MODELS = {
            "openai": "gpt-4o",
            "anthropic": "claude-sonnet-4-20250514",
            "lmstudio": "default",
            "ollama": "llama3",
        }
        model_name = _FALLBACK_MODELS.get(provider_name, "default")
    
    logger.info(f"Using provider: {provider_name}, model: {model_name}")
    
    # Decrypt API key if stored
    api_key = None
    if provider_config.get("apiKey"):
        try:
            api_key = decrypt_api_key(provider_config["apiKey"])
        except Exception as e:
            logger.warning(f"Failed to decrypt API key for {provider_name}: {e}")
    
    # Create LLM provider
    provider = create_provider(
        provider_name,
        api_key=api_key,
        base_url=provider_config.get("baseUrl"),
    )
    
    if not provider:
        raise HTTPException(status_code=400, detail=f"Provider {provider_name} not available")
    
    # Pre-flight check moved into the parallel gather below so it
    # doesn't block retrieval.  Only API-key checks (instant) run here.
    _API_KEY_PROVIDERS = {"openai", "anthropic"}
    _LOCAL_PROVIDERS = {"lmstudio", "ollama"}

    if provider_name in _API_KEY_PROVIDERS and not api_key:
        _preflight_error = (
            f"⚠️ **{provider_name.title()} is selected but no API key is configured.**\n\n"
            f"Go to **Settings → LLM Providers → {provider_name.title()}** and add your API key, "
            f"or switch to a different provider."
        )
        async def _alert_generator():
            yield f"data: {json.dumps({'content': _preflight_error})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_alert_generator(), media_type="text/event-stream")

    logger.info(f"Provider class: {type(provider).__name__}, has stream: {hasattr(type(provider), 'stream')}")
    
    # ── Parallel context retrieval ──────────────────────────────
    # All independent retrieval sources run concurrently to minimize
    # time-to-first-token.  Sources that depend on others (Brave search,
    # continuity detection) run in a second phase.
    import asyncio as _aio

    async def _r_search():
        """Hybrid BM25+vector search across all conversations."""
        try:
            return await search_engine.search(
                query=data.content, user_id=user_id,
                filters=SearchFilters(conversation_id=None), top_k=10,
            )
        except Exception as e:
            logger.debug(f"Hybrid search failed: {e}")
            return []

    async def _r_persona():
        try:
            return await get_user_persona(user_id)
        except Exception:
            return ""

    async def _r_memories():
        try:
            return await get_user_memories(user_id)
        except Exception:
            return []

    async def _r_auto_memories():
        """Autonomous memories from ChromaDB with timestamps."""
        try:
            ms, _ = _build_autonomous_stores(db)
            if ms.is_available:
                hits = ms.search(data.content, user_id=user_id, limit=5, min_confidence=0.3)
                result = []
                for m in hits:
                    mtype = getattr(m, 'memory_type', 'fact')
                    # Include when the memory was formed so the LLM can reason about recency
                    date_str = ""
                    if hasattr(m, 'created_at') and m.created_at:
                        date_str = f" ({m.created_at.strftime('%Y-%m-%d %H:%M')})"
                    result.append(f"[auto:{mtype}{date_str}] {m.content}")
                return result
        except Exception as e:
            logger.debug(f"Autonomous memory retrieval skipped: {e}")
        return []

    async def _r_notes():
        try:
            return await get_relevant_notes(user_id, data.content, limit=3)
        except Exception as e:
            logger.debug(f"Notes retrieval skipped: {e}")
            return []

    async def _r_rag():
        try:
            from rag.document_processor import search_documents
            return search_documents(data.content, user_id, top_k=3)
        except Exception as e:
            logger.debug(f"RAG retrieval skipped: {e}")
            return []

    async def _r_graph():
        try:
            _s = get_settings()
            if _s.neo4j_uri and _s.neo4j_password:
                gs = get_graph_store(
                    uri=_s.neo4j_uri, username=_s.neo4j_username,
                    password=_s.neo4j_password, database=_s.neo4j_database,
                )
                if gs and gs.is_available:
                    from fastapi.concurrency import run_in_threadpool
                    results = await run_in_threadpool(gs.search_by_query, data.content, user_id, 5)
                    if results:
                        return gs.format_context_for_prompt(results)
        except Exception as e:
            logger.debug(f"Knowledge graph retrieval skipped: {e}")
        return ""

    async def _r_history():
        """Fetch conversation messages with timestamps for time grounding.

        Each message gets a [YYYY-MM-DD HH:MM] prefix in the user's
        local timezone so the LLM can reason about when things were
        said — crucial for 'yesterday', 'last week', 'earlier today'.
        Timestamps are stored as UTC in the DB and converted here.

        When _history_limit > 0, only the last N messages are sent.
        Hybrid search already injects relevant older messages from
        ALL conversations, so limiting history avoids paying for
        redundant context tokens.
        """
        # Resolve user's timezone for timestamp conversion
        try:
            import zoneinfo
            _tz_name = get_settings().timezone or "America/Los_Angeles"
            _local_tz = zoneinfo.ZoneInfo(_tz_name)
        except Exception:
            _local_tz = None

        # Use history_limit if set (e.g. 3), otherwise default 25
        _msg_limit = _history_limit if _history_limit > 0 else 25

        raw = []
        async for msg in db.messages.find(
            {"conversationId": data.conversation_id}
        ).sort("timestamp", -1).limit(_msg_limit):
            content = msg["content"]
            extracted = msg.get("metadata", {}).get("extracted_file_text")
            if extracted:
                content += f"\n\n{extracted}"
            # Prepend timestamp converted to user's local timezone
            ts = msg.get("timestamp")
            if ts:
                if _local_tz and hasattr(ts, 'replace'):
                    # DB stores naive UTC datetimes — attach UTC then convert
                    from datetime import timezone as _utc_tz
                    ts_utc = ts.replace(tzinfo=_utc_tz.utc)
                    ts_local = ts_utc.astimezone(_local_tz)
                    ts_str = ts_local.strftime("%Y-%m-%d %H:%M")
                else:
                    ts_str = ts.strftime("%Y-%m-%d %H:%M")
                content = f"[{ts_str}] {content}"
            raw.append({"role": msg["role"], "content": content})
        return list(reversed(raw))

    # ── Intent-based retrievals (email, schedule, budget) ────────
    # These detect user intent via keywords and fetch data PRE-LLM
    # so the LLM can answer with real data (not post-stream markers).

    _EMAIL_INTENT = re.compile(
        r"\b(email|inbox|mail|gmail|e-mail|check.{0,5}mail|search.{0,5}mail|"
        r"search.{0,5}email|find.{0,5}email|any.{0,5}emails?|read.{0,5}email|"
        r"my.{0,5}emails?|from.{0,20}@)\b",
        re.IGNORECASE,
    )
    _SCHEDULE_INTENT = re.compile(
        r"\b(calendar|schedule|appointment|meeting|event|plan|plans|"
        r"upcoming|what.{0,5}(do i|am i|are we|is).{0,10}(today|tomorrow|this week|next)|"
        r"when.{0,5}(is|are|my)|free.{0,5}time|busy|booked|agenda)\b",
        re.IGNORECASE,
    )
    _BUDGET_INTENT = re.compile(
        r"\b(budget|spending|expense|spent|cost|money|how much|"
        r"finances?|financial|receipt|purchase|bought|paid)\b",
        re.IGNORECASE,
    )

    async def _r_email_context() -> str:
        """Search user's email if the message mentions email/inbox/mail."""
        if not _EMAIL_INTENT.search(data.content):
            return ""
        try:
            settings = await db.llm_settings.find_one({"userId": user_id})
            if not settings or not settings.get("email", {}).get("enabled"):
                return ""
            email_cfg = settings.get("email", {})
            if not email_cfg.get("username") or not email_cfg.get("password"):
                return ""
            from utils.encryption import decrypt_api_key
            from email_reader import get_email_reader_from_settings
            password = decrypt_api_key(email_cfg["password"])
            reader = get_email_reader_from_settings(email_cfg, password)
            if not reader:
                return ""
            try:
                # Extract search terms from user message (strip email-related words)
                query = re.sub(
                    r"\b(search|check|find|look|read|my|the|any|for|in|from|"
                    r"email|emails|inbox|mail|gmail|e-mail|please|can you)\b",
                    "", data.content, flags=re.IGNORECASE
                ).strip()
                if len(query) < 2:
                    # No specific query — show recent emails
                    emails = reader.list_recent(count=8)
                else:
                    emails = reader.search(query=query, count=8)
                if not emails:
                    return "\n## Email Results\nNo emails found.\n"
                lines = ["\n## Email Results\n"]
                for i, em in enumerate(emails, 1):
                    subj = em.get("subject", "(no subject)")
                    frm = em.get("from", "")
                    date = em.get("date", "")
                    body = em.get("body", "")[:200]
                    lines.append(f"**{i}. {subj}**")
                    lines.append(f"   From: {frm} | Date: {date}")
                    if body:
                        lines.append(f"   Preview: {body}...")
                    lines.append("")
                logger.info(f"Email context: {len(emails)} emails fetched for query '{query[:50]}'")
                return "\n".join(lines)
            finally:
                reader.disconnect()
        except Exception as e:
            logger.debug(f"Email context retrieval failed: {e}")
            return ""

    async def _r_schedule_context() -> str:
        """Fetch upcoming schedule events if the message mentions calendar/schedule."""
        if not _SCHEDULE_INTENT.search(data.content):
            return ""
        try:
            from datetime import timedelta
            now = datetime.utcnow()
            end = (now + timedelta(days=7)).isoformat()
            events = []
            async for doc in db.schedule_events.find({
                "startTime": {"$gte": now.isoformat(), "$lte": end}
            }).sort("startTime", 1).limit(10):
                t = doc.get("title", "Untitled")
                st = doc.get("startTime", "")
                loc = doc.get("location", "")
                desc = doc.get("description", "")
                cat = doc.get("category", "")
                line = f"- **{t}** — {st}"
                if loc:
                    line += f" at {loc}"
                if cat and cat != "general":
                    line += f" [{cat}]"
                if desc:
                    line += f"\n  {desc[:100]}"
                events.append(line)
            if not events:
                return "\n## Upcoming Schedule\nNo events in the next 7 days.\n"
            logger.info(f"Schedule context: {len(events)} upcoming events")
            return "\n## Upcoming Schedule (Next 7 Days)\n" + "\n".join(events) + "\n"
        except Exception as e:
            logger.debug(f"Schedule context retrieval failed: {e}")
            return ""

    async def _r_budget_context() -> str:
        """Fetch recent spending if the message mentions budget/money/expenses."""
        if not _BUDGET_INTENT.search(data.content):
            return ""
        try:
            from datetime import timedelta
            cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
            total = 0.0
            count = 0
            by_cat: Dict[str, float] = {}
            recent_items = []
            async for doc in db.expenses.find({
                "userId": user_id, "date": {"$gte": cutoff}
            }).sort("date", -1).limit(20):
                amt = doc.get("amount", 0)
                cat = doc.get("category", "uncategorized")
                desc = doc.get("description", "")
                date = doc.get("date", "")
                total += amt
                count += 1
                by_cat[cat] = by_cat.get(cat, 0) + amt
                if len(recent_items) < 5:
                    recent_items.append(f"- ${amt:.2f} {cat}: {desc} ({date[:10]})")
            if count == 0:
                return "\n## Budget Summary\nNo expenses recorded in the last 30 days.\n"
            lines = [f"\n## Budget Summary (Last 30 Days)\n"]
            lines.append(f"**Total:** ${total:.2f} across {count} expenses\n")
            lines.append("| Category | Amount |")
            lines.append("|----------|-------:|")
            for cat, amt in sorted(by_cat.items(), key=lambda x: -x[1]):
                lines.append(f"| {cat.title()} | ${amt:.2f} |")
            if recent_items:
                lines.append("\n**Recent:**")
                lines.extend(recent_items)
            logger.info(f"Budget context: ${total:.2f} across {count} expenses")
            return "\n".join(lines) + "\n"
        except Exception as e:
            logger.debug(f"Budget context retrieval failed: {e}")
            return ""

    async def _r_preflight() -> Optional[str]:
        """Check local provider reachability (cached 60s).

        Runs in parallel with retrieval so it doesn't add latency.
        Returns error string if provider is unreachable, None if OK.
        """
        if provider_name not in _LOCAL_PROVIDERS:
            return None
        import httpx
        _base = provider_config.get("baseUrl") or (
            "http://host.docker.internal:1234" if provider_name == "lmstudio"
            else "http://host.docker.internal:11434"
        )
        _cache_key = f"{provider_name}:{_base}"
        _now_ts = datetime.utcnow().timestamp()
        _cached = _preflight_cache.get(_cache_key)
        if _cached and (_now_ts - _cached["ts"]) < 60:
            return _cached.get("error")
        try:
            async with httpx.AsyncClient(timeout=2.0) as _client:
                _resp = await _client.get(
                    f"{_base}/v1/models" if provider_name == "lmstudio"
                    else f"{_base}/api/tags"
                )
                if _resp.status_code >= 400:
                    raise httpx.HTTPStatusError("bad", request=_resp.request, response=_resp)
            _preflight_cache[_cache_key] = {"ts": _now_ts, "error": None}
            return None
        except Exception:
            _server_name = "LM Studio" if provider_name == "lmstudio" else "Ollama"
            err = (
                f"⚠️ **{_server_name} is selected but not reachable at `{_base}`.**\n\n"
                f"Make sure {_server_name} is running and its API server is started. "
                f"If running in Docker, the URL should be "
                f"`http://host.docker.internal:{_base.split(':')[-1]}`."
            )
            _preflight_cache[_cache_key] = {"ts": _now_ts, "error": err}
            return err

    # Phase 1: fire ALL independent retrievals + preflight at once
    # The preflight check runs in parallel so it adds ZERO latency.
    # Intent-based retrievals (email, schedule, budget) also run in
    # parallel — they detect keywords and only fetch if relevant.
    (
        search_results, persona, memories, auto_memories_list,
        relevant_notes, rag_chunks, graph_context, history,
        email_context, schedule_context, budget_context,
        _preflight_err,
    ) = await _aio.gather(
        _r_search(), _r_persona(), _r_memories(), _r_auto_memories(),
        _r_notes(), _r_rag(), _r_graph(), _r_history(),
        _r_email_context(), _r_schedule_context(), _r_budget_context(),
        _r_preflight(),
    )

    # Check preflight result after gather completes
    if _preflight_err:
        logger.warning(f"Provider pre-flight failed: {provider_name}")
        async def _alert_generator():
            yield f"data: {json.dumps({'content': _preflight_err})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_alert_generator(), media_type="text/event-stream")

    logger.info(
        f"Parallel retrieval done: search={len(search_results)} "
        f"memories={len(auto_memories_list)} notes={len(relevant_notes or [])} "
        f"graph={'yes' if graph_context else 'no'}"
    )

    # Format notes context (with dates for time grounding)
    notes_context = ""
    if relevant_notes:
        parts = []
        for n in relevant_notes:
            date_prefix = f"(Updated: {n['date']}) " if n.get('date') else ""
            parts.append(f"### {date_prefix}{n['title']}\n{n['content'][:500]}")
        notes_context = "\n".join(parts)

    # Format RAG context
    rag_context = ""
    if rag_chunks:
        rag_context = "\n\n".join(
            f"[From: {c['filename']}]\n{c['content']}" for c in rag_chunks
        )

    # Phase 2: Brave search (needs history for LLM reformulation)
    brave_web_context = ""
    brave_raw_results = []
    brave_is_configured = False
    try:
        brave_config = llm_settings.get("braveSearch", {})
        if brave_config.get("enabled") and brave_config.get("apiKey"):
            brave_is_configured = True
            from search.web_search_gate import (
                should_web_search, reformulate_search_query,
                reformulate_query_with_context, scrub_pii,
            )

            # Reuse the last 6 messages from history (already fetched)
            recent_history = history[-6:] if len(history) > 6 else history

            do_search, gate_score, gate_reason = should_web_search(
                data.content, conversation_history=recent_history,
            )

            if do_search:
                search_query = await reformulate_query_with_context(
                    message=data.content,
                    recent_history=recent_history,
                    llm_provider=provider,
                    llm_model=model_name,
                )
                if not search_query:
                    search_query = reformulate_search_query(data.content)

                context_names: list = []
                try:
                    user_doc = await db.users.find_one({"_id": ObjectId(user_id)})
                    if user_doc and user_doc.get("name"):
                        full_name = user_doc["name"]
                        context_names.append(full_name)
                        context_names.extend(full_name.split())
                except Exception:
                    pass
                search_query = scrub_pii(search_query, context_names=context_names)

                from search.brave_search import BraveSearchClient, format_brave_results_for_context
                brave_key = decrypt_api_key(brave_config["apiKey"])
                brave_client = BraveSearchClient(api_key=brave_key)
                brave_results = await brave_client.search(query=search_query, count=8)
                if brave_results:
                    brave_web_context = format_brave_results_for_context(brave_results)
                    brave_raw_results = brave_results
                    logger.info(
                        f"Web Search: gate=YES score={gate_score:.2f} "
                        f"query='{search_query}' → {len(brave_results)} results"
                    )
            else:
                logger.debug(
                    f"Brave Search: gate=NO score={gate_score:.2f} "
                    f"reason={gate_reason}"
                )
    except Exception as e:
        logger.debug(f"Brave Search retrieval skipped: {e}")

    # Phase 2: Continuity detection (reuses search_results from Phase 1)
    continuity_summary = ""
    try:
        msg_count = await db.messages.count_documents({
            "conversationId": data.conversation_id, "userId": user_id,
        })
        if msg_count <= 1 and not data.is_regeneration:
            # Reuse Phase 1 search results instead of a second search call
            related = [
                r for r in search_results
                if (r.conversation_id or "") != data.conversation_id
            ]
            if related:
                top_conv_id = related[0].conversation_id or ""
                if top_conv_id:
                    prev_conv = await db.conversations.find_one(
                        {"_id": ObjectId(top_conv_id), "userId": user_id}
                    )
                    if prev_conv:
                        prev_title = prev_conv.get("title", "an earlier conversation")
                        snippets = [
                            r.content[:150]
                            for r in related[:3]
                            if (r.conversation_id or "") == top_conv_id
                        ]
                        snippet_text = "; ".join(s for s in snippets if s)
                        if snippet_text:
                            continuity_summary = (
                                f"💡 **Looks like you've discussed this before** "
                                f"in *\"{prev_title}\"*:\n"
                                f"> {snippet_text[:300]}\n\n---\n\n"
                            )
    except Exception as e:
        logger.debug(f"Conversation continuity detection skipped: {e}")
    
    # Format messages with categorized context injection
    # Each source is passed separately for structural separation,
    # priority ordering, and token budget management.
    # Enrich search results with conversation titles so the LLM knows
    # which conversation each result came from
    enriched_search_results = []
    conv_title_cache: Dict[str, str] = {}
    for r in search_results:
        conv_id = r.conversation_id or ""
        if conv_id and conv_id not in conv_title_cache:
            conv_doc = await db.conversations.find_one(
                {"_id": ObjectId(conv_id)}, {"title": 1}
            ) if conv_id else None
            conv_title_cache[conv_id] = conv_doc.get("title", "Untitled") if conv_doc else "Untitled"
        title = conv_title_cache.get(conv_id, "")
        enriched_search_results.append({
            "content": r.content,
            "timestamp": r.timestamp.isoformat(),
            "role": r.role,
            "conversation_title": title,
        })

    # Combine intent-based live data contexts (email, schedule, budget)
    _live_parts = [c for c in (email_context, schedule_context, budget_context) if c]
    _live_data = "\n".join(_live_parts) if _live_parts else None

    formatted_messages = provider.format_messages_with_context(
        messages=history,
        system_prompt=persona,
        search_results=enriched_search_results,
        memories=memories,
        web_search_context=brave_web_context or None,
        auto_memories=auto_memories_list or None,
        notes_context=notes_context or None,
        rag_context=rag_context or None,
        graph_context=graph_context or None,
        live_data_context=_live_data,
        context_budget=8000,
        has_web_search=brave_is_configured,
    )

    # ── Addin interceptors: before_llm ─────────────────────────
    # Let registered interceptors (e.g. Skill Voyager) modify
    # messages before they go to the LLM. Skill Voyager uses this
    # to classify the query and inject a skill strategy.
    try:
        _addin_registry = get_registry()
        _interceptor_context = {
            "user_id": user_id,
            "conversation_id": data.conversation_id,
            "provider": provider_name,
            "model": model_name,
        }
        formatted_messages = await _addin_registry.run_interceptors_before(
            formatted_messages, _interceptor_context
        )
    except Exception as _int_err:
        logger.warning(f"Addin interceptors (before_llm) failed: {_int_err}")

    # Separate image attachments from document attachments
    if data.images:
        image_attachments = []
        doc_attachments = []
        for img in data.images:
            ct = img.content_type or ""
            if ct.startswith("image/"):
                image_attachments.append(img)
            else:
                doc_attachments.append(img)

        # Extract text from non-image file attachments (PDF, DOCX, TXT, etc.)
        if doc_attachments:
            from pathlib import Path
            upload_dir = Path(__file__).parent.parent.parent / "data" / "uploads"
            file_texts = []
            for att in doc_attachments:
                url = att.url or ""
                disk_name = url.split("/")[-1] if "/" in url else url
                file_path = upload_dir / disk_name
                if not file_path.exists():
                    continue
                try:
                    from rag.document_processor import parse_file
                    file_bytes = file_path.read_bytes()
                    text = parse_file(att.filename or disk_name, file_bytes)
                    # Truncate to avoid blowing up context
                    if len(text) > 4000:
                        text = text[:4000] + "\n\n[Content truncated — file too long]"
                    file_texts.append(f"📎 **Attached file: {att.filename}**\n\n{text}")
                    logger.info(f"Extracted text from attachment: {att.filename} ({len(text)} chars)")
                except Exception as e:
                    file_texts.append(f"📎 **Attached file: {att.filename}** (could not extract text: {e})")
                    logger.warning(f"Failed to extract text from {att.filename}: {e}")

            # Inject extracted file text into the last user message
            if file_texts:
                file_context = "\n\n---\n\n".join(file_texts)
                for i in range(len(formatted_messages) - 1, -1, -1):
                    if formatted_messages[i].get("role") == "user":
                        formatted_messages[i]["content"] += f"\n\n{file_context}"
                        break

                # Persist extracted file text as memory so the LLM can
                # recall file contents in future conversations
                try:
                    from memory.memory_store import MemoryStore, Memory
                    file_memory_store = MemoryStore(mongo_db=db)
                    if file_memory_store.is_available:
                        for att, ft in zip(doc_attachments, file_texts):
                            # Only store if we actually got text (not error messages)
                            if "could not extract text" in ft:
                                continue
                            memory_content = (
                                f"User uploaded file: {att.filename}\n\n"
                                f"{ft}"
                            )
                            # Cap at 8000 chars for memory storage
                            if len(memory_content) > 8000:
                                memory_content = memory_content[:8000] + "\n\n[Truncated for storage]"
                            file_memory = Memory(
                                content=memory_content,
                                memory_type="fact",
                                user_id=user_id,
                                source_conversation_id=data.conversation_id,
                                confidence=0.95,
                            )
                            await file_memory_store.add(file_memory)
                            logger.info(f"Stored file content as memory: {att.filename}")
                except Exception as mem_err:
                    logger.warning(f"Failed to store file content as memory: {mem_err}")

                # Also save extracted text in the user message metadata
                # so conversation history includes the file content
                try:
                    await db.messages.find_one_and_update(
                        {
                            "conversationId": data.conversation_id,
                            "userId": user_id,
                            "role": "user",
                        },
                        {"$set": {"metadata.extracted_file_text": file_context}},
                        sort=[("timestamp", -1)],
                    )
                except Exception as meta_err:
                    logger.debug(f"Failed to update message metadata with file text: {meta_err}")

        # Inject images into the last user message if present
        if image_attachments:
            model_supports_vision = False
            try:
                available_models = await provider.list_models()
                for m in available_models:
                    if m.id == model_name:
                        model_supports_vision = m.supports_vision
                        break
            except Exception:
                pass  # If we can't check, default to text fallback

            from llm.base import LLMProvider
            formatted_messages = LLMProvider.inject_images_into_messages(
                messages=formatted_messages,
                images=[img.model_dump() for img in image_attachments],
                supports_vision=model_supports_vision,
                provider_name=provider_name,
            )
            logger.info(
                f"Images injected: {len(image_attachments)} image(s), "
                f"vision={'yes' if model_supports_vision else 'no'}"
            )

    # ── Disconnect-safe streaming ──────────────────────────────────
    # Problem: when the client disconnects mid-stream, Starlette
    # cancels the generator.  Everything after the yield (saving the
    # message, running the outlet pipeline) never executes, leaving
    # a corrupt half-message in the conversation.
    #
    # Solution: decouple LLM consumption from SSE delivery using an
    # asyncio.Queue.  A background task consumes the full LLM stream
    # and always saves the result, regardless of whether the client
    # is still connected.  The SSE generator just reads from the
    # queue and yields to the client — if it gets cancelled, the
    # background task keeps running.

    stream_queue: asyncio.Queue = asyncio.Queue()

    async def _consume_llm_stream():
        """Consume the full LLM stream, save to DB, and run outlet.

        Runs as a background task so client disconnect cannot cancel it.
        Pushes SSE-formatted strings into stream_queue for the generator.
        """
        full_response = ""
        try:
            # Stream conversation continuity banner if this topic was discussed before
            if continuity_summary:
                await stream_queue.put(
                    f"data: {json.dumps({'content': continuity_summary})}\n\n"
                )

            # Send context transparency metadata so frontend can show
            # what was retrieved and why in a collapsible panel
            context_meta = {}
            if auto_memories_list:
                context_meta["memories"] = auto_memories_list[:5]
            if notes_context:
                context_meta["notes"] = len(relevant_notes) if relevant_notes else 0
            if graph_context:
                context_meta["graph"] = graph_context[:500]
            if brave_web_context:
                context_meta["web_search"] = True
            if continuity_summary:
                context_meta["continuity"] = True
            if enriched_search_results:
                context_meta["search_results"] = len(enriched_search_results)
            if email_context:
                context_meta["email"] = True
            if schedule_context:
                context_meta["schedule"] = True
            if budget_context:
                context_meta["budget"] = True
            if context_meta:
                await stream_queue.put(
                    f"data: {json.dumps({'context_metadata': context_meta})}\n\n"
                )

            # Send web search sources
            if brave_raw_results:
                await stream_queue.put(
                    f"data: {json.dumps({'web_sources': brave_raw_results})}\n\n"
                )

            chunk_count = 0
            async for chunk in provider.stream(
                messages=formatted_messages,
                model=model_name,
                temperature=0.7
            ):
                chunk_count += 1
                if chunk.content:
                    full_response += chunk.content
                    await stream_queue.put(
                        f"data: {json.dumps({'content': chunk.content})}\n\n"
                    )
                if chunk.is_done:
                    break
            logger.info(f"Stream finished: {chunk_count} chunks, {len(full_response)} chars")

        except Exception as e:
            error_msg = str(e) or f"{type(e).__name__}: Unknown error"
            logger.error(f"Stream error: {error_msg}", exc_info=True)
            await stream_queue.put(
                f"data: {json.dumps({'error': error_msg})}\n\n"
            )
            # Signal end even on error so the generator doesn't hang
            await stream_queue.put(None)
            return

        # ── Addin interceptors: after_llm ──────────────────────
        # Let interceptors (e.g. Skill Voyager) evaluate the response,
        # update skill confidence, and extract new skills.
        try:
            _addin_registry = get_registry()
            _interceptor_context = {
                "user_id": user_id,
                "conversation_id": data.conversation_id,
                "message_id": "",
                "provider": provider_name,
                "model": model_name,
            }
            full_response = await _addin_registry.run_interceptors_after(
                full_response, _interceptor_context
            )
        except Exception as _int_err:
            logger.warning(f"Addin interceptors (after_llm) failed: {_int_err}")

        # ── Post-stream: save message + run outlet (always runs) ──
        try:
            # Config integrity check on outbound response
            try:
                from search.config_validator import check_output_integrity
                full_response = check_output_integrity(
                    full_response, context="llm_stream_response"
                )
            except SystemExit:
                raise
            except Exception:
                pass

            # Self-reflective validation: check response against retrieved context
            # Uses a cheap LLM call to catch hallucinations before the user sees them.
            # Skipped when the user disables it in Settings → Optimization.
            if _response_validation_enabled:
                try:
                    from pipeline.response_validator import validate_response, build_correction_note
                    # Build combined context string from all retrieval sources
                    _ctx_parts = []
                    if auto_memories_list:
                        _ctx_parts.append("Memories: " + "; ".join(auto_memories_list[:5]))
                    if notes_context:
                        _ctx_parts.append("Notes: " + notes_context[:1000])
                    if graph_context:
                        _ctx_parts.append("Graph: " + graph_context[:1000])
                    if brave_web_context:
                        _ctx_parts.append("Web: " + brave_web_context[:1000])
                    _combined_ctx = "\n".join(_ctx_parts)

                    if _combined_ctx:
                        validation = await validate_response(
                            question=data.content,
                            response=full_response,
                            context=_combined_ctx,
                            llm_provider=provider,
                            model=model_name,
                            api_key=api_key,
                            base_url=base_url,
                        )
                        correction_note = build_correction_note(validation)
                        if correction_note:
                            full_response += correction_note
                            # Stream the correction to the frontend
                            await stream_queue.put(
                                f"data: {json.dumps({'content': correction_note})}\n\n"
                            )
                            logger.info(
                                f"Response validation: {len(validation['issues'])} issue(s) found, "
                                f"correction appended"
                            )
                except Exception as val_err:
                    logger.debug(f"Response validation skipped: {val_err}")
            else:
                logger.debug("Response validation disabled by user setting")

            # Security: block email/note auto-actions when web search was used.
            # An attacker could embed [SEND_EMAIL] markers in a web page to
            # hijack the email pipeline via indirect prompt injection.
            web_search_active = bool(brave_web_context)

            if web_search_active:
                # Strip any action markers from the response before processing.
                # The LLM should not be generating these when web content was
                # injected, but defense-in-depth: strip them anyway.
                import re as _re
                _marker_count = 0
                for _pat in (
                    _SEND_EMAIL_PATTERN,
                    _SCHEDULE_EMAIL_PATTERN,
                    _SAVE_NOTE_PATTERN,
                    _ADD_SCHEDULE_PATTERN,
                    _ADD_EXPENSE_PATTERN,
                    _SEARCH_EMAIL_PATTERN,
                ):
                    _matches = _pat.findall(full_response)
                    if _matches:
                        _marker_count += len(_matches)
                        full_response = _pat.sub("", full_response)

                if _marker_count > 0:
                    logger.warning(
                        f"SECURITY: Stripped {_marker_count} action marker(s) from "
                        f"web-search-influenced response (potential injection attack)"
                    )

                # Skip note/email extraction entirely when web search was used
                cleaned_response = full_response
                notes_saved = 0
                notif_summaries = []
            else:
                cleaned_response, notes_saved = await extract_and_save_notes(
                    full_response, user_id, db
                )
                if notes_saved > 0:
                    logger.info(f"Engram auto-saved {notes_saved} note(s) for user {user_id}")

                # Extract schedule events from [ADD_SCHEDULE] markers
                cleaned_response, schedule_added = await extract_and_save_schedule_events(
                    cleaned_response, user_id, db
                )
                if schedule_added > 0:
                    logger.info(f"Engram added {schedule_added} schedule event(s) for user {user_id}")

                # Extract expenses from [ADD_EXPENSE] markers
                cleaned_response, expenses_added = await extract_and_save_expenses(
                    cleaned_response, user_id, db
                )
                if expenses_added > 0:
                    logger.info(f"Engram tracked {expenses_added} expense(s) for user {user_id}")

                # Extract and send any email notifications
                cleaned_response, notif_summaries = await extract_and_send_emails(
                    cleaned_response, user_id, db,
                    conversation_id=data.conversation_id,
                )
            if notif_summaries:
                logger.info(f"Engram processed {len(notif_summaries)} notification(s) for user {user_id}")
                # Send notification confirmations to the frontend via SSE
                await stream_queue.put(
                    f"data: {json.dumps({'notifications': notif_summaries})}\n\n"
                )

            assistant_msg = {
                "conversationId": data.conversation_id,
                "userId": user_id,
                "role": "assistant",
                "content": cleaned_response,
                "timestamp": datetime.utcnow(),
                "web_sources": brave_raw_results if brave_raw_results else [],
                "metadata": {
                    "provider": provider_name,
                    "model": model_name,
                    "notes_saved": notes_saved,
                    "emails_sent": len(notif_summaries),
                }
            }
            asst_result = await db.messages.insert_one(assistant_msg)
            logger.info(f"Assistant message saved for conversation {data.conversation_id}")

            # Index assistant message in vector store for hybrid search
            try:
                await search_engine.index_message(
                    message_id=str(asst_result.inserted_id),
                    conversation_id=data.conversation_id,
                    user_id=user_id,
                    content=cleaned_response,
                    role="assistant",
                    timestamp=datetime.utcnow(),
                )
            except Exception as idx_err:
                logger.warning(f"Assistant message indexing failed: {idx_err}")

            # Kick off memory formation in the background
            async def _run_outlet():
                logger.info(f"Outlet pipeline starting for user {user_id}")
                try:
                    memory_store, negative_store = _build_autonomous_stores(db)
                    # Use the active chat provider for memory extraction
                    # but pick the cheapest model to keep costs low
                    _CHEAP_MODELS = {
                        "anthropic": "claude-haiku-4-5-20251001",
                        "openai": "gpt-4o-mini",
                    }
                    provider_for_extraction = provider_name or "lmstudio"
                    extractor_model = _CHEAP_MODELS.get(provider_name, model_name)

                    # Pass the decrypted API key so extractors don't rely on .env.
                    # Only pass base_url for local providers (lmstudio/ollama) where
                    # it's meaningful; API-key providers use their SDK defaults.
                    ext_api_key = api_key
                    _LOCAL_PROVIDERS = {"lmstudio", "ollama"}
                    ext_base_url = provider_config.get("baseUrl") if provider_for_extraction in _LOCAL_PROVIDERS else None
                    memory_extractor = MemoryExtractor(
                        provider_name=provider_for_extraction, model=extractor_model,
                        api_key=ext_api_key, base_url=ext_base_url,
                    )
                    conflict_resolver = ConflictResolver(
                        provider_name=provider_for_extraction, model=extractor_model,
                        api_key=ext_api_key, base_url=ext_base_url,
                    )
                    negative_extractor = NegativeKnowledgeExtractor(
                        provider_name=provider_for_extraction, model=extractor_model,
                        api_key=ext_api_key, base_url=ext_base_url,
                    )

                    # Set up knowledge graph store (Neo4j)
                    graph_store = None
                    try:
                        settings = get_settings()
                        if settings.neo4j_uri and settings.neo4j_password:
                            graph_store = get_graph_store(
                                uri=settings.neo4j_uri,
                                username=settings.neo4j_username,
                                password=settings.neo4j_password,
                                database=settings.neo4j_database
                            )
                            logger.info(f"Knowledge graph: store={graph_store.is_available if graph_store else False}")
                        else:
                            logger.debug("Neo4j not configured, graph extraction skipped")
                    except Exception as e:
                        logger.warning(f"Knowledge graph not available: {e}")

                    # Build a lightweight LLM provider for entity extraction
                    # (reuses the same cheap model used for memory extraction)
                    from llm.factory import create_provider
                    _extraction_provider = create_provider(
                        provider_for_extraction,
                        api_key=ext_api_key,
                        base_url=ext_base_url,
                    )

                    result = await process_response(
                        user_query=data.content,
                        assistant_response=full_response,
                        user_id=user_id,
                        conversation_id=data.conversation_id,
                        memory_extractor=memory_extractor,
                        conflict_resolver=conflict_resolver,
                        memory_store=memory_store,
                        negative_extractor=negative_extractor,
                        negative_store=negative_store,
                        graph_store=graph_store,
                        llm_provider=_extraction_provider,
                        llm_model=extractor_model,
                    )
                    logger.info(f"Outlet completed: {result}")
                except Exception as e:
                    logger.error(f"Outlet pipeline failed: {e}", exc_info=True)

            task = asyncio.create_task(_run_outlet())
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)

        except Exception as e:
            logger.error(f"Post-stream save failed: {e}", exc_info=True)

        # Signal done + end-of-stream to the generator
        await stream_queue.put(f"data: {json.dumps({'done': True})}\n\n")
        await stream_queue.put(None)

    # Start the LLM consumer as a background task (survives client disconnect)
    consumer_task = asyncio.create_task(_consume_llm_stream())
    _background_tasks.add(consumer_task)
    consumer_task.add_done_callback(_background_tasks.discard)

    async def generate_stream() -> dict:
        """SSE generator — reads from queue, yields to client.

        If the client disconnects, this generator gets cancelled but
        the _consume_llm_stream task keeps running and saves the result.
        """
        try:
            while True:
                item = await stream_queue.get()
                if item is None:
                    break
                yield item
        except asyncio.CancelledError:
            # Client disconnected — LLM consumer task keeps running
            logger.info(
                f"Client disconnected mid-stream for conversation "
                f"{data.conversation_id} — LLM processing continues"
            )

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )


@router.get("/{conversation_id}", response_model=List[MessageResponse])
async def get_messages(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
    limit: int = Query(100, ge=1, le=500)
) -> dict:
    """Get messages for a conversation."""
    db = get_database()
    
    # Verify conversation ownership
    conv = await db.conversations.find_one({
        "_id": ObjectId(conversation_id),
        "userId": current_user["id"]
    })
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    messages = []
    async for msg in db.messages.find(
        {"conversationId": conversation_id}
    ).sort("timestamp", 1).limit(limit):
        messages.append(MessageResponse(
            id=str(msg["_id"]),
            conversation_id=msg["conversationId"],
            role=msg["role"],
            content=msg["content"],
            images=msg.get("images", []),
            web_sources=msg.get("web_sources", []),
            timestamp=msg["timestamp"],
            metadata=msg.get("metadata", {})
        ))
    
    return messages


@router.post("/regenerate")
async def regenerate_response(
    conversation_id: str,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Regenerate the last assistant response."""
    db = get_database()
    user_id = current_user["id"]
    
    # Verify conversation ownership before doing anything
    conv = await db.conversations.find_one({
        "_id": ObjectId(conversation_id),
        "userId": user_id
    })
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Get last assistant message
    last_msg = await db.messages.find_one(
        {"conversationId": conversation_id, "role": "assistant"},
        sort=[("timestamp", -1)]
    )
    
    if last_msg:
        # Notify Skill Voyager of the regeneration (negative feedback)
        try:
            _reg = get_registry()
            for _interceptor in _reg._interceptors:
                if hasattr(_interceptor, 'correction_learner') and _interceptor.correction_learner:
                    from addins.plugins.skill_voyager.correction_learner import CorrectionEvent
                    _skill = getattr(_interceptor, '_last_skill_applied', None)
                    _interceptor.correction_learner.record_correction(
                        CorrectionEvent(
                            correction_type="regenerate",
                            conversation_id=conversation_id,
                            message_id=str(last_msg.get("_id", "")),
                            original_response=last_msg.get("content", "")[:500],
                            corrected_text="",
                            skill_name=_skill.name if _skill else "",
                            skill_id=_skill.id if _skill else "",
                            query_type="",
                        ),
                        skill_store=getattr(_interceptor, 'skill_store', None),
                    )
                    break
        except Exception as _ce:
            logger.debug(f"Correction feedback on regenerate skipped: {_ce}")

        # Delete it
        await db.messages.delete_one({"_id": last_msg["_id"]})
    
    # Get last user message to regenerate from
    last_user = await db.messages.find_one(
        {"conversationId": conversation_id, "role": "user"},
        sort=[("timestamp", -1)]
    )
    
    if not last_user:
        raise HTTPException(status_code=400, detail="No user message to regenerate from")
    
    # Trigger new generation - use is_regeneration flag to skip duplicate user message
    return await send_message(
        MessageCreate(
            conversation_id=conversation_id,
            content=last_user["content"],
            is_regeneration=True
        ),
        current_user
    )
