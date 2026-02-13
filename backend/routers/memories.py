"""
Unified memories router.

Serves ALL memories (manual + autonomous) from a single set of endpoints.
Manual memories are user-created via the UI. Autonomous memories are
extracted automatically by the outlet pipeline from conversations.

Both types are stored in MongoDB and synced to ChromaDB for semantic search.
Deletes purge from ALL stores (MongoDB manual, MongoDB autonomous, ChromaDB).
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from bson import ObjectId

from database import get_database
from routers.auth import get_current_user
from models.memory import MemoryCreate, MemoryResponse, MemoryUpdate

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_chroma_collection():
    """Get the shared ChromaDB memories collection.

    Returns the same collection used by MemoryStore so manual and
    autonomous memories are searchable together.

    Returns:
        ChromaDB collection or None if unavailable.
    """
    try:
        import chromadb
        from chromadb.config import Settings
        from config import CHROMA_MEMORIES_DIR
        from pathlib import Path

        path = Path(CHROMA_MEMORIES_DIR)
        path.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(
            path=str(path),
            settings=Settings(anonymized_telemetry=False),
        )
        return client.get_or_create_collection(
            name="user_memories",
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        logger.debug(f"ChromaDB not available for memory sync: {e}")
        return None


@router.get("", response_model=List[MemoryResponse])
async def list_memories(
    current_user: dict = Depends(get_current_user),
    source: Optional[str] = Query(None, description="Filter: manual, autonomous, or all (default)"),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None, description="Semantic search query"),
) -> dict:
    """List ALL memories for the user (manual + autonomous).

    Combines both MongoDB collections into a single sorted list.
    Supports filtering by source and semantic search via ChromaDB.
    """
    db = get_database()
    user_id = current_user["id"]
    memories: List[MemoryResponse] = []

    # If semantic search is requested, use ChromaDB
    if search and search.strip():
        coll = _get_chroma_collection()
        if coll:
            try:
                results = coll.query(
                    query_texts=[search],
                    n_results=50,
                    where={"user_id": user_id},
                    include=["documents", "metadatas", "distances"],
                )
                if results and results["ids"] and results["ids"][0]:
                    for i, mid in enumerate(results["ids"][0]):
                        meta = results["metadatas"][0][i]
                        is_manual = meta.get("is_manual", False)
                        # Apply source filter
                        if source == "manual" and not is_manual:
                            continue
                        if source == "autonomous" and is_manual:
                            continue
                        memories.append(MemoryResponse(
                            id=mid,
                            content=results["documents"][0][i],
                            category=meta.get("category", meta.get("memory_type", "general")),
                            tags=[],
                            enabled=True,
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow(),
                            source="manual" if is_manual else "autonomous",
                            memory_type=meta.get("memory_type", "fact"),
                            confidence=meta.get("confidence", 0.8),
                        ))
            except Exception as e:
                logger.warning(f"Semantic memory search failed: {e}")
        return memories

    # No search — fetch from both MongoDB collections
    if source != "autonomous":
        # Manual memories from 'memories' collection
        query = {"userId": user_id}
        if category:
            query["category"] = category
        async for doc in db.memories.find(query).sort("createdAt", -1):
            memories.append(MemoryResponse(
                id=str(doc["_id"]),
                content=doc["content"],
                category=doc.get("category", "general"),
                tags=doc.get("tags", []),
                enabled=doc.get("enabled", True),
                created_at=doc["createdAt"],
                updated_at=doc["updatedAt"],
                source="manual",
                memory_type="fact",
                confidence=1.0,
            ))

    if source != "manual":
        # Autonomous memories from 'autonomous_memories' collection
        query = {"userId": user_id, "invalidatedAt": None}
        async for doc in db.autonomous_memories.find(query).sort("createdAt", -1):
            mem_type = doc.get("memoryType", "fact")
            memories.append(MemoryResponse(
                id=str(doc["_id"]),
                content=doc["content"],
                category=mem_type,
                tags=[],
                enabled=True,
                created_at=doc["createdAt"],
                updated_at=doc["updatedAt"],
                source="autonomous",
                memory_type=mem_type,
                confidence=doc.get("confidence", 0.8),
            ))

    # Sort combined list by created_at descending
    memories.sort(key=lambda m: m.created_at, reverse=True)
    return memories


@router.post("", response_model=MemoryResponse)
async def create_memory(
    data: MemoryCreate,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Create a new manual memory entry."""
    db = get_database()
    
    now = datetime.utcnow()
    memory_doc = {
        "userId": current_user["id"],
        "content": data.content,
        "category": data.category or "general",
        "tags": data.tags or [],
        "enabled": True,
        "createdAt": now,
        "updatedAt": now
    }
    
    result = await db.memories.insert_one(memory_doc)

    # Sync to ChromaDB so manual memories appear in semantic search
    try:
        coll = _get_chroma_collection()
        if coll:
            coll.upsert(
                ids=[str(result.inserted_id)],
                documents=[data.content],
                metadatas=[{
                    "user_id": current_user["id"],
                    "memory_type": "fact",
                    "confidence": 1.0,
                    "source_conversation_id": "",
                    "category": data.category or "general",
                    "is_manual": True,
                }],
            )
            logger.debug(f"Manual memory synced to ChromaDB: {result.inserted_id}")
    except Exception as e:
        logger.warning(f"Failed to sync manual memory to ChromaDB: {e}")

    return MemoryResponse(
        id=str(result.inserted_id),
        content=data.content,
        category=data.category or "general",
        tags=data.tags or [],
        enabled=True,
        created_at=now,
        updated_at=now
    )


