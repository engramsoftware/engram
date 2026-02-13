"""
Negative knowledge storage with priority boosting for retrieval.

Stores failures in MongoDB + ChromaDB for semantic search,
with boosted scores to prevent repeated mistakes.
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from bson import ObjectId

from memory.types import NegativeKnowledge

logger = logging.getLogger(__name__)

# ChromaDB imports with fallback
CHROMADB_AVAILABLE = False
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    logger.warning("ChromaDB not available for negative knowledge store")


class NegativeKnowledgeStore:
    """
    Storage for negative knowledge (failures) with semantic search.
    
    Uses dual storage:
    - ChromaDB for vector search
    - MongoDB for full metadata
    
    Methods:
        add: Add negative knowledge
        search: Search with priority boosting
        get_by_entities: Get failures related to specific entities
    """
    
    CHROMA_COLLECTION = "negative_knowledge"
    MONGO_COLLECTION = "negative_knowledge"
    PRIORITY_BOOST = 1.5  # Score multiplier for negative knowledge
    MIN_SIMILARITY = 0.55  # Minimum cosine similarity to include a warning
    
    def __init__(self, chroma_path: str = None, mongo_db = None):
        """
        Initialize negative knowledge store.
        
        Args:
            chroma_path: Path for ChromaDB (defaults to backend/data/chroma_negative)
            mongo_db: MongoDB database instance
        """
        self.chroma_client = None
        self.chroma_collection = None
        self.mongo_db = mongo_db
        self._initialized = False
        
        if not CHROMADB_AVAILABLE:
            logger.warning("Negative knowledge store: ChromaDB not available")
            return
        
        self._init_chroma(chroma_path)
    
    def _init_chroma(self, path: Optional[str]) -> None:
        """Initialize ChromaDB for negative knowledge."""
        try:
            from pathlib import Path
            
            if path is None:
                from config import CHROMA_NEGATIVE_DIR
                path = CHROMA_NEGATIVE_DIR
            else:
                path = Path(path)
            
            path.mkdir(parents=True, exist_ok=True)
            
            self.chroma_client = chromadb.PersistentClient(
                path=str(path),
                settings=Settings(anonymized_telemetry=False)
            )
            
            self.chroma_collection = self.chroma_client.get_or_create_collection(
                name=self.CHROMA_COLLECTION,
                metadata={"hnsw:space": "cosine"}
            )
            
            self._initialized = True
            logger.info(f"Negative knowledge store initialized with {self.chroma_collection.count()} entries")
            
        except Exception as e:
            logger.error(f"Failed to initialize negative knowledge store: {e}")
            self._initialized = False
    
    @property
    def is_available(self) -> bool:
        """Check if store is ready."""
        return self._initialized and self.chroma_collection is not None and self.mongo_db is not None
    
    async def add(self, knowledge: NegativeKnowledge) -> bool:
        """
        Add negative knowledge to store.
        
        Args:
            knowledge: NegativeKnowledge object to add
            
        Returns:
            True if successful
        """
        if not self.is_available:
            return False
        
        try:
            # Insert into MongoDB
            mongo_doc = {
                "userId": knowledge.user_id,
                "whatFailed": knowledge.what_failed,
                "whyFailed": knowledge.why_failed,
                "solutionFound": knowledge.solution_found,
                "context": knowledge.context,
                "createdAt": knowledge.created_at,
                "relatedEntities": knowledge.related_entities
            }
            
            result = await self.mongo_db[self.MONGO_COLLECTION].insert_one(mongo_doc)
            knowledge_id = str(result.inserted_id)
            
            # Add to ChromaDB
            # Combine fields for better semantic search
            search_text = (
                f"Failed: {knowledge.what_failed} "
                f"Reason: {knowledge.why_failed} "
                f"Solution: {knowledge.solution_found or 'None found'} "
                f"Context: {knowledge.context}"
            )
            
            self.chroma_collection.upsert(
                ids=[knowledge_id],
                documents=[search_text],
                metadatas=[{
                    "user_id": knowledge.user_id,
                    "what_failed": knowledge.what_failed,
                    "why_failed": knowledge.why_failed,
                    "related_entities": ",".join(knowledge.related_entities)
                }]
            )
            
            logger.debug(f"Added negative knowledge: {knowledge.what_failed}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add negative knowledge: {e}")
            return False
    
    def search(
        self,
        query: str,
        user_id: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Search for negative knowledge with priority boosting.
        
        Returns results formatted as warnings with boosted scores.
        
        Args:
            query: Search query
            user_id: User ID filter
            limit: Max results
            
        Returns:
            List of dictionaries with content and boosted scores
        """
        if not self.is_available or not query.strip():
            return []
        
        try:
            results = self.chroma_collection.query(
                query_texts=[query],
                n_results=limit,
                where={"user_id": user_id},
                include=["documents", "metadatas", "distances"]
            )
            
            if not results or not results['ids'] or not results['ids'][0]:
                return []
            
            warnings = []
            for i, doc_id in enumerate(results['ids'][0]):
                metadata = results['metadatas'][0][i]
                distance = results['distances'][0][i]
                
                # Convert distance to similarity score (cosine: 0=identical, 2=opposite)
                similarity = max(0, 1 - (distance / 2))
                
                # Skip low-relevance results to avoid injecting irrelevant warnings
                if similarity < self.MIN_SIMILARITY:
                    continue
                
                # Apply priority boost
                boosted_score = similarity * self.PRIORITY_BOOST
                
                # Format as warning message
                what_failed = metadata.get('what_failed', 'Unknown')
                why_failed = metadata.get('why_failed', 'Unknown reason')
                
                warning_content = (
                    f"⚠️ Warning: Previously failed approach detected!\n"
                    f"What failed: {what_failed}\n"
                    f"Why: {why_failed}\n"
                    f"Consider alternative approaches to avoid this issue."
                )
                
                warnings.append({
                    "content": warning_content,
                    "score": boosted_score,
                    "type": "negative_knowledge",
                    "what_failed": what_failed,
                    "why_failed": why_failed
                })
            
            logger.debug(f"Found {len(warnings)} negative knowledge warnings")
            return warnings
            
        except Exception as e:
            logger.error(f"Negative knowledge search failed: {e}")
            return []

    def search_raw(
        self,
        query: str,
        user_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Return raw negative knowledge documents for hybrid BM25+vector search.

        Unlike search(), this returns plain documents with 'content', 'distance',
        and metadata fields — suitable for feeding into HybridSearcher which
        applies its own BM25 + RRF + cross-encoder reranking.

        Args:
            query: Search query.
            user_id: User ID filter.
            limit: Max candidates to return.

        Returns:
            List of dicts with content, distance, what_failed, why_failed, id.
        """
        if not self.is_available or not query.strip():
            return []

        try:
            results = self.chroma_collection.query(
                query_texts=[query],
                n_results=limit,
                where={"user_id": user_id},
                include=["documents", "metadatas", "distances"]
            )

            if not results or not results['ids'] or not results['ids'][0]:
                return []

            docs = []
            for i, doc_id in enumerate(results['ids'][0]):
                metadata = results['metadatas'][0][i]
                distance = results['distances'][0][i]
                what_failed = metadata.get('what_failed', '')
                why_failed = metadata.get('why_failed', '')
                # Plain content for BM25 tokenization
                content = f"{what_failed}. {why_failed}"

                docs.append({
                    "id": doc_id,
                    "content": content,
                    "distance": distance,
                    "what_failed": what_failed,
                    "why_failed": why_failed,
                })

            return docs

        except Exception as e:
            logger.error(f"Negative knowledge search_raw failed: {e}")
            return []

    async def get_by_entities(
        self,
        entities: List[str],
        user_id: str,
        limit: int = 10
    ) -> List[NegativeKnowledge]:
        """
        Get negative knowledge related to specific entities.
        
        Args:
            entities: List of entity names
            user_id: User ID filter
            limit: Max results
            
        Returns:
            List of NegativeKnowledge objects
        """
        if not self.is_available or not entities:
            return []
        
        try:
            # Query MongoDB for exact entity matches
            cursor = self.mongo_db[self.MONGO_COLLECTION].find(
                {
                    "userId": user_id,
                    "relatedEntities": {"$in": entities}
                }
            ).limit(limit)
            
            knowledge_list = []
            async for doc in cursor:
                knowledge = NegativeKnowledge(
                    id=str(doc["_id"]),
                    what_failed=doc["whatFailed"],
                    why_failed=doc["whyFailed"],
                    solution_found=doc.get("solutionFound"),
                    context=doc.get("context", ""),
                    user_id=doc["userId"],
                    created_at=doc["createdAt"],
                    related_entities=doc.get("relatedEntities", [])
                )
                knowledge_list.append(knowledge)
            
            return knowledge_list
            
        except Exception as e:
            logger.error(f"Failed to get negative knowledge by entities: {e}")
            return []
    
    def get_count(self, user_id: Optional[str] = None) -> int:
        """
        Get count of negative knowledge entries.
        
        Args:
            user_id: Optional user filter
            
        Returns:
            Count of entries
        """
        if not self.is_available:
            return 0
        
        if user_id:
            results = self.chroma_collection.query(
                query_texts=[""],
                n_results=1,
                where={"user_id": user_id}
            )
            return len(results['ids'][0]) if results and results['ids'] else 0
        else:
            return self.chroma_collection.count()


# Singleton instance
_negative_store: Optional[NegativeKnowledgeStore] = None


def get_negative_store(mongo_db=None) -> NegativeKnowledgeStore:
    """
    Get or create singleton NegativeKnowledgeStore.
    
    Args:
        mongo_db: MongoDB database (required on first call)
        
    Returns:
        NegativeKnowledgeStore instance
    """
    global _negative_store
    if _negative_store is None:
        _negative_store = NegativeKnowledgeStore(mongo_db=mongo_db)
    elif mongo_db is not None and _negative_store.mongo_db is None:
        _negative_store.mongo_db = mongo_db
    return _negative_store
