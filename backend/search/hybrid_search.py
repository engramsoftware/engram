"""
Hybrid search combining BM25 keyword search + vector semantic search with reranking.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Try to import BM25
try:
    from rank_bm25 import BM25Okapi
    import numpy as np
    HAS_BM25 = True
except ImportError:
    HAS_BM25 = False
    logger.warning("rank_bm25 not available - BM25 search disabled")

# Try to import cross-encoder for reranking
try:
    from sentence_transformers import CrossEncoder
    HAS_CROSS_ENCODER = True
except ImportError:
    HAS_CROSS_ENCODER = False
    # This is optional functionality; don't spam startup logs at warning level.
    logger.info("sentence-transformers CrossEncoder not available - reranking disabled")


# Module-level singleton so the cross-encoder model is loaded once at startup,
# not on every request (model load takes ~1-2s).
_SINGLETON_INSTANCE: Optional["HybridSearcher"] = None


def get_hybrid_searcher() -> "HybridSearcher":
    """Return (or create) the module-level HybridSearcher singleton.

    Avoids reloading the cross-encoder model on every search call.
    """
    global _SINGLETON_INSTANCE
    if _SINGLETON_INSTANCE is None:
        _SINGLETON_INSTANCE = HybridSearcher()
    return _SINGLETON_INSTANCE


class HybridSearcher:
    """Combines BM25 keyword search + vector search + reranking for better recall."""
    
    def __init__(self, reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.reranker = None
        if HAS_CROSS_ENCODER:
            try:
                self.reranker = CrossEncoder(reranker_model)
                logger.info(f"Loaded reranker: {reranker_model}")
            except Exception as e:
                logger.warning(f"Failed to load reranker: {e}")
    
    def tokenize(self, text: str) -> List[str]:
        """Simple tokenization for BM25."""
        return text.lower().split()
    
    def bm25_search(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 20
    ) -> List[Tuple[float, Dict[str, Any]]]:
        """
        BM25 keyword search over documents.
        
        Args:
            query: Search query
            documents: List of dicts with 'content' field
            top_k: Number of results to return
            
        Returns:
            List of (score, document) tuples
        """
        if not documents or not HAS_BM25:
            return []
        
        # Tokenize all documents
        tokenized_docs = [self.tokenize(doc.get('content', '')) for doc in documents]
        
        # Build BM25 index
        bm25 = BM25Okapi(tokenized_docs)
        
        # Search
        tokenized_query = self.tokenize(query)
        scores = bm25.get_scores(tokenized_query)
        
        # Get top-k
        top_indices = np.argsort(scores)[::-1][:top_k]
        results = [(scores[i], documents[i]) for i in top_indices if scores[i] > 0]
        
        return results
    
    def reciprocal_rank_fusion(
        self,
        keyword_results: List[Tuple[float, Dict[str, Any]]],
        vector_results: List[Tuple[float, Dict[str, Any]]],
        k: int = 60
    ) -> List[Dict[str, Any]]:
        """
        Combine keyword and vector results using Reciprocal Rank Fusion.
        
        RRF score = sum(1 / (k + rank)) for each result list
        
        Args:
            keyword_results: BM25 results as (score, doc) tuples
            vector_results: Vector results as (score, doc) tuples
            k: Constant for RRF (default 60)
            
        Returns:
            Combined and sorted results
        """
        # Build document ID -> RRF score mapping
        rrf_scores: Dict[str, float] = {}
        doc_map: Dict[str, Dict[str, Any]] = {}
        
        # Add keyword results
        for rank, (score, doc) in enumerate(keyword_results, start=1):
            doc_id = str(doc.get('id', id(doc)))
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + 1 / (k + rank)
            doc_map[doc_id] = doc
        
        # Add vector results
        for rank, (score, doc) in enumerate(vector_results, start=1):
            doc_id = str(doc.get('id', id(doc)))
            rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + 1 / (k + rank)
            doc_map[doc_id] = doc
        
        # Sort by RRF score
        sorted_ids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)
        
        # Return documents with RRF scores
        results = []
        for doc_id in sorted_ids:
            doc = doc_map[doc_id].copy()
            doc['rrf_score'] = rrf_scores[doc_id]
            results.append(doc)
        
        return results
    
    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Rerank documents using cross-encoder for better relevance.
        
        Args:
            query: Search query
            documents: Documents to rerank (with 'content' field)
            top_k: Number of top results to return
            
        Returns:
            Reranked documents with 'rerank_score' field
        """
        if not self.reranker or not documents:
            return documents[:top_k]
        
        try:
            # Prepare pairs for cross-encoder
            pairs = [(query, doc.get('content', '')) for doc in documents]
            
            # Get relevance scores
            scores = self.reranker.predict(pairs)
            
            # Sort by score
            scored_docs = list(zip(scores, documents))
            scored_docs.sort(key=lambda x: x[0], reverse=True)
            
            # Add scores to documents
            results = []
            for score, doc in scored_docs[:top_k]:
                doc = doc.copy()
                doc['rerank_score'] = float(score)
                results.append(doc)
            
            return results
        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            return documents[:top_k]
    
    def hybrid_search(
        self,
        query: str,
        vector_results: List[Dict[str, Any]],
        all_documents: Optional[List[Dict[str, Any]]] = None,
        top_k: int = 5,
        use_reranking: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Full hybrid search pipeline: BM25 + Vector + RRF + Reranking.
        
        Args:
            query: Search query
            vector_results: Results from vector search (with 'content' field)
            all_documents: All available documents for BM25 (optional, uses vector_results if None)
            top_k: Final number of results
            use_reranking: Whether to apply cross-encoder reranking
            
        Returns:
            Top-k most relevant documents
        """
        # Use vector results as document pool if no separate pool provided
        if all_documents is None:
            all_documents = vector_results
        
        # 1. BM25 keyword search
        keyword_results = self.bm25_search(query, all_documents, top_k=20)
        
        # 2. Convert vector results to (score, doc) format
        vector_tuples = [(doc.get('distance', 0), doc) for doc in vector_results]
        
        # 3. Reciprocal Rank Fusion
        fused_results = self.reciprocal_rank_fusion(keyword_results, vector_tuples)
        
        # 4. Rerank top candidates
        if use_reranking and self.reranker:
            # Get more candidates for reranking
            candidates = fused_results[:min(20, len(fused_results))]
            final_results = self.rerank(query, candidates, top_k=top_k)
        else:
            final_results = fused_results[:top_k]
        
        return final_results
