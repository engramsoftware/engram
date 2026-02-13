"""
Daily digest generator — summarizes yesterday's conversations + pending items.

Runs once daily via the notification scheduler. Generates a concise summary
of what was discussed, decisions made, and any pending reminders. Delivered
as a notification (email or in-app).

Can also be triggered manually via the /digest slash command.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Maximum conversations to summarize per digest (cost control)
MAX_CONVERSATIONS = 10

# Maximum messages to scan per conversation
MAX_MESSAGES_PER_CONV = 30


async def generate_daily_digest(
    user_id: str,
    llm_provider: Any = None,
    model: Optional[str] = None,
    lookback_hours: int = 24,
) -> Dict[str, Any]:
    """
    Generate a daily digest summarizing recent conversations.

    Scans conversations from the last `lookback_hours`, pulls key messages,
    and uses an LLM to produce a concise summary with action items.

    Args:
        user_id: User to generate digest for.
        llm_provider: LLM provider for summarization (optional — raw digest if None).
        model: Model to use for summarization.
        lookback_hours: How far back to look (default 24h).

    Returns:
        Dict with: summary (str), conversations (list), pending_notifications (list),
        memory_count (int), generated_at (str).
    """
    from database import get_database

    db = get_database()
    cutoff = datetime.utcnow() - timedelta(hours=lookback_hours)

    # Find conversations updated in the lookback window
    cursor = db.conversations.find({
        "userId": user_id,
        "updatedAt": {"$gte": cutoff.isoformat()},
    }).sort("updatedAt", -1).limit(MAX_CONVERSATIONS)

    conv_summaries = []
    total_messages = 0

    async for conv in cursor:
        conv_id = str(conv["_id"])
        title = conv.get("title", "Untitled")

        # Get messages for this conversation in the lookback window
        msg_cursor = db.messages.find({
            "conversationId": conv_id,
            "userId": user_id,
            "timestamp": {"$gte": cutoff.isoformat()},
        }).sort("timestamp", -1).limit(MAX_MESSAGES_PER_CONV)

        messages = []
        async for msg in msg_cursor:
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")[:200],
            })

        if not messages:
            continue

        messages.reverse()  # Chronological order
        total_messages += len(messages)

        conv_summaries.append({
            "title": title,
            "message_count": len(messages),
            "messages": messages,
        })

    # Get pending notifications
    pending_notifs = []
    notif_cursor = db.notifications.find({
        "userId": user_id,
        "status": "pending",
    }).limit(5)
    async for notif in notif_cursor:
        pending_notifs.append({
            "subject": notif.get("subject", ""),
            "scheduled_at": str(notif.get("scheduledAt", "")),
        })

    # Get memory count for the period
    memory_count = 0
    try:
        memory_count = await db.autonomous_memories.count_documents({
            "userId": user_id,
            "createdAt": {"$gte": cutoff.isoformat()},
        })
    except Exception:
        pass

    # Build the digest
    if not conv_summaries:
        return {
            "summary": "No conversations in the last 24 hours. Take a break! 🧘",
            "conversations": [],
            "pending_notifications": pending_notifs,
            "memory_count": 0,
            "total_messages": 0,
            "generated_at": datetime.utcnow().isoformat(),
        }

    # If we have an LLM provider, generate a smart summary
    if llm_provider and model:
        try:
            summary = await _llm_summarize(
                conv_summaries, pending_notifs, memory_count,
                llm_provider, model,
            )
        except Exception as e:
            logger.warning(f"LLM digest summarization failed: {e}")
            summary = _build_raw_summary(conv_summaries, pending_notifs, memory_count)
    else:
        summary = _build_raw_summary(conv_summaries, pending_notifs, memory_count)

    return {
        "summary": summary,
        "conversations": [
            {"title": c["title"], "message_count": c["message_count"]}
            for c in conv_summaries
        ],
        "pending_notifications": pending_notifs,
        "memory_count": memory_count,
        "total_messages": total_messages,
        "generated_at": datetime.utcnow().isoformat(),
    }


async def _llm_summarize(
    conv_summaries: List[Dict],
    pending_notifs: List[Dict],
    memory_count: int,
    llm_provider: Any,
    model: str,
) -> str:
    """Use an LLM to generate a concise daily digest summary.

    Args:
        conv_summaries: List of conversation dicts with titles and messages.
        pending_notifs: List of pending notification dicts.
        memory_count: Number of new memories formed.
        llm_provider: LLM provider instance.
        model: Model name to use.

    Returns:
        Formatted markdown summary string.
    """
    # Build context for the LLM
    conv_text = ""
    for c in conv_summaries[:5]:
        conv_text += f"\n### {c['title']} ({c['message_count']} messages)\n"
        for msg in c["messages"][:6]:
            role = "You" if msg["role"] == "user" else "AI"
            conv_text += f"- {role}: {msg['content'][:150]}\n"

    pending_text = ""
    if pending_notifs:
        pending_text = "\nPending reminders:\n"
        for n in pending_notifs:
            pending_text += f"- {n['subject']} (scheduled: {n['scheduled_at']})\n"

    prompt = f"""Generate a concise daily digest (3-5 bullet points max) summarizing what the user discussed yesterday. Include:
- Key topics and decisions
- Any action items or follow-ups mentioned
- Notable things learned or remembered ({memory_count} new memories formed)

Keep it brief, friendly, and useful. Use markdown formatting.

Yesterday's conversations:
{conv_text}
{pending_text}

Daily digest:"""

    messages = [
        {"role": "system", "content": "You are a personal assistant generating a brief daily digest. Be concise and highlight what matters."},
        {"role": "user", "content": prompt},
    ]

    response = ""
    async for chunk in llm_provider.stream(messages=messages, model=model, temperature=0.3):
        if chunk.content:
            response += chunk.content

    return response.strip()


def _build_raw_summary(
    conv_summaries: List[Dict],
    pending_notifs: List[Dict],
    memory_count: int,
) -> str:
    """Build a simple digest without LLM summarization.

    Args:
        conv_summaries: List of conversation dicts.
        pending_notifs: List of pending notification dicts.
        memory_count: Number of new memories formed.

    Returns:
        Formatted markdown summary string.
    """
    lines = ["## 📋 Daily Digest\n"]

    lines.append(f"**{len(conv_summaries)} conversation(s)** yesterday:\n")
    for c in conv_summaries:
        lines.append(f"- **{c['title']}** ({c['message_count']} messages)")

    if memory_count > 0:
        lines.append(f"\n🧠 **{memory_count} new memories** formed\n")

    if pending_notifs:
        lines.append("\n⏰ **Pending reminders:**")
        for n in pending_notifs:
            lines.append(f"- {n['subject']}")

    return "\n".join(lines)
