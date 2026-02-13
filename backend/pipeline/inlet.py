"""
Inlet pipeline: enriches user requests with relevant context.

Retrieves context from multiple sources and fuses results before
sending to the LLM.
"""

import logging
import asyncio
from typing import List, Dict, Any, Optional

from retrieval.fusion import reciprocal_rank_fusion, merge_and_deduplicate

logger = logging.getLogger(__name__)


async def enrich_request(
    messages: List[Dict[str, str]],
    user_id: str,
    conversation_id: str,
    hybrid_search=None,
    memory_store=None,
    graph_store=None,
    negative_store=None,
    top_k: int = 15
) -> str:
    """
    Enrich user request with relevant context from all sources.
    
    Runs parallel retrievals from:
    - Hybrid search (BM25 + vector)
    - Memory store (facts, preferences, decisions)
    - Knowledge graph (entities, relationships)
    - Negative knowledge (failures, warnings)
    
    Then fuses results using RRF and formats as context string.
    
    Args:
        messages: Conversation messages (last message is current query)
        user_id: User ID for personalization
        conversation_id: Current conversation ID
        hybrid_search: HybridSearchWrapper instance
        memory_store: MemoryStore instance
        graph_store: Neo4jGraphStore instance
        negative_store: NegativeKnowledgeStore instance
        top_k: Maximum context items to return
        
    Returns:
        Formatted context string to prepend to messages
    """
    if not messages:
        return ""
    
    # Extract query from last message
    query = messages[-1].get("content", "")
    if not query.strip():
        return ""
    
    logger.info(f"Enriching request for user {user_id}")
    
    # Prepare tasks for parallel retrieval
    tasks = []
    task_names = []
    
    # 1. Hybrid search (messages)
    if hybrid_search and hasattr(hybrid_search, 'search'):
        tasks.append(_safe_hybrid_search(hybrid_search, query, user_id, conversation_id))
        task_names.append("hybrid")
    
    # 2. Memory search
    if memory_store and hasattr(memory_store, 'search'):
        tasks.append(_safe_memory_search(memory_store, query, user_id))
        task_names.append("memory")
    
    # 3. Negative knowledge search (same hybrid BM25+vector logic)
    if negative_store and hasattr(negative_store, 'search'):
        tasks.append(_safe_negative_search(negative_store, query, user_id))
        task_names.append("negative")
    
    # 4. Knowledge graph search (entity-linked, 2-hop traversal)
    if graph_store and hasattr(graph_store, 'search_by_query'):
        tasks.append(_safe_graph_search(graph_store, query, user_id))
        task_names.append("graph")
    
    if not tasks:
        logger.warning("No retrieval sources available")
        return ""
    
    # Run all retrievals in parallel
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions and log errors
        valid_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"{task_names[i]} retrieval failed: {result}")
            elif result:
                valid_results.append(result)
                logger.debug(f"{task_names[i]}: {len(result)} results")
        
        if not valid_results:
            return ""
        
        # Fuse results using RRF
        fused = reciprocal_rank_fusion(valid_results, k=60, top_k=top_k)
        
        # Deduplicate
        final_results = merge_and_deduplicate(fused)
        
        # Format as context
        context = format_context(final_results, top_k=top_k)
        
        logger.info(f"Context enriched with {len(final_results)} items")
        return context
        
    except Exception as e:
        logger.error(f"Error during context enrichment: {e}")
        return ""


async def _safe_hybrid_search(hybrid_search, query: str, user_id: str, conversation_id: str) -> List[Dict[str, Any]]:
    """Safe wrapper for hybrid search."""
    try:
        # Import here to avoid circular dependencies
        from search.hybrid_wrapper import SearchFilters
        
        filters = SearchFilters(
            conversation_id=conversation_id,
            user_id=user_id
        )
        
        results = await hybrid_search.search(query, filters=filters, top_k=10)
        
        # Convert to standard format
        return [
            {
                "content": r.get("content", ""),
                "score": r.get("score", 0.0),
                "type": "message",
                "metadata": r.get("metadata", {})
            }
            for r in results
        ]
    except Exception as e:
        logger.error(f"Hybrid search error: {e}")
        return []


async def _safe_memory_search(memory_store, query: str, user_id: str) -> List[Dict[str, Any]]:
    """Safe wrapper for memory search."""
    try:
        memories = memory_store.search(query, user_id, limit=10)
        
        # Convert Memory objects to dict format
        return [
            {
                "content": m.content,
                "score": m.confidence,
                "type": "memory",
                "memory_type": m.memory_type.value
            }
            for m in memories
        ]
    except Exception as e:
        logger.error(f"Memory search error: {e}")
        return []


