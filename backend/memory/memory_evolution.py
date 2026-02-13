"""
Memory Evolution System - Zettelkasten-style memory with linking and auto-updates.

Based on A-Mem (NeurIPS 2025) paper concepts:
- Atomic notes with keywords, tags, context
- Automatic linking between related memories
- Memory evolution when new related memories arrive
"""

import logging
from typing import List, Dict, Any, Optional, Set
from datetime import datetime
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class MemoryNote:
    """
    Zettelkasten-style memory note with rich metadata.
    
    Each note is atomic and self-contained with:
    - Original content
    - LLM-generated keywords and tags
    - Contextual description
    - Links to related memories
    """
    id: str
    content: str
    user_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    # LLM-generated enrichments
    keywords: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    context_description: str = ""
    
    # Links to related memory IDs
    linked_memories: Set[str] = field(default_factory=set)
    
    # Evolution tracking
    evolution_count: int = 0
    source_conversation_id: str = ""
    confidence: float = 0.8
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "keywords": self.keywords,
            "tags": self.tags,
            "context_description": self.context_description,
            "linked_memories": list(self.linked_memories),
            "evolution_count": self.evolution_count,
            "source_conversation_id": self.source_conversation_id,
            "confidence": self.confidence
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryNote":
        return cls(
            id=data["id"],
            content=data["content"],
            user_id=data["user_id"],
            created_at=datetime.fromisoformat(data["created_at"]) if isinstance(data["created_at"], str) else data["created_at"],
            updated_at=datetime.fromisoformat(data["updated_at"]) if isinstance(data["updated_at"], str) else data["updated_at"],
            keywords=data.get("keywords", []),
            tags=data.get("tags", []),
            context_description=data.get("context_description", ""),
            linked_memories=set(data.get("linked_memories", [])),
            evolution_count=data.get("evolution_count", 0),
            source_conversation_id=data.get("source_conversation_id", ""),
            confidence=data.get("confidence", 0.8)
        )


