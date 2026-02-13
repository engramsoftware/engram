"""
Knowledge graph module for entity extraction and Neo4j integration.
"""

from knowledge_graph.entity_extractor import (
    EntityExtractor,
    Entity,
    Relationship,
    get_entity_extractor
)
from knowledge_graph.types import (
    NodeType,
    RelationType,
    GraphNode,
    GraphRelationship
)
from knowledge_graph.graph_store import (
    Neo4jGraphStore,
    get_graph_store
)

__all__ = [
    # Entity extraction
    "EntityExtractor",
    "Entity",
    "Relationship",
    "get_entity_extractor",
    # Graph types
    "NodeType",
    "RelationType",
    "GraphNode",
    "GraphRelationship",
    # Graph store
    "Neo4jGraphStore",
    "get_graph_store"
]
