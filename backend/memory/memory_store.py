"""
Memory storage system using ChromaDB (vectors) + MongoDB (metadata).

This module provides persistent storage for autonomous memories with
semantic search capabilities.

Dual storage:
- ChromaDB: Vector embeddings for semantic similarity search
- MongoDB: Full metadata and content for queries and updates
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from bson import ObjectId

from memory.types import Memory, UpdateAction

logger = logging.getLogger(__name__)

# ChromaDB imports with graceful fallback
CHROMADB_AVAILABLE = False
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    logger.warning("ChromaDB not available for memory store")


class MemoryStore:
    """
    Persistent storage for autonomous memories.
    
    Uses dual storage:
    - ChromaDB collection 'user_memories' for vector search
    - MongoDB collection 'autonomous_memories' for metadata
    
    Methods:
        add(memory): Add a new memory
        search(query, user_id, limit): Semantic search for memories
        update(memory_id, content): Update an existing memory
        delete(memory_id): Delete a memory
        get_by_user(user_id): Get all active memories for a user
    """
    
    # Collection names
    CHROMA_COLLECTION = "user_memories"
    MONGO_COLLECTION = "autonomous_memories"
    
    def __init__(self, chroma_path: str = None, mongo_db = None):
        """
        Initialize memory store with ChromaDB and MongoDB.
        
        Args:
            chroma_path: Path for ChromaDB persistence (defaults to backend/data/chroma_memories)
            mongo_db: MongoDB database instance
        """
        self.chroma_client = None
        self.chroma_collection = None
        self.mongo_db = mongo_db
        self._initialized = False
        
        if not CHROMADB_AVAILABLE:
            logger.warning("MemoryStore: ChromaDB not available")
            return
        
        # Initialize ChromaDB
        self._init_chroma(chroma_path)
    
    def _init_chroma(self, path: Optional[str]) -> None:
        """Initialize ChromaDB client and collection."""
        try:
            from pathlib import Path
            
            # Default path if not provided
            if path is None:
                from config import CHROMA_MEMORIES_DIR
                path = CHROMA_MEMORIES_DIR
            else:
                path = Path(path)
            
            # Ensure directory exists
            path.mkdir(parents=True, exist_ok=True)
            
            # Create persistent client
            self.chroma_client = chromadb.PersistentClient(
                path=str(path),
                settings=Settings(anonymized_telemetry=False)
            )
            
            # Get or create collection with cosine similarity
            self.chroma_collection = self.chroma_client.get_or_create_collection(
                name=self.CHROMA_COLLECTION,
                metadata={"hnsw:space": "cosine"}
            )
            
            self._initialized = True
            logger.info(f"MemoryStore initialized with {self.chroma_collection.count()} memories")
            
        except Exception as e:
            logger.error(f"Failed to initialize MemoryStore: {e}")
            self._initialized = False
    
    @property
    def is_available(self) -> bool:
        """Check if the memory store is ready."""
        return self._initialized and self.chroma_collection is not None and self.mongo_db is not None
    
    async def add(self, memory: Memory) -> bool:
        """
        Add a new memory to the store.
        
        Stores in both ChromaDB (with embedding) and MongoDB (with metadata).
        
        Args:
            memory: Memory object to store
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available:
            logger.warning("MemoryStore not available, skipping add")
            return False
        
        if not memory.content or not memory.content.strip():
            logger.debug("Empty memory content, skipping")
            return False
        
        try:
            # Insert into MongoDB first to get ID
            mongo_doc = {
                "userId": memory.user_id,
                "content": memory.content,
                "memoryType": memory.memory_type.value,
                "confidence": memory.confidence,
                "createdAt": memory.created_at,
                "updatedAt": memory.updated_at,
                "invalidatedAt": memory.invalidated_at,
                "sourceConversationId": memory.source_conversation_id
            }
            
            result = await self.mongo_db[self.MONGO_COLLECTION].insert_one(mongo_doc)
            memory_id = str(result.inserted_id)
            
            # Add to ChromaDB with the MongoDB ID
            # ChromaDB will generate embeddings automatically
            self.chroma_collection.upsert(
                ids=[memory_id],
                documents=[memory.content],
                metadatas=[{
                    "user_id": memory.user_id,
                    "memory_type": memory.memory_type.value,
                    "confidence": memory.confidence,
                    "source_conversation_id": memory.source_conversation_id
                }]
            )
            
            logger.debug(f"Added memory {memory_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add memory: {e}")
            return False
    
    def search(
        self,
        query: str,
        user_id: str,
        limit: int = 5,
        min_confidence: float = 0.0
    ) -> List[Memory]:
        """
        Search for memories using semantic similarity.
        
        Args:
            query: Search query text
            user_id: Filter to this user's memories
            limit: Maximum number of results
            min_confidence: Minimum confidence threshold
            
        Returns:
            List of Memory objects sorted by relevance
        """
        if not self.is_available:
            logger.debug("MemoryStore not available, returning empty results")
            return []
        
        if not query or not query.strip():
            return []
        
        try:
            # Query ChromaDB for semantically similar memories
            results = self.chroma_collection.query(
                query_texts=[query],
                n_results=limit * 2,  # Get more to filter by confidence
                where={"user_id": user_id},
                include=["documents", "metadatas", "distances"]
            )
            
            if not results or not results['ids'] or not results['ids'][0]:
                return []
            
            # Convert to Memory objects
            memories = []
            for i, memory_id in enumerate(results['ids'][0]):
                metadata = results['metadatas'][0][i]
                
                # Filter by confidence
                if metadata.get('confidence', 0.0) < min_confidence:
                    continue
                
                memory = Memory(
                    id=memory_id,
                    content=results['documents'][0][i],
                    memory_type=metadata['memory_type'],
                    user_id=metadata['user_id'],
                    confidence=metadata.get('confidence', 0.8),
                    source_conversation_id=metadata.get('source_conversation_id', ''),
                    created_at=datetime.utcnow(),  # Will be overwritten by MongoDB fetch if needed
                    updated_at=datetime.utcnow()
                )
                memories.append(memory)
            
            logger.debug(f"Found {len(memories)} memories for query")
            return memories[:limit]
            
        except Exception as e:
            logger.error(f"Memory search failed: {e}")
            return []
    
    async def update(self, memory_id: str, content: str) -> bool:
        """
        Update an existing memory's content.
        
        Args:
            memory_id: ID of memory to update
            content: New content
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available:
            return False
        
        try:
            # Update in MongoDB
            result = await self.mongo_db[self.MONGO_COLLECTION].update_one(
                {"_id": ObjectId(memory_id)},
                {
                    "$set": {
                        "content": content,
                        "updatedAt": datetime.utcnow()
                    }
                }
            )
            
            if result.matched_count == 0:
                logger.warning(f"Memory {memory_id} not found for update")
                return False
            
            # Update in ChromaDB (will re-generate embedding)
            self.chroma_collection.update(
                ids=[memory_id],
                documents=[content]
            )
            
            logger.debug(f"Updated memory {memory_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update memory {memory_id}: {e}")
            return False
    
    async def delete(self, memory_id: str) -> bool:
        """
        Delete a memory from the store.
        
        Args:
            memory_id: ID of memory to delete
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available:
            return False
        
        try:
            # Delete from MongoDB
            result = await self.mongo_db[self.MONGO_COLLECTION].delete_one(
                {"_id": ObjectId(memory_id)}
            )
            
            if result.deleted_count == 0:
                logger.warning(f"Memory {memory_id} not found for deletion")
                return False
            
            # Delete from ChromaDB
            self.chroma_collection.delete(ids=[memory_id])
            
            logger.debug(f"Deleted memory {memory_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete memory {memory_id}: {e}")
            return False
    
    async def get_by_user(
        self,
        user_id: str,
        active_only: bool = True,
        limit: int = 100
    ) -> List[Memory]:
        """
        Get all memories for a user from MongoDB.
        
        Args:
            user_id: User ID to filter by
            active_only: If True, only return non-invalidated memories
            limit: Maximum number of memories to return
            
        Returns:
            List of Memory objects
        """
        if not self.is_available:
            return []
        
        try:
            # Build query
            query = {"userId": user_id}
            if active_only:
                query["invalidatedAt"] = None
            
            # Fetch from MongoDB
            cursor = self.mongo_db[self.MONGO_COLLECTION].find(query).limit(limit)
            
            memories = []
            async for doc in cursor:
                memory = Memory(
                    id=str(doc["_id"]),
                    content=doc["content"],
                    memory_type=doc["memoryType"],
                    user_id=doc["userId"],
                    confidence=doc.get("confidence", 0.8),
                    created_at=doc["createdAt"],
                    updated_at=doc["updatedAt"],
                    invalidated_at=doc.get("invalidatedAt"),
                    source_conversation_id=doc.get("sourceConversationId", "")
                )
                memories.append(memory)
            
            return memories
            
        except Exception as e:
            logger.error(f"Failed to get memories for user {user_id}: {e}")
            return []
    
    def get_count(self, user_id: Optional[str] = None) -> int:
        """
        Get count of memories in the store.
        
        Args:
            user_id: Optional user filter
            
        Returns:
            Number of memories
        """
        if not self.is_available:
            return 0
        
        if user_id:
            # Count with filter (requires querying)
            results = self.chroma_collection.query(
                query_texts=[""],
                n_results=1,
                where={"user_id": user_id}
            )
            return len(results['ids'][0]) if results and results['ids'] else 0
        else:
            return self.chroma_collection.count()


# Module-level singleton for easy access
_memory_store: Optional[MemoryStore] = None


def get_memory_store(mongo_db=None) -> MemoryStore:
    """
    Get or create the singleton MemoryStore instance.
    
    Args:
        mongo_db: MongoDB database instance (required on first call)
        
    Returns:
        MemoryStore singleton instance
    """
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore(mongo_db=mongo_db)
    elif mongo_db is not None and _memory_store.mongo_db is None:
        _memory_store.mongo_db = mongo_db
    return _memory_store
