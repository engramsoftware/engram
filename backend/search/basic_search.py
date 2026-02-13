"""
Basic keyword search implementation.
Fallback when hybrid search is not available.
Uses MongoDB text search for simple keyword matching.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from search.search_interface import SearchInterface, SearchResult, SearchFilters
from database import get_database

logger = logging.getLogger(__name__)


class BasicKeywordSearch(SearchInterface):
    """
    Simple keyword-based search using MongoDB text index.
    
    This is a fallback implementation when the full hybrid search
    (BM25 + embeddings + reranking) is not available.
    
    Uses MongoDB's $text operator for basic keyword matching.
    """
    
    async def search(
        self,
        query: str,
        user_id: str,
        filters: Optional[SearchFilters] = None,
        top_k: int = 5
    ) -> List[SearchResult]:
        """
        Search messages using MongoDB text search.
        
        Args:
            query: Search query string
            user_id: User ID to filter by
            filters: Additional search filters
            top_k: Maximum results to return
            
        Returns:
            List of SearchResult objects
        """
        db = get_database()
        
        # Build query filter
        match_filter: Dict[str, Any] = {
            "userId": user_id,
            "$text": {"$search": query}
        }
        
        # Apply additional filters
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
        
        try:
            # Execute text search with relevance scoring
            cursor = db.messages.find(
                match_filter,
                {"score": {"$meta": "textScore"}}
            ).sort(
                [("score", {"$meta": "textScore"})]
            ).limit(top_k)
            
            results = []
            async for doc in cursor:
                results.append(SearchResult(
                    id=str(doc["_id"]),
                    conversation_id=doc["conversationId"],
                    content=doc["content"],
                    role=doc["role"],
                    timestamp=doc["timestamp"],
                    score=doc.get("score", 0.0),
                    metadata=doc.get("metadata", {})
                ))
            
            return results
            
        except Exception as e:
            logger.error(f"Basic search failed: {e}")
            # Fallback to simple regex search if text index fails
            return await self._fallback_regex_search(
                query, user_id, filters, top_k
            )
    
    async def _fallback_regex_search(
        self,
        query: str,
        user_id: str,
        filters: Optional[SearchFilters],
        top_k: int
    ) -> List[SearchResult]:
        """
        Fallback regex search when text index is unavailable.
        Less efficient but always works.
        """
        db = get_database()
        
        # Build case-insensitive regex pattern
        match_filter: Dict[str, Any] = {
            "userId": user_id,
            "content": {"$regex": query, "$options": "i"}
        }
        
        if filters and filters.conversation_id:
            match_filter["conversationId"] = filters.conversation_id
        
        cursor = db.messages.find(match_filter).sort(
            "timestamp", -1
        ).limit(top_k)
        
        results = []
        async for doc in cursor:
            results.append(SearchResult(
                id=str(doc["_id"]),
                conversation_id=doc["conversationId"],
                content=doc["content"],
                role=doc["role"],
                timestamp=doc["timestamp"],
                score=1.0,  # No scoring for regex
                metadata=doc.get("metadata", {})
            ))
        
        return results
    
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
        Index a message (no-op for basic search).
        MongoDB text index is automatic.
        """
        # MongoDB text index handles this automatically
        # No additional indexing needed
        return True
