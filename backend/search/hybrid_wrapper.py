"""
Hybrid Search Wrapper.
Wraps the external hybrid_search.py for advanced search capabilities.

INTEGRATION INSTRUCTIONS:
========================
This wrapper is designed to integrate with a hybrid_search.py module.
Place it in this search/ directory or set HYBRID_SEARCH_PATH in .env.

The hybrid search pipeline:
1. Vector Search - Semantic similarity using embeddings
2. BM25 - Keyword matching with term frequency
3. RRF (k=60) - Reciprocal Rank Fusion to combine results
4. Cross-Encoder Reranking - Final relevance scoring

To enable hybrid search:
1. Copy hybrid_search.py to this search/ directory
2. Install dependencies: rank_bm25, sentence-transformers
3. Set HYBRID_SEARCH_ENABLED=true in .env
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from search.search_interface import SearchInterface, SearchResult, SearchFilters
from search.basic_search import BasicKeywordSearch
from search.vector_store import get_vector_store
from database import get_database

logger = logging.getLogger(__name__)

# ============================================================
# Try to import the hybrid search module
# ============================================================
HYBRID_AVAILABLE = False
HybridSearcher = None

try:
    # Try importing from local search directory first
    from search.hybrid_search import HybridSearcher as HS
    HybridSearcher = HS
    HYBRID_AVAILABLE = True
    logger.info("Hybrid search module loaded from local directory")
except ImportError as e:
    # Hybrid search not available - will use basic search fallback
    logger.warning(f"Hybrid search not available: {e}")
    logger.info("Falling back to basic keyword search")


class HybridSearchWrapper(SearchInterface):
    """
    Wrapper for hybrid BM25 + embedding search with reranking.
    
    Falls back to BasicKeywordSearch if hybrid_search.py is not available.
    
    The hybrid search combines:
    - BM25 keyword search for exact term matching
    - Vector/embedding search for semantic similarity
    - Reciprocal Rank Fusion (RRF) to merge results
    - Cross-encoder reranking for final relevance scoring
    """
    
    def __init__(self, reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        """
        Initialize hybrid search wrapper.
        
        Args:
            reranker_model: Model name for cross-encoder reranking
        """
        self.reranker_model = reranker_model
        self.hybrid_searcher = None
        self.fallback = BasicKeywordSearch()
        
        # Initialize hybrid searcher if available
        if HYBRID_AVAILABLE and HybridSearcher:
            try:
                self.hybrid_searcher = HybridSearcher(reranker_model=reranker_model)
                logger.info("Hybrid searcher initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize hybrid searcher: {e}")
    
    async def search(
        self,
        query: str,
        user_id: str,
        filters: Optional[SearchFilters] = None,
        top_k: int = 5
    ) -> List[SearchResult]:
        """
        Search using hybrid BM25 + vector search with reranking.
        
        Pipeline:
        1. Fetch candidate documents from MongoDB
        2. Run BM25 keyword search
        3. (Optional) Run vector search if embeddings available
        4. Combine with Reciprocal Rank Fusion
        5. Rerank with cross-encoder
        
        Args:
            query: Search query
            user_id: User ID to filter by
            filters: Additional search filters
            top_k: Maximum results to return
            
        Returns:
            List of SearchResult objects sorted by relevance
        """
        # Fall back to basic search if hybrid not available
        if not self.hybrid_searcher:
            logger.debug("Using fallback basic search")
            return await self.fallback.search(query, user_id, filters, top_k)
        
        try:
            # Get vector store for semantic search
            vector_store = get_vector_store()
            
            # Fetch ALL user messages for BM25 keyword search
            # No limit — BM25 needs the full corpus to find keyword matches
            # from any point in conversation history
            documents = await self._fetch_candidate_documents(
                user_id, filters, limit=0
            )
            
            if not documents:
                return []
            
            # Get vector search results from ChromaDB
            # This provides semantic similarity matches
            vector_results = []
            if vector_store.is_available:
                conversation_id = filters.conversation_id if filters else None
                vector_results = vector_store.search(
                    query=query,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    top_k=20  # Get more for fusion
                )
                logger.debug(f"Vector search returned {len(vector_results)} results")
            
            # Run hybrid search combining BM25 + vector results
            # If no vector results, BM25 alone still works via RRF
            results = self.hybrid_searcher.hybrid_search(
                query=query,
                vector_results=vector_results if vector_results else documents,
                all_documents=documents,
                top_k=top_k,
                use_reranking=True
            )
            
            # Convert to SearchResult objects, fetching timestamps from
            # MongoDB for vector-only results that lack them
            search_results = []
            missing_ids = [
                doc.get("id", "") for doc in results
                if not doc.get("timestamp") and doc.get("id")
            ]
            timestamp_map: Dict[str, datetime] = {}
            if missing_ids:
                from bson import ObjectId as _ObjId
                valid_ids = []
                for mid in missing_ids:
                    try:
                        valid_ids.append(_ObjId(mid))
                    except Exception:
                        pass
                if valid_ids:
                    db = get_database()
                    async for msg in db.messages.find(
                        {"_id": {"$in": valid_ids}},
                        {"timestamp": 1}
                    ):
                        timestamp_map[str(msg["_id"])] = msg.get("timestamp", datetime.utcnow())

            for doc in results:
                doc_id = doc.get("id", "")
                ts = doc.get("timestamp") or timestamp_map.get(doc_id, datetime.utcnow())
                search_results.append(SearchResult(
                    id=doc_id,
                    conversation_id=doc.get("conversation_id", ""),
                    content=doc.get("content", ""),
                    role=doc.get("role", "user"),
                    timestamp=ts,
                    score=doc.get("rerank_score", doc.get("rrf_score", 0.0)),
                    metadata=doc.get("metadata", {})
                ))
            
            return search_results
            
        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            # Fall back to basic search on error
            return await self.fallback.search(query, user_id, filters, top_k)
    
    async def _fetch_candidate_documents(
        self,
        user_id: str,
        filters: Optional[SearchFilters],
        limit: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Fetch candidate documents from the database for BM25 keyword search.
        
        Args:
            user_id: User ID to filter by
            filters: Additional filters
            limit: Maximum documents to fetch (0 = no limit, fetch all)
            
        Returns:
            List of document dicts with 'content' field for BM25
        """
        db = get_database()
        
        # Build query filter
        match_filter: Dict[str, Any] = {"userId": user_id}
        
        if filters:
            if filters.conversation_id:
                match_filter["conversationId"] = filters.conversation_id
            if filters.role:
                match_filter["role"] = filters.role
            if filters.date_from:
                match_filter["timestamp"] = {"$gte": filters.date_from}
            if filters.date_to:
                if "timestamp" in match_filter:
                    match_filter["timestamp"]["$lte"] = filters.date_to
                else:
                    match_filter["timestamp"] = {"$lte": filters.date_to}
        
        # Fetch messages as candidates for BM25
        # limit=0 means fetch all — BM25 needs the full corpus
        cursor = db.messages.find(match_filter).sort("timestamp", -1)
        if limit > 0:
            cursor = cursor.limit(limit)
        
        documents = []
        async for doc in cursor:
            documents.append({
                "id": str(doc["_id"]),
                "conversation_id": doc["conversationId"],
                "content": doc["content"],
                "role": doc["role"],
                "timestamp": doc["timestamp"],
                "metadata": doc.get("metadata", {})
            })
        
        return documents
    
    async def index_message(
        self,
        message_id: str,
        conversation_id: str,
        user_id: str,
        content: str,
        role: str,
        timestamp: datetime,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Index a message for future search.
        
        This method:
        1. Adds the message embedding to ChromaDB for vector search
        2. MongoDB handles raw storage (done elsewhere)
        3. BM25 is computed on-demand during search
        
        Args:
            message_id: Unique message identifier
            conversation_id: Conversation this message belongs to
            user_id: User who owns this message
            content: Message text to embed
            role: Message role (user/assistant)
            timestamp: When the message was created
            metadata: Additional metadata
            
        Returns:
            True if indexing succeeded, False otherwise
        """
        # Get the vector store singleton
        vector_store = get_vector_store()
        
        if not vector_store.is_available:
            logger.debug("Vector store not available, skipping embedding")
            return True  # Return True to not break the flow
        
        # Add to ChromaDB - embedding is generated automatically
        success = vector_store.add_message(
            message_id=message_id,
            content=content,
            user_id=user_id,
            conversation_id=conversation_id,
            role=role,
            metadata=metadata
        )
        
        if success:
            logger.debug(f"Indexed message {message_id} in vector store")
        
        return success
    
    def is_hybrid_enabled(self) -> bool:
        """Check if hybrid search is available and enabled."""
        return self.hybrid_searcher is not None
