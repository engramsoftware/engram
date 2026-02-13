"""
Code Improver Interceptor - Enhances coding queries with intelligent context.

Ties together:
- Adaptive Retrieval (decide when to fetch context)
- Code Entity Extraction (parse code in queries)
- Memory Evolution (learn from past solutions)
- Knowledge Graph (relationship-aware context)

Techniques:
- Code-aware memory with compressed summaries
- Zettelkasten-style note linking
- Hybrid RAG with reranking
"""

import logging
from typing import List, Dict, Any, Optional

from addins.addin_interface import InterceptorAddin, AddinType

logger = logging.getLogger(__name__)


class CodeImproverAddin(InterceptorAddin):
    """
    Message interceptor that enhances coding assistance.
    
    Before LLM:
    1. Analyze query complexity
    2. Extract code entities
    3. Retrieve relevant context (adaptive)
    4. Inject optimized context
    
    After LLM:
    1. Extract entities from response
    2. Store in knowledge graph
    3. Evolve related memories
    """
    
    name = "code_improver"
    version = "1.0.0"
    description = "Enhances coding queries with intelligent context retrieval"
    addin_type = AddinType.INTERCEPTOR
    permissions = ["memory", "graph", "search"]
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.adaptive_retrieval = None
        self.code_extractor = None
        self.memory_evolution = None
        self.graph_store = None
        self.memory_store = None
        self.llm_provider = None
    
    async def initialize(self) -> bool:
        """Initialize all components."""
        try:
            # Import components
            from pipeline.adaptive_retrieval import AdaptiveRetrieval
            from knowledge_graph.code_extractor import CodeExtractor
            
            self.adaptive_retrieval = AdaptiveRetrieval()
            self.code_extractor = CodeExtractor()
            
            # These will be set from app context if available
            self._initialized = True
            logger.info("CodeImprover interceptor initialized")
            return True
            
        except Exception as e:
            logger.error(f"CodeImprover initialization failed: {e}")
            return False
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        pass
    
    def set_dependencies(
        self,
        graph_store=None,
        memory_store=None,
        memory_evolution=None,
        llm_provider=None
    ) -> dict:
        """
        Set external dependencies after initialization.
        
        Called by the application to inject shared resources.
        """
        self.graph_store = graph_store
        self.memory_store = memory_store
        self.memory_evolution = memory_evolution
        self.llm_provider = llm_provider
        
        if llm_provider:
            from pipeline.adaptive_retrieval import AdaptiveRetrieval
            from knowledge_graph.code_extractor import CodeExtractor
            self.adaptive_retrieval = AdaptiveRetrieval(llm_provider)
            self.code_extractor = CodeExtractor(llm_provider)
    
    async def before_llm(
        self,
        messages: List[Dict[str, str]],
        context: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        """
        Process messages before sending to LLM.
        
        1. Analyze the last user message
        2. Decide what context to retrieve
        3. Inject relevant context
        """
        if not messages:
            return messages
        
        # Get the last user message
        user_msg = None
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_msg = msg
                break
        
        if not user_msg:
            return messages
        
        query = user_msg.get("content", "")
        user_id = context.get("user_id", "")
        
        # Step 1: Analyze query for retrieval strategy
        if self.adaptive_retrieval:
            plan = self.adaptive_retrieval.analyze_query(query)
            
            if not self.adaptive_retrieval.should_retrieve(plan):
                logger.debug(f"Skipping retrieval: {plan.reasoning}")
                return messages
            
            sources = self.adaptive_retrieval.get_retrieval_sources(plan)
            logger.debug(f"Retrieval plan: {plan.decision.value}, sources: {sources}")
        else:
            # Default to hybrid if no adaptive retrieval
            sources = {"memory": True, "graph": True, "search": True, "web": False}
            plan = None
        
        # Step 2: Extract code entities from query
        code_entities = []
        if self.code_extractor:
            from knowledge_graph.code_extractor import extract_code_blocks
            
            # Extract from code blocks
            code_blocks = extract_code_blocks(query)
            for lang, code in code_blocks:
                entities = self.code_extractor.extract_entities(code, lang)
                code_entities.extend(entities)
            
            # Also check for inline code patterns
            if not code_entities:
                entities = self.code_extractor.extract_entities(query)
                code_entities.extend(entities)
        
        # Step 3: Gather context from various sources
        context_parts = []
        
        # Memory context
        if sources.get("memory") and self.memory_store and self.memory_store.is_available:
            try:
                memories = self.memory_store.search(query, user_id, limit=3)
                if memories:
                    mem_context = self._format_memories(memories)
                    if mem_context:
                        context_parts.append(mem_context)
            except Exception as e:
                logger.debug(f"Memory search failed: {e}")
        
        # Knowledge graph context
        if sources.get("graph") and self.graph_store and self.graph_store.is_available:
            try:
                # Search graph using query + extracted entities
                search_terms = [query]
                for entity in code_entities[:5]:
                    search_terms.append(entity.name)
                
                graph_results = self.graph_store.search_by_query(
                    " ".join(search_terms),
                    user_id,
                    limit=5
                )
                
                if graph_results:
                    graph_context = self.graph_store.format_context_for_prompt(graph_results)
                    if graph_context:
                        context_parts.append(graph_context)
            except Exception as e:
                logger.debug(f"Graph search failed: {e}")
        
        # Evolved memory context (with links)
        if sources.get("memory") and self.memory_evolution:
            try:
                # Get linked memories for deeper context
                if hasattr(self.memory_evolution, 'find_related_memories'):
                    from memory.memory_evolution import MemoryNote
                    temp_note = MemoryNote(
                        id="temp",
                        content=query,
                        user_id=user_id
                    )
                    related = await self.memory_evolution.find_related_memories(temp_note, limit=3)
                    if related:
                        evolved_context = self._format_evolved_memories(related)
                        if evolved_context:
                            context_parts.append(evolved_context)
            except Exception as e:
                logger.debug(f"Evolved memory search failed: {e}")
        
        # Step 4: Inject context into messages
        if context_parts:
            combined_context = "\n\n".join(context_parts)
            
            # Find or create system message
            system_idx = None
            for i, msg in enumerate(messages):
                if msg.get("role") == "system":
                    system_idx = i
                    break
            
            context_injection = f"\n\n[Retrieved Context]\n{combined_context}\n[End Context]"
            
            if system_idx is not None:
                messages[system_idx]["content"] += context_injection
            else:
                # Insert system message at beginning
                messages.insert(0, {
                    "role": "system",
                    "content": f"You are a helpful coding assistant.{context_injection}"
                })
            
            logger.info(f"Injected {len(context_parts)} context sections ({len(combined_context)} chars)")
        
        return messages
    
    async def after_llm(
        self,
        response: str,
        context: Dict[str, Any]
    ) -> str:
        """
        Process LLM response.
        
        1. Extract code entities from response
        2. Store significant entities in knowledge graph
        3. Create/evolve memories if response contains solutions
        """
        if not response:
            return response
        
        user_id = context.get("user_id", "")
        conversation_id = context.get("conversation_id", "")
        
        # Extract entities from response
        if self.code_extractor:
            from knowledge_graph.code_extractor import extract_code_blocks
            
            code_blocks = extract_code_blocks(response)
            all_entities = []
            
            for lang, code in code_blocks:
                entities = self.code_extractor.extract_entities(code, lang)
                all_entities.extend(entities)
            
            # Store significant entities in knowledge graph
            if all_entities and self.graph_store and self.graph_store.is_available:
                await self._store_entities_in_graph(all_entities, user_id, conversation_id)
        
        # Check if response contains a solution worth remembering
        if self._looks_like_solution(response) and self.memory_evolution:
            try:
                # Extract key insight for memory
                summary = self._extract_solution_summary(response)
                if summary:
                    await self.memory_evolution.add_memory(
                        content=summary,
                        user_id=user_id,
                        source_conversation_id=conversation_id
                    )
                    logger.debug(f"Stored solution memory: {summary[:100]}")
            except Exception as e:
                logger.debug(f"Failed to store solution memory: {e}")
        
        return response
    
    def _format_memories(self, memories: List[Any]) -> str:
        """Format memories for context injection."""
        if not memories:
            return ""
        
        lines = ["[User Memories]"]
        for mem in memories[:5]:
            content = mem.content if hasattr(mem, 'content') else str(mem)
            lines.append(f"• {content[:200]}")
        
        return "\n".join(lines)
    
    def _format_evolved_memories(self, notes: List[Any]) -> str:
        """Format evolved memory notes with links."""
        if not notes:
            return ""
        
        lines = ["[Related Knowledge]"]
        for note in notes[:5]:
            content = note.content if hasattr(note, 'content') else str(note)
            context = note.context_description if hasattr(note, 'context_description') else ""
            
            if context:
                lines.append(f"• {context[:150]}")
            else:
                lines.append(f"• {content[:150]}")
            
            # Show links if available
            if hasattr(note, 'linked_memories') and note.linked_memories:
                lines.append(f"  (linked to {len(note.linked_memories)} related items)")
        
        return "\n".join(lines)
    
    async def _store_entities_in_graph(
        self,
        entities: List[Any],
        user_id: str,
        conversation_id: str
    ):
        """Store extracted code entities in knowledge graph."""
        from knowledge_graph.types import GraphNode, GraphRelationship, NodeType, RelationType
        from datetime import datetime
        
        for entity in entities[:10]:  # Limit to prevent spam
            try:
                # Create node
                node = GraphNode(
                    label=NodeType.Entity,
                    name=entity.name,
                    node_type=entity.entity_type.value,
                    properties={
                        "signature": entity.signature[:200] if entity.signature else "",
                        "docstring": entity.docstring[:200] if entity.docstring else "",
                        "source_conversation": conversation_id
                    },
                    created_at=datetime.utcnow(),
                    last_seen=datetime.utcnow()
                )
                
                self.graph_store.add_node(node, user_id)
                
                # Create relationships for dependencies
                for dep in entity.dependencies[:5]:
                    rel = GraphRelationship(
                        from_node=entity.name,
                        to_node=dep,
                        rel_type=RelationType.USES,
                        confidence=0.7,
                        source_conversation_id=conversation_id,
                        created_at=datetime.utcnow()
                    )
                    self.graph_store.add_relationship(rel, user_id)
                    
            except Exception as e:
                logger.debug(f"Failed to store entity {entity.name}: {e}")
    
    def _looks_like_solution(self, response: str) -> bool:
        """Check if response looks like a solution worth remembering."""
        solution_indicators = [
            "```",  # Contains code
            "solution",
            "fix",
            "try this",
            "you can",
            "here's how",
            "the issue is",
            "the problem is",
        ]
        
        response_lower = response.lower()
        matches = sum(1 for ind in solution_indicators if ind in response_lower)
        
        # Needs at least 2 indicators and reasonable length
        return matches >= 2 and len(response) > 200
    
    def _extract_solution_summary(self, response: str, max_length: int = 300) -> str:
        """Extract a summary of the solution for memory storage."""
        # Try to find the key insight
        lines = response.split('\n')
        
        # Look for lines that explain the solution
        key_phrases = ["the issue", "the problem", "the solution", "you need to", "try ", "fix "]
        
        for line in lines:
            line_lower = line.lower().strip()
            if any(phrase in line_lower for phrase in key_phrases):
                if len(line) > 30:  # Meaningful length
                    return line[:max_length]
        
        # Fallback: use first non-code paragraph
        paragraphs = response.split('\n\n')
        for para in paragraphs:
            if not para.strip().startswith('```') and len(para) > 50:
                return para[:max_length]
        
        return ""


# Export
Addin = CodeImproverAddin
