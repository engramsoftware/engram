"""
Search router.
Handles chat history search with hybrid BM25 + vector search.
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from database import get_database
from routers.auth import get_current_user
from search.hybrid_wrapper import HybridSearchWrapper
from search.search_interface import SearchFilters, SearchResult

logger = logging.getLogger(__name__)
router = APIRouter()

# Initialize search engine
search_engine = HybridSearchWrapper()


class SearchRequest(BaseModel):
    """Search request body."""
    query: str
    conversation_id: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    role: Optional[str] = None
    top_k: int = 10


class SearchResultResponse(BaseModel):
    """Search result for API response."""
    id: str
    conversation_id: str
    conversation_title: Optional[str] = None
    content: str
    role: str
    timestamp: datetime
    score: float
    highlight: Optional[str] = None


@router.post("", response_model=List[SearchResultResponse])
async def search_messages(
    request: SearchRequest,
    current_user: dict = Depends(get_current_user)
) -> dict:
    """
    Search chat history using hybrid search.
    
    The search pipeline:
    1. BM25 keyword search for exact term matching
    2. Vector search for semantic similarity (if available)
    3. Reciprocal Rank Fusion to combine results
    4. Cross-encoder reranking for final relevance
    
    Results can be used to provide context to the LLM.
    """
    db = get_database()
    user_id = current_user["id"]
    
    # Build search filters
    filters = SearchFilters(
        user_id=user_id,
        conversation_id=request.conversation_id,
        date_from=request.date_from,
        date_to=request.date_to,
        role=request.role
    )
    
    # Execute search
    results = await search_engine.search(
        query=request.query,
        user_id=user_id,
        filters=filters,
        top_k=request.top_k
    )
    
    # Fetch conversation titles for results
    conv_ids = list(set(r.conversation_id for r in results))
    conv_titles = {}
    
    if conv_ids:
        from bson import ObjectId
        async for conv in db.conversations.find(
            {"_id": {"$in": [ObjectId(cid) for cid in conv_ids]}}
        ):
            conv_titles[str(conv["_id"])] = conv.get("title", "Untitled")
    
    # Build response
    response = []
    for result in results:
        # Create highlight snippet
        highlight = _create_highlight(result.content, request.query)
        
        response.append(SearchResultResponse(
            id=result.id,
            conversation_id=result.conversation_id,
            conversation_title=conv_titles.get(result.conversation_id),
            content=result.content,
            role=result.role,
            timestamp=result.timestamp,
            score=result.score,
            highlight=highlight
        ))
    
    return response


def _create_highlight(content: str, query: str, context_chars: int = 100) -> str:
    """
    Create a highlighted snippet showing query match in context.
    
    Args:
        content: Full message content
        query: Search query
        context_chars: Characters to show around match
        
    Returns:
        Snippet with match highlighted
    """
    query_lower = query.lower()
    content_lower = content.lower()
    
    # Find first occurrence of any query word
    query_words = query_lower.split()
    match_pos = -1
    
    for word in query_words:
        pos = content_lower.find(word)
        if pos != -1:
            match_pos = pos
            break
    
    if match_pos == -1:
        # No match found, return start of content
        return content[:context_chars * 2] + ("..." if len(content) > context_chars * 2 else "")
    
    # Extract context around match
    start = max(0, match_pos - context_chars)
    end = min(len(content), match_pos + context_chars)
    
    snippet = content[start:end]
    
    # Add ellipsis if truncated
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."
    
    return snippet


@router.get("/status")
async def get_search_status(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Get search engine status.
    Returns whether hybrid search is enabled.
    """
    reranker_active = False
    if search_engine.hybrid_searcher:
        reranker_active = search_engine.hybrid_searcher.reranker is not None
    return {
        "hybrid_enabled": search_engine.is_hybrid_enabled(),
        "engine": "hybrid" if search_engine.is_hybrid_enabled() else "basic",
        "reranker_active": reranker_active,
    }
