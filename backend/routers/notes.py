"""
Notes router.
Handles CRUD operations for the user's knowledge base / notes system.

Notes support hierarchical folders, markdown content, tags, and
LLM read/write access so the assistant can act as Engram — creating,
updating, and referencing notes on behalf of the user.
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from bson import ObjectId

from database import get_database
from routers.auth import get_current_user
from models.note import NoteCreate, NoteResponse, NoteUpdate

logger = logging.getLogger(__name__)
router = APIRouter()


def _doc_to_response(doc: dict, child_count: int = 0) -> NoteResponse:
    """Convert a MongoDB document to a NoteResponse.

    Args:
        doc: Raw MongoDB document with camelCase fields.
        child_count: Number of child notes (for folders).

    Returns:
        NoteResponse with snake_case fields.
    """
    return NoteResponse(
        id=str(doc["_id"]),
        user_id=doc["userId"],
        title=doc["title"],
        content=doc.get("content", ""),
        folder=doc.get("folder"),
        parent_id=doc.get("parentId"),
        tags=doc.get("tags", []),
        is_folder=doc.get("isFolder", False),
        is_pinned=doc.get("isPinned", False),
        created_at=doc["createdAt"],
        updated_at=doc["updatedAt"],
        last_edited_by=doc.get("lastEditedBy", "user"),
        child_count=child_count,
    )


@router.post("", response_model=NoteResponse)
async def create_note(
    data: NoteCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Create a new note or folder."""
    db = get_database()

    now = datetime.utcnow()
    note_doc = {
        "userId": current_user["id"],
        "title": data.title or "Untitled",
        "content": data.content,
        "folder": data.folder,
        "parentId": data.parent_id,
        "tags": data.tags,
        "isFolder": data.is_folder,
        "isPinned": False,
        "createdAt": now,
        "updatedAt": now,
        "lastEditedBy": "user",
    }

    result = await db.notes.insert_one(note_doc)

    return NoteResponse(
        id=str(result.inserted_id),
        user_id=current_user["id"],
        title=note_doc["title"],
        content=note_doc["content"],
        folder=note_doc["folder"],
        parent_id=note_doc["parentId"],
        tags=note_doc["tags"],
        is_folder=note_doc["isFolder"],
        is_pinned=False,
        created_at=now,
        updated_at=now,
        last_edited_by="user",
        child_count=0,
    )


@router.get("", response_model=List[NoteResponse])
async def list_notes(
    current_user: dict = Depends(get_current_user),
    parent_id: Optional[str] = Query(None, description="Filter by parent folder ID"),
    folder: Optional[str] = Query(None, description="Filter by folder name"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    search: Optional[str] = Query(None, description="Full-text search in title/content"),
    limit: int = Query(100, ge=1, le=500),
    skip: int = Query(0, ge=0),
) -> dict:
    """
    List user's notes with optional filters.

    Folders appear first, then notes sorted by update time.
    """
    db = get_database()

    # Build query filter
    query: dict = {"userId": current_user["id"]}

    if parent_id is not None:
        query["parentId"] = parent_id
    elif folder is not None:
        query["folder"] = folder
    else:
        # Default: show root-level notes (no parent)
        query["parentId"] = None

    if tag:
        query["tags"] = tag

    if search:
        query["$text"] = {"$search": search}

    # Folders first, pinned first, then by update time
    cursor = (
        db.notes.find(query)
        .sort([("isFolder", -1), ("isPinned", -1), ("updatedAt", -1)])
        .skip(skip)
        .limit(limit)
    )

    notes = []
    async for doc in cursor:
        # Count children for folders
        child_count = 0
        if doc.get("isFolder"):
            child_count = await db.notes.count_documents({
                "userId": current_user["id"],
                "parentId": str(doc["_id"]),
            })
        notes.append(_doc_to_response(doc, child_count))

    return notes


@router.get("/all", response_model=List[NoteResponse])
async def list_all_notes(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    List ALL user's notes (flat list, no parent filter).
    Useful for building the full tree or search index on the frontend.
    """
    db = get_database()

    cursor = (
        db.notes.find({"userId": current_user["id"]})
        .sort([("isFolder", -1), ("isPinned", -1), ("updatedAt", -1)])
    )

    notes = []
    async for doc in cursor:
        child_count = 0
        if doc.get("isFolder"):
            child_count = await db.notes.count_documents({
                "userId": current_user["id"],
                "parentId": str(doc["_id"]),
            })
        notes.append(_doc_to_response(doc, child_count))

    return notes


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(
    note_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get a specific note by ID."""
    db = get_database()

    doc = await db.notes.find_one({
        "_id": ObjectId(note_id),
        "userId": current_user["id"],
    })

    if not doc:
        raise HTTPException(status_code=404, detail="Note not found")

    child_count = 0
    if doc.get("isFolder"):
        child_count = await db.notes.count_documents({
            "userId": current_user["id"],
            "parentId": note_id,
        })

    return _doc_to_response(doc, child_count)


@router.put("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: str,
    data: NoteUpdate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Update a note's content, title, tags, or location."""
    db = get_database()

    update_doc: dict = {"updatedAt": datetime.utcnow()}

    if data.title is not None:
        update_doc["title"] = data.title
    if data.content is not None:
        update_doc["content"] = data.content
    if data.folder is not None:
        update_doc["folder"] = data.folder
    if data.parent_id is not None:
        update_doc["parentId"] = data.parent_id
    if data.tags is not None:
        update_doc["tags"] = data.tags
    if data.is_pinned is not None:
        update_doc["isPinned"] = data.is_pinned
    if data.last_edited_by is not None:
        update_doc["lastEditedBy"] = data.last_edited_by
    else:
        update_doc["lastEditedBy"] = "user"

    result = await db.notes.find_one_and_update(
        {"_id": ObjectId(note_id), "userId": current_user["id"]},
        {"$set": update_doc},
        return_document=True,
    )

    if not result:
        raise HTTPException(status_code=404, detail="Note not found")

    return _doc_to_response(result)


@router.delete("/{note_id}")
async def delete_note(
    note_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """
    Delete a note. If it's a folder, also deletes all children recursively.
    """
    db = get_database()

    doc = await db.notes.find_one({
        "_id": ObjectId(note_id),
        "userId": current_user["id"],
    })

    if not doc:
        raise HTTPException(status_code=404, detail="Note not found")

    # Recursively delete children if this is a folder
    if doc.get("isFolder"):
        await _delete_children(db, current_user["id"], note_id)

    await db.notes.delete_one({"_id": ObjectId(note_id)})

    return {"message": "Note deleted"}


async def _delete_children(db, user_id: str, parent_id: str) -> None:
    """Recursively delete all child notes of a folder.

    Args:
        db: MongoDB database instance.
        user_id: Owner's user ID.
        parent_id: ID of the parent folder being deleted.
    """
    children = db.notes.find({"userId": user_id, "parentId": parent_id})
    async for child in children:
        child_id = str(child["_id"])
        if child.get("isFolder"):
            await _delete_children(db, user_id, child_id)
        await db.notes.delete_one({"_id": child["_id"]})
