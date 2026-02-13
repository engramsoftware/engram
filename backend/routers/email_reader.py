"""
Email reader router — read-only email access for LLM context.

Uses IMAP with the same app password from email settings (SMTP config).
Provides search, list, and read endpoints. NO deletes or modifications.
The LLM uses email content to provide recommendations and insights.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from database import get_database
from routers.auth import get_current_user
from utils.encryption import decrypt_api_key

logger = logging.getLogger(__name__)
router = APIRouter()


async def _get_email_reader(user_id: str):
    """Get a connected EmailReader for the given user.

    Loads email config from MongoDB settings, decrypts the app password,
    and creates an IMAP connection. Returns None if not configured.

    Args:
        user_id: User ID to load settings for.

    Returns:
        Connected EmailReader instance, or None.
    """
    from email_reader import get_email_reader_from_settings

    db = get_database()
    settings = await db.llm_settings.find_one({"userId": user_id})
    if not settings:
        return None

    email_cfg = settings.get("email", {})
    if not email_cfg.get("enabled") or not email_cfg.get("username") or not email_cfg.get("password"):
        return None

    try:
        password = decrypt_api_key(email_cfg["password"])
    except Exception:
        return None

    return get_email_reader_from_settings(email_cfg, password)


@router.get("/recent")
async def list_recent_emails(
    count: int = Query(default=20, ge=1, le=50, description="Number of emails"),
    folder: str = Query(default="INBOX", description="IMAP folder"),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """List recent emails from the user's inbox.

    Returns metadata only (from, subject, date) — not full body.
    Uses IMAP PEEK so emails aren't marked as read.
    """
    reader = await _get_email_reader(current_user["id"])
    if not reader:
        raise HTTPException(status_code=400, detail="Email not configured. Set up email in Settings first.")

    try:
        emails = reader.list_recent(folder=folder, count=count)
        return {"emails": emails, "count": len(emails)}
    finally:
        reader.disconnect()


@router.get("/search")
async def search_emails(
    q: str = Query(..., description="Search query (e.g. 'from:amazon subject:order')"),
    count: int = Query(default=20, ge=1, le=50),
    folder: str = Query(default="INBOX"),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Search emails using natural language queries.

    Supports: from:X, subject:Y, to:Z, or plain text for body/subject search.
    Never modifies or deletes emails.
    """
    reader = await _get_email_reader(current_user["id"])
    if not reader:
        raise HTTPException(status_code=400, detail="Email not configured. Set up email in Settings first.")

    try:
        emails = reader.search(query=q, folder=folder, count=count)
        return {"emails": emails, "query": q, "count": len(emails)}
    finally:
        reader.disconnect()


@router.get("/message/{uid}")
async def get_email_message(
    uid: str,
    folder: str = Query(default="INBOX"),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get full email content by UID.

    Returns headers + body text. Uses PEEK so it won't mark as read.
    Body is truncated to 4000 chars for token budget.
    """
    reader = await _get_email_reader(current_user["id"])
    if not reader:
        raise HTTPException(status_code=400, detail="Email not configured.")

    try:
        message = reader.get_message(uid=uid, folder=folder)
        if not message:
            raise HTTPException(status_code=404, detail="Email not found")
        return message
    finally:
        reader.disconnect()


@router.get("/context")
async def get_email_context(
    q: str = Query(..., description="Query to find relevant emails for LLM context"),
    count: int = Query(default=5, ge=1, le=10),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get email content formatted for LLM context injection.

    Searches emails and returns a pre-formatted summary string that can be
    injected into the LLM's system prompt. Designed for the chat pipeline.

    Args:
        q: Search query to find relevant emails.
        count: Number of emails to include in context.

    Returns:
        Dict with formatted context string and email count.
    """
    reader = await _get_email_reader(current_user["id"])
    if not reader:
        return {"context": "", "count": 0, "available": False}

    try:
        emails = reader.search(query=q, count=count)
        if not emails:
            return {"context": "", "count": 0, "available": True}

        # Fetch full content for top results
        context_parts = []
        for em in emails[:count]:
            full = reader.get_message(uid=em["uid"])
            if full:
                snippet = full.get("body", "")[:800]
                context_parts.append(
                    f"**From:** {full['from']}\n"
                    f"**Subject:** {full['subject']}\n"
                    f"**Date:** {full['date']}\n"
                    f"**Content:** {snippet}\n"
                )

        context = "## Relevant Emails\n\n" + "\n---\n".join(context_parts) if context_parts else ""
        return {"context": context, "count": len(context_parts), "available": True}
    finally:
        reader.disconnect()