@router.get("/categories/list")
async def list_categories(current_user: dict = Depends(get_current_user)) -> dict:
    """Get all unique memory categories for the user."""
    db = get_database()

    categories = await db.memories.distinct(
        "category",
        {"userId": current_user["id"]}
    )

    return {"categories": categories}


@router.post("/sync")
async def sync_memories(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Sync MongoDB and ChromaDB memory stores.

    Ensures every memory in both MongoDB collections has a corresponding
    entry in ChromaDB, and removes ChromaDB entries that no longer exist
    in MongoDB. This is a reconciliation endpoint — safe to call anytime.

    Returns:
        Stats on what was synced.
    """
    db = get_database()
    user_id = current_user["id"]
    coll = _get_chroma_collection()
    if not coll:
        raise HTTPException(status_code=503, detail="ChromaDB not available")

    stats = {"added_to_chroma": 0, "removed_from_chroma": 0, "already_synced": 0}

    # Collect all MongoDB memory IDs for this user
    mongo_ids: dict = {}  # id -> (content, metadata)

    # Manual memories
    async for doc in db.memories.find({"userId": user_id, "enabled": True}):
        mid = str(doc["_id"])
        mongo_ids[mid] = (
            doc["content"],
            {
                "user_id": user_id,
                "memory_type": "fact",
                "confidence": 1.0,
                "source_conversation_id": "",
                "category": doc.get("category", "general"),
                "is_manual": True,
            },
        )

    # Autonomous memories
    async for doc in db.autonomous_memories.find(
        {"userId": user_id, "invalidatedAt": None}
    ):
        mid = str(doc["_id"])
        mongo_ids[mid] = (
            doc["content"],
            {
                "user_id": user_id,
                "memory_type": doc.get("memoryType", "fact"),
                "confidence": doc.get("confidence", 0.8),
                "source_conversation_id": doc.get("sourceConversationId", ""),
            },
        )

    # Get all ChromaDB IDs for this user
    chroma_results = coll.get(
        where={"user_id": user_id},
        include=["metadatas"],
    )
    chroma_ids = set(chroma_results["ids"]) if chroma_results["ids"] else set()

    # Add missing entries to ChromaDB
    for mid, (content, metadata) in mongo_ids.items():
        if mid not in chroma_ids:
            coll.upsert(ids=[mid], documents=[content], metadatas=[metadata])
            stats["added_to_chroma"] += 1
        else:
            stats["already_synced"] += 1

    # Remove orphaned ChromaDB entries (no longer in MongoDB)
    orphaned = chroma_ids - set(mongo_ids.keys())
    if orphaned:
        coll.delete(ids=list(orphaned))
        stats["removed_from_chroma"] = len(orphaned)

    logger.info(f"Memory sync for user {user_id}: {stats}")
    return stats


# ── Parameterized routes MUST come after fixed-path routes ──


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: str,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Get a specific memory entry."""
    db = get_database()
    
    memory = await db.memories.find_one({
        "_id": ObjectId(memory_id),
        "userId": current_user["id"]
    })
    
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")
    
    return MemoryResponse(
        id=str(memory["_id"]),
        content=memory["content"],
        category=memory.get("category", "general"),
        tags=memory.get("tags", []),
        enabled=memory.get("enabled", True),
        created_at=memory["createdAt"],
        updated_at=memory["updatedAt"]
    )


@router.put("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: str,
    data: MemoryUpdate,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Update a memory entry."""
    db = get_database()
    
    # Build update document
    update_doc = {"updatedAt": datetime.utcnow()}
    
    if data.content is not None:
        update_doc["content"] = data.content
    if data.category is not None:
        update_doc["category"] = data.category
    if data.tags is not None:
        update_doc["tags"] = data.tags
    if data.enabled is not None:
        update_doc["enabled"] = data.enabled
    
    result = await db.memories.find_one_and_update(
        {"_id": ObjectId(memory_id), "userId": current_user["id"]},
        {"$set": update_doc},
        return_document=True
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Sync update to ChromaDB
    try:
        coll = _get_chroma_collection()
        if coll and result.get("enabled", True):
            coll.upsert(
                ids=[str(result["_id"])],
                documents=[result["content"]],
                metadatas=[{
                    "user_id": current_user["id"],
                    "memory_type": "fact",
                    "confidence": 1.0,
                    "source_conversation_id": "",
                    "category": result.get("category", "general"),
                    "is_manual": True,
                }],
            )
        elif coll and not result.get("enabled", True):
            # Disabled memories should be removed from search
            try:
                coll.delete(ids=[str(result["_id"])])
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Failed to sync manual memory update to ChromaDB: {e}")

    return MemoryResponse(
        id=str(result["_id"]),
        content=result["content"],
        category=result.get("category", "general"),
        tags=result.get("tags", []),
        enabled=result.get("enabled", True),
        created_at=result["createdAt"],
        updated_at=result["updatedAt"]
    )


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: str,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """Delete a memory from ALL stores (manual MongoDB, autonomous MongoDB, ChromaDB).

    Tries both MongoDB collections so the caller doesn't need to know
    which collection the memory lives in.
    """
    db = get_database()
    user_id = current_user["id"]
    deleted = False

    # Try deleting from manual memories collection
    result = await db.memories.delete_one({
        "_id": ObjectId(memory_id),
        "userId": user_id,
    })
    if result.deleted_count > 0:
        deleted = True
        logger.debug(f"Deleted manual memory {memory_id}")

    # Try deleting from autonomous memories collection
    result = await db.autonomous_memories.delete_one({
        "_id": ObjectId(memory_id),
        "userId": user_id,
    })
    if result.deleted_count > 0:
        deleted = True
        logger.debug(f"Deleted autonomous memory {memory_id}")

    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Remove from ChromaDB (covers both manual and autonomous)
    try:
        coll = _get_chroma_collection()
        if coll:
            try:
                coll.delete(ids=[memory_id])
                logger.debug(f"Deleted memory {memory_id} from ChromaDB")
            except Exception:
                pass  # May not exist in ChromaDB
    except Exception as e:
        logger.debug(f"ChromaDB delete skipped: {e}")

    return {"message": "Memory deleted"}
