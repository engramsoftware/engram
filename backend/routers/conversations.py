"""
Conversations router.
Handles CRUD operations for chat conversations.
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from bson import ObjectId

from database import get_database
from routers.auth import get_current_user
from models.conversation import (
    ConversationCreate, 
    ConversationResponse, 
    ConversationUpdate
)

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("", response_model=ConversationResponse)
async def create_conversation(
    data: ConversationCreate,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Create a new conversation."""
    db = get_database()
    
    now = datetime.utcnow()
    conv_doc = {
        "userId": current_user["id"],
        "title": data.title or "New Chat",
        "createdAt": now,
        "updatedAt": now,
        "modelProvider": data.model_provider,
        "modelName": data.model_name,
        "isPinned": False
    }
    
    result = await db.conversations.insert_one(conv_doc)
    
    return ConversationResponse(
        id=str(result.inserted_id),
        user_id=current_user["id"],
        title=conv_doc["title"],
        created_at=now,
        updated_at=now,
        model_provider=data.model_provider,
        model_name=data.model_name,
        is_pinned=False,
        message_count=0
    )


@router.get("", response_model=List[ConversationResponse])
async def list_conversations(
    current_user: dict = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=100),
    skip: int = Query(0, ge=0)
) -> dict:
    """
    List user's conversations, sorted by update time.
    Pinned conversations appear first.
    """
    db = get_database()
    
    # Fetch conversations sorted by pinned first, then by update time
    cursor = (
        db.conversations.find({"userId": current_user["id"]})
        .sort([("isPinned", -1), ("updatedAt", -1)])
        .skip(skip)
        .limit(limit)
    )

    # Collect all conversations first, then batch-count messages
    # to avoid N+1 queries (one count per conversation)
    conv_docs = []
    async for doc in cursor:
        conv_docs.append(doc)

    # Batch count: one query per conversation is unavoidable with the
    # MongoDB-style API, but SQLite is local so sub-ms per query.
    # For truly large lists, consider caching counts on the conversation doc.
    conversations = []
    for doc in conv_docs:
        conv_id = str(doc["_id"])
        msg_count = await db.messages.count_documents({"conversationId": conv_id})
        conversations.append(ConversationResponse(
            id=conv_id,
            user_id=doc["userId"],
            title=doc["title"],
            created_at=doc["createdAt"],
            updated_at=doc["updatedAt"],
            model_provider=doc.get("modelProvider"),
            model_name=doc.get("modelName"),
            is_pinned=doc.get("isPinned", False),
            message_count=msg_count,
        ))

    return conversations


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Get a specific conversation by ID."""
    db = get_database()
    
    conv = await db.conversations.find_one({
        "_id": ObjectId(conversation_id),
        "userId": current_user["id"]
    })
    
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Get message count
    msg_count = await db.messages.count_documents({
        "conversationId": conversation_id
    })
    
    return ConversationResponse(
        id=str(conv["_id"]),
        user_id=conv["userId"],
        title=conv["title"],
        created_at=conv["createdAt"],
        updated_at=conv["updatedAt"],
        model_provider=conv.get("modelProvider"),
        model_name=conv.get("modelName"),
        is_pinned=conv.get("isPinned", False),
        message_count=msg_count
    )


@router.put("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: str,
    data: ConversationUpdate,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Update conversation metadata."""
    db = get_database()
    
    # Build update document
    update_doc = {"updatedAt": datetime.utcnow()}
    if data.title is not None:
        update_doc["title"] = data.title
    if data.model_provider is not None:
        update_doc["modelProvider"] = data.model_provider
    if data.model_name is not None:
        update_doc["modelName"] = data.model_name
    if data.is_pinned is not None:
        update_doc["isPinned"] = data.is_pinned
    
    result = await db.conversations.find_one_and_update(
        {"_id": ObjectId(conversation_id), "userId": current_user["id"]},
        {"$set": update_doc},
        return_document=True
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    return ConversationResponse(
        id=str(result["_id"]),
        user_id=result["userId"],
        title=result["title"],
        created_at=result["createdAt"],
        updated_at=result["updatedAt"],
        model_provider=result.get("modelProvider"),
        model_name=result.get("modelName"),
        is_pinned=result.get("isPinned", False),
        message_count=0
    )


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Delete a conversation and all its messages."""
    db = get_database()
    
    # Verify ownership
    conv = await db.conversations.find_one({
        "_id": ObjectId(conversation_id),
        "userId": current_user["id"]
    })
    
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # Delete messages first
    await db.messages.delete_many({"conversationId": conversation_id})
    
    # Delete conversation
    await db.conversations.delete_one({"_id": ObjectId(conversation_id)})
    
    return {"message": "Conversation deleted"}
