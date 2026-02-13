"""
Outlet pipeline: processes LLM responses for memory formation.

Extracts memories, entities, and relationships from conversations
after the LLM responds.
"""

import logging
import asyncio
from typing import Optional, Dict, Any

from memory.types import Memory, MemoryType, UpdateAction

logger = logging.getLogger(__name__)


# Minimum combined length (user + assistant) to run the outlet pipeline.
# Trivial exchanges like "hi" / "Hello! How can I help?" are skipped.
_MIN_OUTLET_LENGTH = 80


def _is_trivial_exchange(user_query: str, assistant_response: str) -> bool:
    """Return True if the exchange is too short/trivial for extraction.

    Skips greetings, acknowledgements, and very short exchanges that
    would pollute the knowledge graph and waste LLM calls.
    """
    combined = len(user_query.strip()) + len(assistant_response.strip())
    if combined < _MIN_OUTLET_LENGTH:
        return True
    # Skip pure greeting patterns
    _TRIVIAL = {"hi", "hello", "hey", "thanks", "thank you", "ok", "okay",
                "bye", "goodbye", "yes", "no", "sure", "yep", "nope", "cool"}
    if user_query.strip().lower().rstrip("!?.,") in _TRIVIAL:
        return True
    return False


async def process_response(
    user_query: str,
    assistant_response: str,
    user_id: str,
    conversation_id: str,
    memory_extractor=None,
    conflict_resolver=None,
    memory_store=None,
    negative_extractor=None,
    negative_store=None,
    entity_extractor=None,
    graph_store=None,
    llm_provider=None,
    llm_model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Process LLM response to extract and store memories, entities, and relationships.
    
    This is the "outlet" of the pipeline - it processes the response after
    the LLM has generated it.
    
    Steps:
    1. Extract memories (facts, preferences, decisions, experiences)
    2. Resolve conflicts with existing memories
    3. Store new/updated memories
    4. Extract negative knowledge (failures, warnings)
    5. Extract entities and update knowledge graph
    
    Args:
        user_query: User's query/message
        assistant_response: LLM's response
        user_id: User ID
        conversation_id: Conversation ID
        memory_extractor: MemoryExtractor instance
        conflict_resolver: ConflictResolver instance
        memory_store: MemoryStore instance
        negative_extractor: NegativeKnowledgeExtractor instance
        negative_store: NegativeKnowledgeStore instance
        entity_extractor: EntityExtractor instance
        graph_store: Neo4jGraphStore instance
        
    Returns:
        Dict with processing statistics
    """
    stats = {
        "memories_added": 0,
        "memories_updated": 0,
        "memories_deleted": 0,
        "negative_knowledge_added": 0,
        "entities_extracted": 0,
        "relationships_extracted": 0
    }
    
    logger.info(f"Processing response for user {user_id}")

    # Gate: skip trivial exchanges to avoid noise and wasted LLM calls
    if _is_trivial_exchange(user_query, assistant_response):
        logger.debug(f"Outlet skipped: trivial exchange (user={len(user_query)}c, asst={len(assistant_response)}c)")
        return stats
    
    # Task 1: Extract and store memories
    if memory_extractor and memory_store:
        try:
            await _process_memories(
                user_query,
                assistant_response,
                user_id,
                conversation_id,
                memory_extractor,
                conflict_resolver,
                memory_store,
                stats
            )
        except Exception as e:
            logger.error(f"Memory processing failed: {e}")
    
    # Task 2: Extract and store negative knowledge
    if negative_extractor and negative_store:
        try:
            await _process_negative_knowledge(
                user_query,
                assistant_response,
                user_id,
                negative_extractor,
                negative_store,
                stats
            )
        except Exception as e:
            logger.error(f"Negative knowledge processing failed: {e}")
    
    # Task 3: Extract entities and update graph (LLM-based)
    if llm_provider and graph_store:
        try:
            await _process_entities(
                user_query,
                assistant_response,
                user_id,
                conversation_id,
                entity_extractor,
                graph_store,
                stats,
                llm_provider=llm_provider,
                llm_model=llm_model,
            )
        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
    
    logger.info(f"Response processed: {stats}")
    return stats


async def _process_memories(
    user_query: str,
    assistant_response: str,
    user_id: str,
    conversation_id: str,
    memory_extractor,
    conflict_resolver,
    memory_store,
    stats: Dict[str, int]
) -> None:
    """Extract and store memories from conversation."""
    # Extract candidate memories
    memories = await memory_extractor.extract_memories(
        user_query,
        assistant_response,
        user_id,
        conversation_id
    )
    
    if not memories:
        return
    
    logger.debug(f"Extracted {len(memories)} candidate memories")
    
    # Process each memory
    for memory in memories:
        try:
            # Search for similar existing memories
            similar = memory_store.search(
                memory.content,
                user_id,
                limit=5,
                min_confidence=0.7
            )
            
            # Resolve conflicts
            resolution = await conflict_resolver.resolve_conflict(
                memory,
                similar,
                similarity_threshold=0.8
            )
            
            # Apply resolution
            if resolution.action == UpdateAction.ADD:
                success = await memory_store.add(memory)
                if success:
                    stats["memories_added"] += 1
            
            elif resolution.action == UpdateAction.UPDATE:
                if resolution.target_memory_id and resolution.updated_content:
                    success = await memory_store.update(
                        resolution.target_memory_id,
                        resolution.updated_content
                    )
                    if success:
                        stats["memories_updated"] += 1
            
            elif resolution.action == UpdateAction.DELETE:
                if resolution.target_memory_id:
                    success = await memory_store.delete(resolution.target_memory_id)
                    if success:
                        stats["memories_deleted"] += 1
            
            # NONE: do nothing
            
        except Exception as e:
            logger.error(f"Failed to process memory: {e}")


async def _process_negative_knowledge(
    user_query: str,
    assistant_response: str,
    user_id: str,
    negative_extractor,
    negative_store,
    stats: Dict[str, int]
) -> None:
    """Extract and store negative knowledge (failures)."""
    negative_knowledge = await negative_extractor.extract_negative_knowledge(
        user_query,
        assistant_response,
        user_id
    )
    
    if not negative_knowledge:
        return
    
    logger.debug(f"Extracted {len(negative_knowledge)} negative knowledge entries")
    
    for nk in negative_knowledge:
        try:
            success = await negative_store.add(nk)
            if success:
                stats["negative_knowledge_added"] += 1
        except Exception as e:
            logger.error(f"Failed to store negative knowledge: {e}")


# Maximum entities to store per message — prevents a single long response
# from flooding the graph with low-quality nodes.
_MAX_ENTITIES_PER_MESSAGE = 15


async def _process_entities(
    user_query: str,
    assistant_response: str,
    user_id: str,
    conversation_id: str,
    entity_extractor,
    graph_store,
    stats: Dict[str, int],
    llm_provider=None,
    llm_model: Optional[str] = None,
) -> None:
    """Extract entities and relationships via LLM, update knowledge graph.

    Uses the new LLM-based extractor (llm_entity_extractor.py) which produces
    clean, contextually-aware entities and semantic relationship labels.
    Falls back gracefully if no LLM provider is available.
    """
    if not llm_provider:
        logger.debug("Entity extraction skipped: no LLM provider")
        return

    # Import the new LLM-based extractor
    from knowledge_graph.llm_entity_extractor import get_llm_entity_extractor
    from knowledge_graph.types import GraphNode, NodeType

    extractor = get_llm_entity_extractor()

    # Single LLM call extracts both entities and relationships as JSON
    entities, relationships = await extractor.extract(
        user_query=user_query,
        assistant_response=assistant_response,
        provider=llm_provider,
        model=llm_model,
    )

    if not entities and not relationships:
        return

    # Cap entities (LLM prompt already limits to 15, but enforce here too)
    if len(entities) > _MAX_ENTITIES_PER_MESSAGE:
        entities = entities[:_MAX_ENTITIES_PER_MESSAGE]

    logger.debug(f"LLM extracted {len(entities)} entities, {len(relationships)} relationships")

    # Store entities as graph nodes
    for entity in entities:
        try:
            node = GraphNode(
                label=NodeType.ENTITY,
                name=entity.text,
                node_type=entity.type,
                properties={"confidence": entity.confidence, "source": "llm"},
            )
            success = graph_store.add_node(node, user_id)
            if success:
                stats["entities_extracted"] += 1
        except Exception as e:
            logger.error(f"Failed to store entity {entity.text}: {e}")

    # Store relationships with semantic labels (e.g. LIVES_IN, PREFERS)
    for rel in relationships:
        try:
            success = graph_store.add_relationship_dynamic(
                from_node=rel.subject,
                to_node=rel.object,
                rel_label=rel.predicate,
                user_id=user_id,
                confidence=rel.confidence,
                source_conversation_id=conversation_id,
                properties={"source": "llm"},
            )
            if success:
                stats["relationships_extracted"] += 1
        except Exception as e:
            logger.error(f"Failed to store relationship: {e}")
