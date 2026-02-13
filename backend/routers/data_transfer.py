"""
Data import/export endpoints.

Handles:
- Import conversations from ChatGPT export (conversations.json)
- Export all user data as a downloadable ZIP archive
"""

import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from database import get_database
from routers.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Data Transfer"])


# ============================================================
# ChatGPT Import
# ============================================================

def _extract_chatgpt_messages(conversation: dict) -> List[dict]:
    """Walk the ChatGPT conversation tree and extract messages in order.

    ChatGPT exports use a tree structure with a `mapping` dict.
    Each node has a parent pointer. We walk from `current_node` back
    to the root, then reverse to get chronological order.

    Args:
        conversation: A single conversation object from conversations.json.

    Returns:
        List of dicts with keys: role, content, timestamp.
    """
    mapping = conversation.get("mapping", {})
    current_node = conversation.get("current_node")
    messages = []

    while current_node:
        node = mapping.get(current_node, {})
        msg = node.get("message") if node else None

        if msg:
            author_role = msg.get("author", {}).get("role", "")
            content = msg.get("content", {})
            parts = content.get("parts", []) if content.get("content_type") == "text" else []

            # Join text parts, skip empty messages and system prompts
            text = ""
            for part in parts:
                if isinstance(part, str):
                    text += part
                elif isinstance(part, dict):
                    # Some parts are dicts (e.g. image references) — skip
                    pass

            if text.strip() and author_role in ("user", "assistant"):
                # Extract timestamp from create_time
                create_time = msg.get("create_time")
                ts = (
                    datetime.fromtimestamp(create_time, tz=timezone.utc).isoformat()
                    if create_time
                    else datetime.now(timezone.utc).isoformat()
                )
                messages.append({
                    "role": author_role,
                    "content": text.strip(),
                    "timestamp": ts,
                })

        current_node = node.get("parent") if node else None

    # Walking from leaf to root gives reverse order — flip it
    messages.reverse()
    return messages


@router.post("/import/chatgpt")
async def import_chatgpt(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
) -> dict:
    """Import conversations from a ChatGPT export ZIP or conversations.json.

    Accepts either:
    - A ZIP file (the raw ChatGPT export) containing conversations.json
    - A bare conversations.json file

    Each ChatGPT conversation becomes a conversation in this app with
    all its messages preserved.

    Args:
        file: The uploaded file (ZIP or JSON).
        user: The authenticated user.

    Returns:
        Summary of imported conversations and messages.
    """
    user_id = str(user["id"])
    db = get_database()

    # Read the uploaded file
    raw = await file.read()
    conversations_data = None

    # Try ZIP first (ChatGPT exports as ZIP)
    if file.filename and file.filename.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                # Look for conversations.json inside the ZIP
                for name in zf.namelist():
                    if name.endswith("conversations.json"):
                        with zf.open(name) as f:
                            conversations_data = json.loads(f.read())
                        break
                if conversations_data is None:
                    raise HTTPException(
                        status_code=400,
                        detail="ZIP file does not contain conversations.json",
                    )
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid ZIP file")
    else:
        # Try parsing as raw JSON
        try:
            conversations_data = json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON file")

    if not isinstance(conversations_data, list):
        raise HTTPException(
            status_code=400,
            detail="Expected a JSON array of conversations",
        )

    imported_convos = 0
    imported_messages = 0
    skipped = 0

    for conv in conversations_data:
        title = conv.get("title", "Imported Chat")
        create_time = conv.get("create_time")
        update_time = conv.get("update_time")

        messages = _extract_chatgpt_messages(conv)
        if not messages:
            skipped += 1
            continue

        # Create the conversation
        created_at = (
            datetime.fromtimestamp(create_time, tz=timezone.utc)
            if create_time
            else datetime.now(timezone.utc)
        )
        updated_at = (
            datetime.fromtimestamp(update_time, tz=timezone.utc)
            if update_time
            else created_at
        )

        conv_doc = {
            "userId": user_id,
            "title": title,
            "createdAt": created_at.isoformat(),
            "updatedAt": updated_at.isoformat(),
            "modelProvider": "chatgpt-import",
            "modelName": conv.get("default_model_slug", "unknown"),
            "isPinned": False,
            "messageCount": len(messages),
        }
        result = await db.conversations.insert_one(conv_doc)
        conv_id = str(result.inserted_id)

        # Insert all messages
        for msg in messages:
            msg_doc = {
                "conversationId": conv_id,
                "userId": user_id,
                "role": msg["role"],
                "content": msg["content"],
                "timestamp": msg["timestamp"],
                "metadata": {"source": "chatgpt-import"},
            }
            await db.messages.insert_one(msg_doc)

        imported_convos += 1
        imported_messages += len(messages)

    logger.info(
        f"ChatGPT import for user {user_id}: "
        f"{imported_convos} conversations, {imported_messages} messages, "
        f"{skipped} skipped (empty)"
    )

    return {
        "status": "success",
        "imported": {
            "conversations": imported_convos,
            "messages": imported_messages,
        },
        "skipped": skipped,
        "total_in_file": len(conversations_data),
    }


