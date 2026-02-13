"""
ChromaDB Vector Store for semantic search.

This module provides a ChromaDB-based vector store for storing and searching
message embeddings. It uses the persistent client to store data locally.

Key features:
- Persistent storage at backend/data/chroma
- Cosine similarity for text matching
- Default all-MiniLM-L6-v2 embeddings (same family as cross-encoder reranker)
- Thread-safe operations

Usage:
    vector_store = VectorStore()
    await vector_store.add_message(message_id, content, user_id, conversation_id)
    results = await vector_store.search(query, user_id, top_k=10)
"""

import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# ============================================================
# ChromaDB imports with graceful fallback
# ============================================================
CHROMADB_AVAILABLE = False

try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
    logger.info("ChromaDB loaded successfully")
except ImportError as e:
    logger.warning(f"ChromaDB not available: {e}")


class VectorStore:
    """
    ChromaDB-based vector store for message embeddings.
    
    Stores embeddings locally in backend/data/chroma for persistence.
    Uses cosine similarity and the default all-MiniLM-L6-v2 model.
    
    Attributes:
        client: ChromaDB PersistentClient instance
        collection: The message_embeddings collection
    """
    
    # Collection name for message embeddings
    COLLECTION_NAME = "message_embeddings"
    
    # Default storage path (relative to backend directory)
    DEFAULT_PATH = None  # Set in __init__ from config
    
    def __init__(self, persist_path: Optional[Path] = None):
        """
        Initialize the vector store with ChromaDB persistent client.
        
        Args:
            persist_path: Path to store ChromaDB data. Defaults to backend/data/chroma
        """
        self.client = None
        self.collection = None
        self._initialized = False
        
        if not CHROMADB_AVAILABLE:
            logger.warning("VectorStore disabled - ChromaDB not installed")
            return
        
        # Use provided path or centralized config default
        from config import CHROMA_MESSAGES_DIR
        path = persist_path or CHROMA_MESSAGES_DIR
        
        try:
            # Ensure directory exists
            path.mkdir(parents=True, exist_ok=True)
            
            # Initialize persistent client
            # Settings() uses defaults which are fine for local use
            self.client = chromadb.PersistentClient(
                path=str(path),
                settings=Settings(anonymized_telemetry=False)
            )
            
            # Get or create the collection
            # Using cosine distance for text similarity (better than L2 for embeddings)
            self.collection = self.client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )
            
            self._initialized = True
            logger.info(f"VectorStore initialized at {path}")
            logger.info(f"Collection '{self.COLLECTION_NAME}' has {self.collection.count()} documents")
            
        except Exception as e:
            logger.error(f"Failed to initialize VectorStore: {e}")
            self._initialized = False
    
    @property
    def is_available(self) -> bool:
        """Check if the vector store is initialized and ready."""
        return self._initialized and self.collection is not None
    
    def add_message(
        self,
        message_id: str,
        content: str,
        user_id: str,
        conversation_id: str,
        role: str = "user",
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Add a message embedding to the vector store.
        
        ChromaDB handles embedding generation automatically using
        the default all-MiniLM-L6-v2 model.
        
        Args:
            message_id: Unique identifier for the message
            content: The message text to embed
            user_id: User who owns this message
            conversation_id: Conversation this message belongs to
            role: Message role (user/assistant)
            metadata: Additional metadata to store
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available:
            logger.debug("VectorStore not available, skipping add_message")
            return False
        
        if not content or not content.strip():
            logger.debug(f"Skipping empty content for message {message_id}")
            return False
        
        try:
            # Build metadata for filtering
            doc_metadata = {
                "user_id": user_id,
                "conversation_id": conversation_id,
                "role": role
            }
            
            # Add any extra metadata
            if metadata:
                doc_metadata.update(metadata)
            
            # Upsert to handle duplicates gracefully
            self.collection.upsert(
                ids=[message_id],
                documents=[content],
                metadatas=[doc_metadata]
            )
            
            logger.debug(f"Added message {message_id} to vector store")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add message {message_id}: {e}")
            return False
    
    def search(
        self,
        query: str,
        user_id: str,
        conversation_id: Optional[str] = None,
        top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search for similar messages using vector similarity.
        
        Args:
            query: The search query text
            user_id: Filter to this user's messages
            conversation_id: Optional filter to specific conversation
            top_k: Maximum number of results to return
            
        Returns:
            List of dicts with 'id', 'content', 'distance', and metadata
        """
        if not self.is_available:
            logger.debug("VectorStore not available, returning empty results")
            return []
        
        if not query or not query.strip():
            return []
        
        try:
            # Build filter for user (and optionally conversation)
            where_filter = {"user_id": user_id}
            if conversation_id:
                where_filter["conversation_id"] = conversation_id
            
            # Query the collection
            results = self.collection.query(
                query_texts=[query],
                n_results=top_k,
                where=where_filter,
                include=["documents", "metadatas", "distances"]
            )
            
            # Convert to list of dicts
            # ChromaDB returns nested lists: results['ids'][0], results['documents'][0], etc.
            output = []
            if results and results['ids'] and results['ids'][0]:
                for i, doc_id in enumerate(results['ids'][0]):
                    output.append({
                        "id": doc_id,
                        "content": results['documents'][0][i] if results['documents'] else "",
                        "distance": results['distances'][0][i] if results['distances'] else 0.0,
                        "conversation_id": results['metadatas'][0][i].get('conversation_id', ''),
                        "role": results['metadatas'][0][i].get('role', 'user'),
                        "metadata": results['metadatas'][0][i] if results['metadatas'] else {}
                    })
            
            logger.debug(f"Vector search returned {len(output)} results for query")
            return output
            
        except Exception as e:
            logger.error(f"Vector search failed: {e}")
            return []
    
    def delete_conversation(self, conversation_id: str) -> bool:
        """
        Delete all embeddings for a conversation.
        
        Args:
            conversation_id: The conversation to delete embeddings for
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available:
            return False
        
        try:
            # Delete by metadata filter
            self.collection.delete(
                where={"conversation_id": conversation_id}
            )
            logger.info(f"Deleted embeddings for conversation {conversation_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete conversation {conversation_id}: {e}")
            return False
    
    def get_count(self) -> int:
        """Get the total number of embeddings in the store."""
        if not self.is_available:
            return 0
        return self.collection.count()


# ============================================================
# Module-level singleton for easy access
# ============================================================
_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """
    Get the singleton VectorStore instance.
    
    Creates the instance on first call, reuses on subsequent calls.
    This ensures only one ChromaDB client is created.
    
    Returns:
        The VectorStore singleton instance
    """
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