async def _safe_negative_search(negative_store, query: str, user_id: str) -> List[Dict[str, Any]]:
    """Search negative knowledge using BM25+vector hybrid search with reranking.

    Same search logic as hybrid message search: vector retrieval from ChromaDB,
    BM25 keyword matching, RRF fusion, then cross-encoder reranking. Only results
    that survive reranking with positive scores are returned.

    Args:
        negative_store: NegativeKnowledgeStore instance.
        query: User's query text.
        user_id: User ID for filtering.

    Returns:
        List of dicts in the standard retrieval format (content, score, type).
    """
    try:
        from search.hybrid_search import get_hybrid_searcher

        # Get raw vector results from ChromaDB (more candidates for hybrid filtering)
        raw = negative_store.search_raw(query, user_id, limit=10)
        if not raw:
            return []

        # Run BM25+vector+RRF+reranking (same logic as message hybrid search)
        searcher = get_hybrid_searcher()
        hybrid_results = searcher.hybrid_search(
            query=query,
            vector_results=raw,
            top_k=3,
            use_reranking=True,
        )

        # Convert to standard format — plain content, no ⚠️ markers
        results = []
        for r in hybrid_results:
            score = r.get("rerank_score", r.get("rrf_score", 0))
            # Only include if reranker scored it positively (relevant to query)
            if score <= 0:
                continue
            what = r.get("what_failed", "")
            why = r.get("why_failed", "")
            content = f"{what} — {why}" if what and why else r.get("content", "")
            results.append({
                "content": content,
                "score": float(score),
                "type": "negative_knowledge",
            })

        return results
    except Exception as e:
        logger.error(f"Negative knowledge search error: {e}")
        return []


async def _safe_graph_search(graph_store, query: str, user_id: str) -> List[Dict[str, Any]]:
    """Safe wrapper for knowledge graph search.

    Runs GLiNER entity linking on the query, then 2-hop traversal
    with temporal decay and community detection.

    Args:
        graph_store: Neo4jGraphStore instance.
        query: User's query text.
        user_id: User ID for graph isolation.

    Returns:
        List of dicts in the standard retrieval format (content, score, type).
    """
    try:
        from fastapi.concurrency import run_in_threadpool
        # Neo4j driver is sync — run in threadpool to avoid blocking event loop
        graph_results = await run_in_threadpool(graph_store.search_by_query, query, user_id, 5)
        if not graph_results:
            return []

        # Format graph results into the standard retrieval format
        # so they can participate in RRF fusion with other sources
        formatted = []
        context_text = graph_store.format_context_for_prompt(graph_results)
        if context_text:
            formatted.append({
                "content": context_text,
                "score": max(r.get("relevance", 0.5) for r in graph_results),
                "type": "graph_context",
            })

        return formatted
    except Exception as e:
        logger.error(f"Knowledge graph search error: {e}")
        return []


def format_context(
    results: List[Dict[str, Any]],
    top_k: int = 15
) -> str:
    """
    Format fused results into a context string for the LLM.
    
    Args:
        results: Fused and sorted results
        top_k: Maximum items to include
        
    Returns:
        Formatted context string
    """
    if not results:
        return ""
    
    context_parts = ["# Relevant Context\n"]
    
    # Group by type for better organization
    messages = [r for r in results if r.get("type") == "message"]
    memories = [r for r in results if r.get("type") == "memory"]
    warnings = [r for r in results if r.get("type") == "negative_knowledge"]
    graph = [r for r in results if r.get("type") == "graph_context"]
    
    # Past issues (plain context, no special formatting)
    if warnings:
        context_parts.append("\n## Past Related Issues\n")
        for warning in warnings[:3]:
            content = warning.get("content", "")
            context_parts.append(f"- {content}\n")
    
    # Then memories (user's facts, preferences, decisions)
    if memories:
        context_parts.append("\n## User's Memories\n")
        for memory in memories[:5]:  # Max 5 memories
            content = memory.get("content", "")
            mem_type = memory.get("memory_type", "fact")
            context_parts.append(f"- [{mem_type}] {content}\n")
    
    # Knowledge graph context (entities, relationships, topics)
    if graph:
        context_parts.append("\n## Knowledge Graph\n")
        for g in graph[:1]:  # Graph context is already formatted
            content = g.get("content", "")
            context_parts.append(f"{content}\n")
    
    # Finally, relevant past messages
    if messages:
        context_parts.append("\n## Related Past Messages\n")
        for msg in messages[:7]:  # Max 7 messages
            content = msg.get("content", "")
            # Truncate long messages
            if len(content) > 200:
                content = content[:200] + "..."
            context_parts.append(f"- {content}\n")
    
    return "".join(context_parts)