# ============================================================
# Export All User Data
# ============================================================

@router.get("/export")
async def export_user_data(
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """Export all user data as a downloadable ZIP archive.

    Includes:
    - conversations.json — all conversations with messages
    - memories.json — all autonomous memories
    - notes.json — all notes
    - personas.json — all custom personas
    - settings.json — LLM provider settings (API keys redacted)

    Returns:
        A streaming ZIP file download.
    """
    user_id = str(user["id"])
    db = get_database()

    # Gather all user data
    conversations = []
    async for conv in db.conversations.find({"userId": user_id}):
        conv_id = str(conv["_id"])
        conv["_id"] = conv_id

        # Fetch messages for this conversation
        msgs = []
        async for msg in db.messages.find({"conversationId": conv_id}):
            msg["_id"] = str(msg["_id"])
            msgs.append(msg)

        conv["messages"] = msgs
        conversations.append(conv)

    memories = []
    async for mem in db.memories.find({"userId": user_id}):
        mem["_id"] = str(mem["_id"])
        memories.append(mem)

    notes = []
    async for note in db.notes.find({"userId": user_id}):
        note["_id"] = str(note["_id"])
        notes.append(note)

    personas = []
    async for persona in db.personas.find({"userId": user_id}):
        persona["_id"] = str(persona["_id"])
        personas.append(persona)

    # Settings (redact API keys)
    settings_doc = await db.llm_settings.find_one({"userId": user_id})
    if settings_doc:
        settings_doc["_id"] = str(settings_doc["_id"])
        # Redact any API keys
        providers = settings_doc.get("providers", {})
        for prov_name, prov_data in providers.items():
            if isinstance(prov_data, dict) and "apiKey" in prov_data:
                key = prov_data["apiKey"]
                if key and len(key) > 8:
                    prov_data["apiKey"] = key[:4] + "..." + key[-4:]
    else:
        settings_doc = {}

    # Build ZIP in memory
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "conversations.json",
            json.dumps(conversations, indent=2, default=str, ensure_ascii=False),
        )
        zf.writestr(
            "memories.json",
            json.dumps(memories, indent=2, default=str, ensure_ascii=False),
        )
        zf.writestr(
            "notes.json",
            json.dumps(notes, indent=2, default=str, ensure_ascii=False),
        )
        zf.writestr(
            "personas.json",
            json.dumps(personas, indent=2, default=str, ensure_ascii=False),
        )
        zf.writestr(
            "settings.json",
            json.dumps(settings_doc, indent=2, default=str, ensure_ascii=False),
        )

        # Add a README
        readme = (
            "Engram Data Export\n"
            "===================\n\n"
            f"Exported: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"User: {user.get('email', 'unknown')}\n\n"
            "Files:\n"
            "  conversations.json — All conversations with messages\n"
            "  memories.json      — Autonomous memories\n"
            "  notes.json         — Notes and folders\n"
            "  personas.json      — Custom AI personas\n"
            "  settings.json      — LLM settings (API keys redacted)\n"
        )
        zf.writestr("README.txt", readme)

    buffer.seek(0)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"engram_export_{timestamp}.zip"

    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