class MemoryEvolution:
    """
    Manages memory evolution with Zettelkasten-style linking.
    
    When new memories are added:
    1. Extract keywords/tags/context via LLM
    2. Find similar memories via embedding
    3. Create bidirectional links
    4. Evolve existing memories if new info supplements them
    """
    
    ENRICHMENT_PROMPT = """Analyze this memory content and extract structured metadata.

Content: {content}

Respond in this exact JSON format:
{{
    "keywords": ["keyword1", "keyword2", "keyword3"],
    "tags": ["tag1", "tag2"],
    "context_description": "A rich one-sentence description of what this memory represents and its significance"
}}

Keywords should be specific technical terms, names, or concepts.
Tags should be broad categories like: code, error, solution, preference, fact, decision, tool, library.
Context description should explain WHY this memory matters."""

    EVOLUTION_PROMPT = """Given an existing memory and a new related memory, determine if the existing memory should be updated.

Existing Memory:
- Content: {existing_content}
- Context: {existing_context}
- Keywords: {existing_keywords}

New Related Memory:
- Content: {new_content}
- Context: {new_context}

Should the existing memory's context be updated to incorporate insights from the new memory?
If yes, provide the updated context. If no, explain why.

Respond in JSON:
{{
    "should_update": true/false,
    "updated_context": "new context if updating, empty string if not",
    "new_keywords": ["any", "additional", "keywords"],
    "reason": "brief explanation"
}}"""

    LINK_ANALYSIS_PROMPT = """Analyze if these two memories should be linked.

Memory A:
- Content: {content_a}
- Keywords: {keywords_a}

Memory B:
- Content: {content_b}
- Keywords: {keywords_b}

Should these memories be linked? Consider:
- Do they share concepts, entities, or topics?
- Does one provide context for the other?
- Are they cause/effect or problem/solution pairs?

Respond in JSON:
{{
    "should_link": true/false,
    "relationship_type": "related|supplements|contradicts|solves|causes",
    "reason": "brief explanation"
}}"""

    def __init__(self, memory_store, llm_provider=None, mongo_db=None):
        """
        Initialize memory evolution system.
        
        Args:
            memory_store: Base MemoryStore for vector operations
            llm_provider: LLM provider for enrichment/evolution
            mongo_db: MongoDB for storing enriched notes
        """
        self.memory_store = memory_store
        self.llm_provider = llm_provider
        self.mongo_db = mongo_db
        self.collection_name = "evolved_memories"
    
    async def enrich_memory(self, content: str, user_id: str) -> MemoryNote:
        """
        Create enriched memory note from raw content using LLM.
        
        Args:
            content: Raw memory content
            user_id: User ID
            
        Returns:
            Enriched MemoryNote with keywords, tags, context
        """
        import json
        from bson import ObjectId
        
        note = MemoryNote(
            id=str(ObjectId()),
            content=content,
            user_id=user_id
        )
        
        if not self.llm_provider:
            # Fallback: extract simple keywords
            words = content.lower().split()
            note.keywords = list(set([w for w in words if len(w) > 4]))[:5]
            note.tags = ["general"]
            note.context_description = content[:200]
            return note
        
        try:
            prompt = self.ENRICHMENT_PROMPT.format(content=content)
            response = await self.llm_provider.generate(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300
            )
            
            # Parse JSON response
            result = json.loads(response.content)
            note.keywords = result.get("keywords", [])
            note.tags = result.get("tags", [])
            note.context_description = result.get("context_description", content[:200])
            
        except Exception as e:
            logger.warning(f"Memory enrichment failed: {e}, using fallback")
            words = content.lower().split()
            note.keywords = list(set([w for w in words if len(w) > 4]))[:5]
            note.tags = ["general"]
            note.context_description = content[:200]
        
        return note
    
    async def find_related_memories(
        self,
        note: MemoryNote,
        limit: int = 5,
        min_similarity: float = 0.7
    ) -> List[MemoryNote]:
        """
        Find memories related to the given note using vector similarity.
        
        Args:
            note: Memory note to find relations for
            limit: Maximum related memories to return
            min_similarity: Minimum similarity threshold
            
        Returns:
            List of related MemoryNote objects
        """
        if not self.memory_store or not self.memory_store.is_available:
            return []
        
        try:
            # Search using the note's content + context
            search_text = f"{note.content} {note.context_description}"
            
            # Use ChromaDB for vector search
            results = self.memory_store.chroma_collection.query(
                query_texts=[search_text],
                n_results=limit + 1,  # +1 to exclude self
                where={"user_id": note.user_id},
                include=["documents", "metadatas", "distances"]
            )
            
            if not results or not results['ids'] or not results['ids'][0]:
                return []
            
            related = []
            for i, memory_id in enumerate(results['ids'][0]):
                if memory_id == note.id:
                    continue
                
                # Convert distance to similarity (ChromaDB uses L2 distance)
                distance = results['distances'][0][i] if results['distances'] else 1.0
                similarity = 1 / (1 + distance)
                
                if similarity >= min_similarity:
                    # Try to load full note from MongoDB
                    full_note = await self._load_note(memory_id)
                    if full_note:
                        related.append(full_note)
                    else:
                        # Create basic note from search results
                        related.append(MemoryNote(
                            id=memory_id,
                            content=results['documents'][0][i],
                            user_id=note.user_id,
                            keywords=results['metadatas'][0][i].get('keywords', []),
                            tags=results['metadatas'][0][i].get('tags', [])
                        ))
            
            return related[:limit]
            
        except Exception as e:
            logger.error(f"Failed to find related memories: {e}")
            return []
    
    async def create_links(
        self,
        note: MemoryNote,
        related_notes: List[MemoryNote]
    ) -> List[str]:
        """
        Create bidirectional links between note and related notes.
        Uses LLM to validate meaningful connections.
        
        Args:
            note: New memory note
            related_notes: Potentially related notes
            
        Returns:
            List of linked memory IDs
        """
        import json
        
        linked_ids = []
        
        for related in related_notes:
            should_link = True
            
            # Use LLM to validate link if available
            if self.llm_provider:
                try:
                    prompt = self.LINK_ANALYSIS_PROMPT.format(
                        content_a=note.content[:500],
                        keywords_a=", ".join(note.keywords),
                        content_b=related.content[:500],
                        keywords_b=", ".join(related.keywords)
                    )
                    
                    response = await self.llm_provider.generate(
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=200
                    )
                    
                    result = json.loads(response.content)
                    should_link = result.get("should_link", True)
                    
                except Exception as e:
                    logger.debug(f"Link analysis failed, defaulting to link: {e}")
                    should_link = True
            
            if should_link:
                # Bidirectional linking
                note.linked_memories.add(related.id)
                related.linked_memories.add(note.id)
                linked_ids.append(related.id)
                
                # Update related note in storage
                await self._save_note(related)
        
        return linked_ids
    
    async def evolve_related_memories(
        self,
        note: MemoryNote,
        related_notes: List[MemoryNote]
    ) -> int:
        """
        Evolve existing memories based on new information.
        
        When a new memory is related to existing ones, the existing
        memories may need their context updated.
        
        Args:
            note: New memory note
            related_notes: Related existing notes
            
        Returns:
            Number of memories evolved
        """
        import json
        
        if not self.llm_provider:
            return 0
        
        evolved_count = 0
        
        for related in related_notes:
            try:
                prompt = self.EVOLUTION_PROMPT.format(
                    existing_content=related.content[:500],
                    existing_context=related.context_description,
                    existing_keywords=", ".join(related.keywords),
                    new_content=note.content[:500],
                    new_context=note.context_description
                )
                
                response = await self.llm_provider.generate(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300
                )
                
                result = json.loads(response.content)
                
                if result.get("should_update", False):
                    # Evolve the memory
                    if result.get("updated_context"):
                        related.context_description = result["updated_context"]
                    
                    if result.get("new_keywords"):
                        existing = set(related.keywords)
                        existing.update(result["new_keywords"])
                        related.keywords = list(existing)[:10]
                    
                    related.evolution_count += 1
                    related.updated_at = datetime.utcnow()
                    
                    await self._save_note(related)
                    evolved_count += 1
                    
                    logger.debug(f"Evolved memory {related.id}: {result.get('reason', 'no reason')}")
                    
            except Exception as e:
                logger.debug(f"Evolution check failed for {related.id}: {e}")
        
        return evolved_count
    
    async def add_memory(
        self,
        content: str,
        user_id: str,
        source_conversation_id: str = ""
    ) -> MemoryNote:
        """
        Full pipeline: enrich, link, evolve, and store a new memory.
        
        Args:
            content: Raw memory content
            user_id: User ID
            source_conversation_id: Optional conversation ID
            
        Returns:
            The created MemoryNote
        """
        # 1. Enrich with LLM
        note = await self.enrich_memory(content, user_id)
        note.source_conversation_id = source_conversation_id
        
        # 2. Find related memories
        related = await self.find_related_memories(note)
        
        # 3. Create links
        if related:
            await self.create_links(note, related)
            
            # 4. Evolve related memories
            evolved = await self.evolve_related_memories(note, related)
            logger.info(f"Memory added with {len(related)} links, {evolved} memories evolved")
        
        # 5. Save the new note
        await self._save_note(note)
        
        # 6. Also add to base memory store for vector search
        if self.memory_store and self.memory_store.is_available:
            from memory.types import Memory, MemoryType
            base_memory = Memory(
                id=note.id,
                content=note.content,
                memory_type=MemoryType.FACT,
                user_id=user_id,
                confidence=note.confidence,
                source_conversation_id=source_conversation_id
            )
            await self.memory_store.add(base_memory)
        
        return note
    
    async def get_linked_context(
        self,
        memory_id: str,
        max_depth: int = 2
    ) -> List[MemoryNote]:
        """
        Get all memories linked to a given memory (multi-hop).
        
        Args:
            memory_id: Starting memory ID
            max_depth: Maximum link traversal depth
            
        Returns:
            List of linked memories
        """
        visited = set()
        result = []
        
        async def traverse(mid: str, depth: int) -> dict:
            if depth > max_depth or mid in visited:
                return
            
            visited.add(mid)
            note = await self._load_note(mid)
            
            if note:
                result.append(note)
                for linked_id in note.linked_memories:
                    await traverse(linked_id, depth + 1)
        
        await traverse(memory_id, 0)
        return result
    
    async def _save_note(self, note: MemoryNote) -> bool:
        """Save memory note to MongoDB."""
        if not self.mongo_db:
            return False
        
        try:
            await self.mongo_db[self.collection_name].update_one(
                {"id": note.id},
                {"$set": note.to_dict()},
                upsert=True
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save note {note.id}: {e}")
            return False
    
    async def _load_note(self, memory_id: str) -> Optional[MemoryNote]:
        """Load memory note from MongoDB."""
        if not self.mongo_db:
            return None
        
        try:
            doc = await self.mongo_db[self.collection_name].find_one({"id": memory_id})
            if doc:
                return MemoryNote.from_dict(doc)
            return None
        except Exception as e:
            logger.error(f"Failed to load note {memory_id}: {e}")
            return None


# Singleton instance
_memory_evolution: Optional[MemoryEvolution] = None


def get_memory_evolution(memory_store=None, llm_provider=None, mongo_db=None) -> MemoryEvolution:
    """Get or create the MemoryEvolution singleton."""
    global _memory_evolution
    if _memory_evolution is None:
        _memory_evolution = MemoryEvolution(memory_store, llm_provider, mongo_db)
    return _memory_evolution
