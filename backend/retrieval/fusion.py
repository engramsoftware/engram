"""
Retrieval fusion using Reciprocal Rank Fusion (RRF).

Combines results from multiple retrieval sources (messages, memories,
knowledge graph, negative knowledge) into a unified ranked list.
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def reciprocal_rank_fusion(
    result_lists: List[List[Dict[str, Any]]],
    k: int = 60,
    top_k: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Combine multiple ranked result lists using Reciprocal Rank Fusion.
    
    RRF formula: score = sum(1 / (k + rank)) for each appearance
    
    This gives consistent weight to items that appear in multiple sources,
    while still considering their individual ranks.
    
    Args:
        result_lists: List of result lists from different sources
        k: Constant for RRF (default: 60, from original paper)
        top_k: Return only top K results (optional)
        
    Returns:
        Fused and sorted list of results with fused_score
    """
    if not result_lists:
        return []
    
    scores: Dict[str, float] = {}
    items: Dict[str, Dict[str, Any]] = {}
    
    # Process each result list
    for results in result_lists:
        if not results:
            continue
        
        for rank, item in enumerate(results):
            # Use content hash as key (truncated to 100 chars for efficiency)
            content = item.get("content", "")
            if not content:
                continue
            
            key = content[:100]
            
            # Initialize if first time seeing this item
            if key not in scores:
                scores[key] = 0.0
                items[key] = item.copy()
            
            # Add RRF score: 1 / (k + rank + 1)
            # rank starts at 0, so rank + 1 gives 1-based rank
            rrf_score = 1.0 / (k + rank + 1)
            scores[key] += rrf_score
            
            # If item has a pre-existing score, preserve it
            if "score" in item and "original_score" not in items[key]:
                items[key]["original_score"] = item["score"]
    
    # Sort by fused score (descending)
    sorted_items = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    
    # Apply top_k limit if specified
    if top_k is not None:
        sorted_items = sorted_items[:top_k]
    
    # Format results with fused scores
    fused_results = []
    for key, score in sorted_items:
        result = items[key].copy()
        result["fused_score"] = score
        fused_results.append(result)
    
    logger.debug(f"RRF fused {len(result_lists)} sources into {len(fused_results)} results")
    
    return fused_results


def merge_and_deduplicate(
    results: List[Dict[str, Any]],
    content_key: str = "content",
    threshold: float = 0.9
) -> List[Dict[str, Any]]:
    """
    Merge and deduplicate similar results.
    
    Uses simple string similarity to detect duplicates.
    
    Args:
        results: List of results to deduplicate
        content_key: Key for content field
        threshold: Similarity threshold (0.0-1.0)
        
    Returns:
        Deduplicated results (keeping highest score)
    """
    if not results:
        return []
    
    # Simple deduplication by exact content match
    # For more sophisticated similarity, we'd need embeddings
    seen_content: Dict[str, Dict[str, Any]] = {}
    
    for result in results:
        content = result.get(content_key, "")
        if not content:
            continue
        
        # Normalize content for comparison
        normalized = content.lower().strip()
        
        # Keep result with highest score
        if normalized not in seen_content:
            seen_content[normalized] = result
        else:
            existing_score = seen_content[normalized].get("fused_score", 0.0)
            new_score = result.get("fused_score", 0.0)
            
            if new_score > existing_score:
                seen_content[normalized] = result
    
    deduplicated = list(seen_content.values())
    
    if len(deduplicated) < len(results):
        logger.debug(f"Deduplicated {len(results)} -> {len(deduplicated)} results")
    
    return deduplicated
