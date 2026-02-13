"""
Neo4j knowledge graph store with temporal support.

This module provides persistent storage for entities and relationships
in a Neo4j graph database with temporal awareness.

Features:
- Entity and relationship storage
- Temporal tracking (created_at, last_seen)
- Efficient queries for related entities
- User isolation (each user has their own graph)
"""

import logging
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime

from knowledge_graph.types import GraphNode, GraphRelationship, NodeType, RelationType

logger = logging.getLogger(__name__)

# Neo4j imports with graceful fallback
NEO4J_AVAILABLE = False
try:
    from neo4j import GraphDatabase, Driver
    from neo4j.exceptions import ServiceUnavailable, AuthError
    NEO4J_AVAILABLE = True
    logger.info("Neo4j driver available")
except ImportError:
    logger.warning("Neo4j driver not available - knowledge graph disabled")


class Neo4jGraphStore:
    """
    Neo4j graph database store for knowledge graph.
    
    Stores entities and relationships with temporal tracking and user isolation.
    
    Methods:
        add_node: Add or update a node
        add_relationship: Add a relationship between nodes
        get_node: Get a node by name
        get_related_nodes: Get all nodes related to a given node
        search_nodes: Search for nodes by type/name
    """
    
    def __init__(
        self,
        uri: str,
        username: str,
        password: str,
        database: str = "neo4j"
    ):
        """
        Initialize Neo4j connection.
        
        Args:
            uri: Neo4j connection URI (bolt://localhost:7687 or neo4j+s://... for Aura)
            username: Neo4j username
            password: Neo4j password
            database: Database name (default: neo4j)
        """
        self.uri = uri
        self.username = username
        self.database = database
        self.driver: Optional[Driver] = None
        self._initialized = False
        
        if not NEO4J_AVAILABLE:
            logger.warning("Neo4j driver not available")
            return
        
        # Initialize driver
        self._init_driver(password)
    
    def _init_driver(self, password: str) -> None:
        """Initialize Neo4j driver and test connection."""
        import os
        import time

        # Fix SSL certificate issues on Windows by using certifi
        try:
            import certifi
            os.environ.setdefault('SSL_CERT_FILE', certifi.where())
            os.environ.setdefault('REQUESTS_CA_BUNDLE', certifi.where())
        except ImportError:
            pass

        try:
            # For Aura (neo4j+s://), we need proper SSL handling
            # The driver handles SSL automatically for neo4j+s:// URIs
            self.driver = GraphDatabase.driver(
                self.uri,
                auth=(self.username, password)
            )

            # Test connection with retry for newly provisioned instances
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    self.driver.verify_connectivity()
                    break
                except ServiceUnavailable as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Neo4j connection attempt {attempt + 1} failed, retrying...")
                        time.sleep(2)
                    else:
                        raise

            self._initialized = True
            logger.info(f"Connected to Neo4j at {self.uri}")

            # Create indexes for performance
            self._create_indexes()

        except AuthError as e:
            logger.error(f"Neo4j authentication failed: {e}")
            self.driver = None
        except ServiceUnavailable as e:
            logger.error(f"Neo4j service unavailable: {e}")
            self.driver = None
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            self.driver = None
    
    def _create_indexes(self) -> None:
        """Create indexes for efficient queries."""
        if not self.is_available:
            return

        try:
            with self.driver.session(database=self.database) as session:
                # Index on entity name + user_id for fast lookups (Neo4j 5.x syntax)
                session.run(
                    """
                    CREATE INDEX node_name_user IF NOT EXISTS
                    FOR (n:Entity) ON (n.name, n.user_id)
                    """
                )

                # Index on last_seen for temporal queries
                session.run(
                    """
                    CREATE INDEX node_last_seen IF NOT EXISTS
                    FOR (n:Entity) ON (n.last_seen)
                    """
                )
                
                # Index on node_type for filtered searches
                session.run(
                    """
                    CREATE INDEX node_type IF NOT EXISTS
                    FOR (n:Entity) ON (n.node_type)
                    """
                )
                
                # Fulltext index for text search across entity names and properties
                try:
                    session.run(
                        """
                        CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS
                        FOR (n:Entity) ON EACH [n.name, n.node_type]
                        """
                    )
                except Exception:
                    # Fulltext indexes may not be available on all Neo4j editions
                    logger.debug("Fulltext index not created (may not be supported)")

                logger.debug("Neo4j indexes created")

        except Exception as e:
            logger.warning(f"Failed to create indexes: {e}")
    
    @property
    def is_available(self) -> bool:
        """Check if Neo4j is connected and ready."""
        return self._initialized and self.driver is not None
    
    def close(self) -> None:
        """Close the Neo4j driver connection."""
        if self.driver:
            self.driver.close()
            logger.info("Neo4j connection closed")
    
    def add_node(
        self,
        node: GraphNode,
        user_id: str
    ) -> bool:
        """
        Add or update a node in the graph.
        
        If a node with the same name and user_id exists, updates last_seen.
        Otherwise, creates a new node.
        
        Args:
            node: GraphNode to add
            user_id: User ID for isolation
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available:
            return False

        import json
        try:
            with self.driver.session(database=self.database) as session:
                # MERGE: create if doesn't exist, update if it does
                # Serialize properties to JSON string (Neo4j doesn't allow nested maps)
                properties_json = json.dumps(node.properties) if node.properties else "{}"
                result = session.run(
                    f"""
                    MERGE (n:{node.label.value} {{name: $name, user_id: $user_id}})
                    ON CREATE SET
                        n.node_type = $node_type,
                        n.created_at = datetime($created_at),
                        n.last_seen = datetime($last_seen),
                        n.properties = $properties
                    ON MATCH SET
                        n.last_seen = datetime($last_seen)
                    RETURN n
                    """,
                    name=node.name,
                    user_id=user_id,
                    node_type=node.node_type,
                    created_at=node.created_at.isoformat(),
                    last_seen=node.last_seen.isoformat(),
                    properties=properties_json
                )
                
                record = result.single()
                if record:
                    logger.debug(f"Added/updated node: {node.name}")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Failed to add node {node.name}: {e}")
            return False
    
    def add_relationship(
        self,
        relationship: GraphRelationship,
        user_id: str
    ) -> bool:
        """
        Add a relationship between two nodes.
        
        Creates nodes if they don't exist, then creates the relationship.
        
        Args:
            relationship: GraphRelationship to add
            user_id: User ID for isolation
            
        Returns:
            True if successful, False otherwise
        """
        if not self.is_available:
            return False

        import json
        try:
            with self.driver.session(database=self.database) as session:
                # MERGE nodes and create relationship
                # Serialize properties to JSON string
                properties_json = json.dumps(relationship.properties) if relationship.properties else "{}"
                result = session.run(
                    f"""
                    MERGE (from:Entity {{name: $from_node, user_id: $user_id}})
                    MERGE (to:Entity {{name: $to_node, user_id: $user_id}})
                    MERGE (from)-[r:{relationship.rel_type.value}]->(to)
                    ON CREATE SET
                        r.confidence = $confidence,
                        r.created_at = datetime($created_at),
                        r.source_conversation_id = $source_conversation_id,
                        r.properties = $properties
                    RETURN r
                    """,
                    from_node=relationship.from_node,
                    to_node=relationship.to_node,
                    user_id=user_id,
                    confidence=relationship.confidence,
                    created_at=relationship.created_at.isoformat(),
                    source_conversation_id=relationship.source_conversation_id,
                    properties=properties_json
                )
                
                record = result.single()
                if record:
                    logger.debug(
                        f"Added relationship: {relationship.from_node} "
                        f"-> {relationship.rel_type.value} -> {relationship.to_node}"
                    )
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Failed to add relationship: {e}")
            return False
    
    def add_relationship_dynamic(
        self,
        from_node: str,
        to_node: str,
        rel_label: str,
        user_id: str,
        confidence: float = 0.8,
        source_conversation_id: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Add a relationship with an LLM-generated semantic label.

        Unlike add_relationship() which requires a RelationType enum,
        this method accepts any string label (e.g. "lives_in", "prefers",
        "works_at") and writes it directly as the Neo4j relationship type.

        Args:
            from_node: Source entity name.
            to_node: Target entity name.
            rel_label: Semantic relationship label (UPPER_SNAKE_CASE).
            user_id: User ID for isolation.
            confidence: Confidence score (0.0-1.0).
            source_conversation_id: Conversation where this was extracted.
            properties: Additional properties dict.

        Returns:
            True if successful, False otherwise.
        """
        if not self.is_available:
            return False

        import json
        import re as _re

        # Sanitise label: Neo4j relationship types must be alphanumeric + underscore
        safe_label = _re.sub(r"[^A-Za-z0-9_]", "_", rel_label).upper()
        if not safe_label or safe_label[0].isdigit():
            safe_label = "RELATES_TO"

        properties_json = json.dumps(properties) if properties else "{}"
        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(
                    f"""
                    MERGE (from:Entity {{name: $from_node, user_id: $user_id}})
                    MERGE (to:Entity {{name: $to_node, user_id: $user_id}})
                    MERGE (from)-[r:{safe_label}]->(to)
                    ON CREATE SET
                        r.confidence = $confidence,
                        r.created_at = datetime($created_at),
                        r.source_conversation_id = $source_conversation_id,
                        r.properties = $properties,
                        r.is_active = true
                    RETURN r
                    """,
                    from_node=from_node,
                    to_node=to_node,
                    user_id=user_id,
                    confidence=confidence,
                    created_at=datetime.utcnow().isoformat(),
                    source_conversation_id=source_conversation_id,
                    properties=properties_json,
                )
                record = result.single()
                if record:
                    logger.debug(f"Added dynamic rel: {from_node} -[{safe_label}]-> {to_node}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Failed to add dynamic relationship: {e}")
            return False

    def invalidate_relationships(
        self,
        entity_name: str,
        rel_label: str,
        user_id: str,
    ) -> int:
        """Mark existing relationships as inactive (temporal conflict resolution).

        When new information contradicts an old relationship, we mark the old
        one as is_active=false rather than deleting it, preserving history.

        Args:
            entity_name: Entity whose outgoing relationships to invalidate.
            rel_label: Relationship type to invalidate (UPPER_SNAKE_CASE).
            user_id: User ID for isolation.

        Returns:
            Number of relationships invalidated.
        """
        if not self.is_available:
            return 0

        import re as _re
        safe_label = _re.sub(r"[^A-Za-z0-9_]", "_", rel_label).upper()
        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(
                    f"""
                    MATCH (from:Entity {{name: $name, user_id: $user_id}})-[r:{safe_label}]->()
                    WHERE r.is_active IS NULL OR r.is_active = true
                    SET r.is_active = false, r.invalidated_at = datetime($now)
                    RETURN count(r) AS cnt
                    """,
                    name=entity_name,
                    user_id=user_id,
                    now=datetime.utcnow().isoformat(),
                )
                cnt = result.single()["cnt"]
                if cnt:
                    logger.debug(f"Invalidated {cnt} {safe_label} rels from {entity_name}")
                return cnt
        except Exception as e:
            logger.error(f"Failed to invalidate relationships: {e}")
            return 0

    def get_node(
        self,
        name: str,
        user_id: str
    ) -> Optional[GraphNode]:
        """
        Get a node by name.
        
        Args:
            name: Node name
            user_id: User ID for isolation
            
        Returns:
            GraphNode if found, None otherwise
        """
        if not self.is_available:
            return None
        
        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(
                    """
                    MATCH (n {name: $name, user_id: $user_id})
                    RETURN n, labels(n) as labels
                    """,
                    name=name,
                    user_id=user_id
                )
                
                record = result.single()
                if not record:
                    return None
                
                node_data = dict(record["n"])
                label = record["labels"][0] if record["labels"] else "Entity"
                
                return GraphNode(
                    label=NodeType(label),
                    name=node_data["name"],
                    node_type=node_data.get("node_type", ""),
                    properties=node_data.get("properties", {}),
                    created_at=datetime.fromisoformat(node_data.get("created_at", datetime.utcnow().isoformat())),
                    last_seen=datetime.fromisoformat(node_data.get("last_seen", datetime.utcnow().isoformat()))
                )
                
        except Exception as e:
            logger.error(f"Failed to get node {name}: {e}")
            return None
    
    def get_related_nodes(
        self,
        name: str,
        user_id: str,
        max_depth: int = 2
    ) -> List[Tuple[GraphNode, str]]:
        """
        Get all nodes related to a given node.
        
        Args:
            name: Source node name
            user_id: User ID for isolation
            max_depth: Maximum relationship depth to traverse (default: 2)
            
        Returns:
            List of (GraphNode, relationship_type) tuples
        """
        if not self.is_available:
            return []
        
        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(
                    f"""
                    MATCH (start {{name: $name, user_id: $user_id}})
                    MATCH (start)-[r*1..{max_depth}]-(related)
                    WHERE related.user_id = $user_id
                    RETURN DISTINCT related, type(r[0]) as rel_type, labels(related) as labels
                    LIMIT 50
                    """,
                    name=name,
                    user_id=user_id
                )
                
                nodes = []
                for record in result:
                    node_data = dict(record["related"])
                    label = record["labels"][0] if record["labels"] else "Entity"
                    rel_type = record["rel_type"]
                    
                    node = GraphNode(
                        label=NodeType(label),
                        name=node_data["name"],
                        node_type=node_data.get("node_type", ""),
                        properties=node_data.get("properties", {})
                    )
                    nodes.append((node, rel_type))
                
                return nodes
                
        except Exception as e:
            logger.error(f"Failed to get related nodes for {name}: {e}")
            return []
    
    def search_nodes(
        self,
        user_id: str,
        node_type: Optional[str] = None,
        name_contains: Optional[str] = None,
        limit: int = 20
    ) -> List[GraphNode]:
        """
        Search for nodes by type and/or name.
        
        Args:
            user_id: User ID for isolation
            node_type: Filter by node type (optional)
            name_contains: Filter by name substring (optional)
            limit: Maximum results to return
            
        Returns:
            List of matching GraphNode objects
        """
        if not self.is_available:
            return []
        
        try:
            query = "MATCH (n {user_id: $user_id})"
            params = {"user_id": user_id, "limit": limit}
            
            conditions = []
            if node_type:
                conditions.append("n.node_type = $node_type")
                params["node_type"] = node_type
            
            if name_contains:
                conditions.append("toLower(n.name) CONTAINS toLower($name_contains)")
                params["name_contains"] = name_contains
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            
            query += " RETURN n, labels(n) as labels ORDER BY n.last_seen DESC LIMIT $limit"
            
            with self.driver.session(database=self.database) as session:
                result = session.run(query, **params)
                
                nodes = []
                for record in result:
                    node_data = dict(record["n"])
                    label = record["labels"][0] if record["labels"] else "Entity"
                    
                    node = GraphNode(
                        label=NodeType(label),
                        name=node_data["name"],
                        node_type=node_data.get("node_type", ""),
                        properties=node_data.get("properties", {})
                    )
                    nodes.append(node)
                
                return nodes
                
        except Exception as e:
            logger.error(f"Failed to search nodes: {e}")
            return []

    def _extract_query_entities(self, query: str) -> List[str]:
        """Extract entity names from a user query using GLiNER.

        Uses the same GLiNER model as the outlet pipeline to identify
        named entities in the query, giving much better graph entry
        points than simple keyword splitting.

        Args:
            query: The user's question text.

        Returns:
            List of extracted entity name strings (lowercased).
        """
        try:
            from knowledge_graph.entity_extractor import get_entity_extractor
            extractor = get_entity_extractor()
            if extractor and extractor.gliner_model:
                entities = extractor.extract_entities(query)
                return [e.text.lower() for e in entities if is_valid_entity(e.text)]
        except Exception as e:
            logger.debug(f"GLiNER query entity extraction failed: {e}")
        return []

    def search_by_query(
        self,
        query: str,
        user_id: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        GraphRAG-style search: multi-hop traversal with relationship-aware context.

        Uses proper graph traversal patterns:
        1. Entity linking - GLiNER extraction + keyword fallback for entry points
        2. Multi-hop traversal - explore 2 hops for connected context
        3. Path extraction - capture relationship chains for reasoning
        4. Relevance scoring - temporal decay + relationship strength
        5. Community detection - group co-occurring entities into topic clusters

        Args:
            query: User's query text
            user_id: User ID for isolation
            limit: Maximum results to return

        Returns:
            List of context dicts with entities, paths, and subgraph info
        """
        if not self.is_available:
            return []

        try:
            # STEP 0: Entity linking via GLiNER (preferred) + keyword fallback
            # GLiNER extracts real entity names ("Python", "FastAPI", "Neo4j")
            # instead of just splitting on whitespace.
            entity_names = self._extract_query_entities(query)

            # Keyword fallback for terms GLiNER might miss
            stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                        'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                        'would', 'could', 'should', 'may', 'might', 'must', 'can',
                        'this', 'that', 'these', 'those', 'i', 'you', 'he', 'she',
                        'it', 'we', 'they', 'what', 'which', 'who', 'whom', 'how',
                        'when', 'where', 'why', 'if', 'then', 'else', 'and', 'or',
                        'but', 'not', 'no', 'yes', 'all', 'any', 'some', 'my', 'your',
                        'his', 'her', 'its', 'our', 'their', 'with', 'about', 'into',
                        'from', 'for', 'on', 'in', 'at', 'to', 'of', 'by', 'as'}
            keywords = [w.lower().strip() for w in query.split()
                       if len(w) > 2 and w.lower().strip() not in stopwords]
            # Merge: entity names first (higher quality), then keywords
            words = list(dict.fromkeys(entity_names + keywords))

            context_results = []

            with self.driver.session(database=self.database) as session:
                # STEP 1: Find entry points — exact entity name match first,
                # then keyword CONTAINS fallback. Temporal decay weights recent
                # entities exponentially higher (1d=1.0, 7d=0.7, 30d=0.4, older=0.2).
                entry_points = session.run(
                    """
                    MATCH (n {user_id: $user_id})
                    WHERE n.node_type IS NOT NULL
                    WITH n,
                         CASE
                             WHEN toLower(n.name) IN $entity_names THEN 3.0
                             ELSE 0.0
                         END as exact_score,
                         [word IN $words WHERE toLower(n.name) CONTAINS word | word] as matches
                    WHERE exact_score > 0 OR size(matches) > 0
                    WITH n, (exact_score + toFloat(size(matches))) as match_score,
                         CASE
                             WHEN n.last_seen > datetime() - duration('P1D') THEN 1.0
                             WHEN n.last_seen > datetime() - duration('P3D') THEN 0.85
                             WHEN n.last_seen > datetime() - duration('P7D') THEN 0.7
                             WHEN n.last_seen > datetime() - duration('P14D') THEN 0.5
                             WHEN n.last_seen > datetime() - duration('P30D') THEN 0.4
                             ELSE 0.2
                         END as recency_score
                    RETURN n.name as name, n.node_type as type,
                           (match_score * recency_score) as relevance
                    ORDER BY relevance DESC
                    LIMIT $limit
                    """,
                    user_id=user_id,
                    entity_names=entity_names,
                    words=words,
                    limit=limit
                )

                entry_nodes = [(r["name"], r["type"], r["relevance"]) for r in entry_points]

                # STEP 2: Multi-hop traversal from entry points
                # Get subgraph with paths up to 2 hops
                for entry_name, entry_type, relevance in entry_nodes:
                    # Get 2-hop neighborhood with relationship paths
                    subgraph = session.run(
                        """
                        MATCH (start {name: $name, user_id: $user_id})
                        OPTIONAL MATCH path = (start)-[r1]-(hop1 {user_id: $user_id})
                        WHERE hop1.node_type IS NOT NULL
                        OPTIONAL MATCH path2 = (hop1)-[r2]-(hop2 {user_id: $user_id})
                        WHERE hop2.node_type IS NOT NULL AND hop2.name <> start.name
                        WITH start,
                             collect(DISTINCT {
                                 node: hop1.name,
                                 type: hop1.node_type,
                                 rel: type(r1),
                                 confidence: COALESCE(r1.confidence, 0.5),
                                 created_at: toString(r1.created_at),
                                 source_conversation_id: r1.source_conversation_id,
                                 is_active: COALESCE(r1.is_active, true),
                                 hop: 1
                             }) as hop1_nodes,
                             collect(DISTINCT {
                                 node: hop2.name,
                                 type: hop2.node_type,
                                 via: hop1.name,
                                 rel1: type(r1),
                                 rel2: type(r2),
                                 confidence: COALESCE(r1.confidence, 0.5) * COALESCE(r2.confidence, 0.5),
                                 created_at: toString(r1.created_at),
                                 source_conversation_id: r1.source_conversation_id,
                                 is_active: COALESCE(r1.is_active, true),
                                 hop: 2
                             }) as hop2_nodes
                        RETURN start.name as entity, start.node_type as entity_type,
                               hop1_nodes, hop2_nodes
                        """,
                        name=entry_name,
                        user_id=user_id
                    )

                    record = subgraph.single()
                    if record:
                        hop1 = [h for h in record["hop1_nodes"]
                               if h["node"] and is_valid_entity(h["node"])]
                        hop2 = [h for h in record["hop2_nodes"]
                               if h["node"] and is_valid_entity(h["node"])]

                        # Build paths for context
                        paths = []
                        for h1 in hop1[:5]:
                            paths.append({
                                "path": f"{entry_name} -[{h1['rel']}]-> {h1['node']}",
                                "target": h1["node"],
                                "target_type": h1["type"],
                                "confidence": h1["confidence"],
                                "created_at": h1.get("created_at"),
                                "source_conversation_id": h1.get("source_conversation_id"),
                                "is_active": h1.get("is_active", True),
                                "hops": 1
                            })

                        for h2 in hop2[:3]:
                            if h2["via"]:
                                paths.append({
                                    "path": f"{entry_name} -[{h2['rel1']}]-> {h2['via']} -[{h2['rel2']}]-> {h2['node']}",
                                    "target": h2["node"],
                                    "target_type": h2["type"],
                                    "confidence": h2["confidence"],
                                    "created_at": h2.get("created_at"),
                                    "source_conversation_id": h2.get("source_conversation_id"),
                                    "is_active": h2.get("is_active", True),
                                    "hops": 2
                                })

                        context_results.append({
                            "entity": entry_name,
                            "type": entry_type,
                            "relevance": relevance,
                            "paths": paths,
                            "direct_relations": hop1[:5]
                        })

                # STEP 3: If no direct matches, use graph-aware fallback
                # Get most connected recent entities (high-degree nodes are often important)
                if not context_results:
                    result = session.run(
                        """
                        MATCH (n {user_id: $user_id})
                        WHERE n.node_type IN ['technology', 'framework', 'programming_language',
                                              'tool', 'error_type', 'project', 'decision']
                        WITH n, COUNT { (n)--() } as degree
                        ORDER BY n.last_seen DESC, degree DESC
                        LIMIT $limit
                        OPTIONAL MATCH (n)-[r]-(related {user_id: $user_id})
                        WHERE related.node_type IS NOT NULL
                        RETURN n.name as entity, n.node_type as type, degree,
                               collect(DISTINCT {
                                   node: related.name,
                                   type: related.node_type,
                                   rel: type(r)
                               })[0..3] as connections
                        """,
                        user_id=user_id,
                        limit=limit
                    )

                    for record in result:
                        entity = record["entity"]
                        if entity and is_valid_entity(entity):
                            connections = [c for c in record["connections"]
                                         if c["node"] and is_valid_entity(c["node"])]
                            paths = []
                            for c in connections:
                                paths.append({
                                    "path": f"{entity} -[{c['rel']}]-> {c['node']}",
                                    "target": c["node"],
                                    "target_type": c["type"],
                                    "confidence": 0.5,
                                    "hops": 1
                                })
                            context_results.append({
                                "entity": entity,
                                "type": record["type"],
                                "relevance": 0.3,
                                "paths": paths,
                                "direct_relations": connections
                            })

            # STEP 4: Community detection — group co-occurring entities into
            # topic clusters so the LLM can reason about broader themes.
            # Uses connected components: entities sharing relationships form a topic.
            if context_results:
                context_results = self._detect_communities(context_results)

            logger.info(f"GraphRAG search found {len(context_results)} entities with {sum(len(c.get('paths', [])) for c in context_results)} relationship paths")
            return context_results

        except Exception as e:
            logger.error(f"GraphRAG search failed: {e}")
            return []

    @staticmethod
    def _detect_communities(context_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Group entities into topic clusters based on shared relationships.

        Entities that share relationship targets are grouped into the same
        community/topic. This helps the LLM understand broader themes
        rather than isolated facts.

        Args:
            context_results: List of entity context dicts from search_by_query.

        Returns:
            Same list with 'community' field added to each entry.
        """
        if not context_results:
            return context_results

        # Build adjacency: entity -> set of connected entity names
        entity_neighbors: Dict[str, set] = {}
        for ctx in context_results:
            entity = ctx["entity"]
            neighbors = set()
            for path in ctx.get("paths", []):
                target = path.get("target", "")
                if target:
                    neighbors.add(target)
            for rel in ctx.get("direct_relations", []):
                node = rel.get("node", "")
                if node:
                    neighbors.add(node)
            entity_neighbors[entity] = neighbors

        # Union-Find to group entities sharing neighbors
        parent: Dict[str, str] = {}

        def find(x: str) -> str:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        entities = list(entity_neighbors.keys())
        for e in entities:
            parent[e] = e

        # Merge entities that share at least one neighbor
        for i, e1 in enumerate(entities):
            for e2 in entities[i + 1:]:
                if entity_neighbors[e1] & entity_neighbors[e2]:
                    union(e1, e2)

        # Assign community labels based on the most common node_type in each group
        communities: Dict[str, List[str]] = {}
        for e in entities:
            root = find(e)
            communities.setdefault(root, []).append(e)

        # Label communities by their dominant entity type
        community_labels: Dict[str, str] = {}
        type_map = {ctx["entity"]: ctx.get("type", "unknown") for ctx in context_results}
        for root, members in communities.items():
            types = [type_map.get(m, "unknown") for m in members]
            # Most common type becomes the topic label
            dominant = max(set(types), key=types.count) if types else "general"
            label = f"{dominant}_topic"
            community_labels[root] = label

        # Attach community to each result
        for ctx in context_results:
            root = find(ctx["entity"])
            ctx["community"] = community_labels.get(root, "general_topic")
            ctx["community_members"] = communities.get(root, [ctx["entity"]])

        return context_results

    def format_context_for_prompt(self, context_results: List[Dict[str, Any]]) -> str:
        """
        Format graph context for LLM prompt injection.

        Groups entities by community/topic for coherent context.
        Outputs relationship paths that help the LLM reason about connections.
        Higher confidence paths are prioritized.
        """
        if not context_results:
            return ""

        lines = ["[Knowledge Graph Context]"]
        lines.append("The following entities and relationships are relevant to this conversation:")
        lines.append("")

        # Group by community for coherent topic presentation
        communities: Dict[str, List[Dict[str, Any]]] = {}
        for ctx in context_results:
            community = ctx.get("community", "general_topic")
            communities.setdefault(community, []).append(ctx)

        for community, members in communities.items():
            # Show topic header if multiple communities exist
            if len(communities) > 1:
                topic_label = community.replace("_topic", "").replace("_", " ").title()
                lines.append(f"── {topic_label} ──")

            for ctx in members:
                entity = ctx["entity"]
                etype = ctx["type"]

                # Entity header
                lines.append(f"• {entity} ({etype})")

                # Show relationship paths (sorted by confidence)
                paths = ctx.get("paths", [])
                if paths:
                    sorted_paths = sorted(paths, key=lambda p: p.get("confidence", 0), reverse=True)
                    for path_info in sorted_paths[:5]:
                        path = path_info.get("path", "")
                        conf = path_info.get("confidence", 0)
                        if path:
                            conf_indicator = "●" if conf > 0.7 else "○" if conf > 0.4 else "◌"
                            # Temporal citation: when and active status
                            citation = ""
                            created = path_info.get("created_at")
                            is_active = path_info.get("is_active", True)
                            if created:
                                # Parse ISO timestamp to readable date
                                try:
                                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                                    citation = f" (learned {dt.strftime('%b %d')})"
                                except (ValueError, AttributeError):
                                    pass
                            if not is_active:
                                citation += " [NO LONGER TRUE]"
                            lines.append(f"  {conf_indicator} {path}{citation}")

                # Fallback to direct relations if no paths
                elif ctx.get("direct_relations"):
                    for rel in ctx["direct_relations"][:3]:
                        rel_name = rel.get("node", rel.get("name", ""))
                        rel_type = rel.get("type", "")
                        relationship = rel.get("rel", "RELATES_TO")
                        if rel_name:
                            lines.append(f"  → {relationship} {rel_name} ({rel_type})")

                lines.append("")

        # Add reasoning hint for the LLM
        lines.append("Use these relationships to inform your response with contextual awareness.")

        return "\n".join(lines)

    def get_entity_context(
        self,
        entity_name: str,
        user_id: str,
        max_hops: int = 2
    ) -> Dict[str, Any]:
        """
        Get full context for a specific entity including all relationships.

        Useful for deep-dive questions about a specific topic.

        Args:
            entity_name: Name of the entity to explore
            user_id: User ID for isolation
            max_hops: Maximum traversal depth

        Returns:
            Dict with entity info and full relationship graph
        """
        if not self.is_available:
            return {}

        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(
                    f"""
                    MATCH (start {{name: $name, user_id: $user_id}})
                    OPTIONAL MATCH path = (start)-[*1..{max_hops}]-(connected {{user_id: $user_id}})
                    WHERE connected.node_type IS NOT NULL
                    WITH start, connected, relationships(path) as rels,
                         [node in nodes(path) | node.name] as path_nodes
                    RETURN start.name as entity,
                           start.node_type as type,
                           start.properties as properties,
                           collect(DISTINCT {{
                               target: connected.name,
                               target_type: connected.node_type,
                               path: path_nodes,
                               relationship_chain: [r in rels | type(r)]
                           }}) as connections
                    """,
                    name=entity_name,
                    user_id=user_id
                )

                record = result.single()
                if not record:
                    return {}

                connections = [
                    c for c in record["connections"]
                    if c["target"] and is_valid_entity(c["target"])
                ]

                return {
                    "entity": record["entity"],
                    "type": record["type"],
                    "properties": record["properties"] or {},
                    "connections": connections
                }

        except Exception as e:
            logger.error(f"Failed to get entity context for {entity_name}: {e}")
            return {}

    def find_paths_between(
        self,
        entity1: str,
        entity2: str,
        user_id: str,
        max_hops: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Find relationship paths between two entities.

        Useful for understanding how concepts are connected.

        Args:
            entity1: Starting entity name
            entity2: Target entity name
            user_id: User ID for isolation
            max_hops: Maximum path length

        Returns:
            List of paths with relationship chains
        """
        if not self.is_available:
            return []

        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(
                    f"""
                    MATCH path = shortestPath(
                        (a {{name: $entity1, user_id: $user_id}})-[*1..{max_hops}]-
                        (b {{name: $entity2, user_id: $user_id}})
                    )
                    WITH path, [node in nodes(path) | node.name] as node_names,
                         [rel in relationships(path) | type(rel)] as rel_types
                    RETURN node_names, rel_types, length(path) as path_length
                    LIMIT 3
                    """,
                    entity1=entity1,
                    entity2=entity2,
                    user_id=user_id
                )

                paths = []
                for record in result:
                    nodes = record["node_names"]
                    rels = record["rel_types"]

                    # Build readable path string
                    path_parts = []
                    for i, node in enumerate(nodes):
                        path_parts.append(node)
                        if i < len(rels):
                            path_parts.append(f"-[{rels[i]}]->")

                    paths.append({
                        "path_string": " ".join(path_parts),
                        "nodes": nodes,
                        "relationships": rels,
                        "length": record["path_length"]
                    })

                return paths

        except Exception as e:
            logger.error(f"Failed to find paths between {entity1} and {entity2}: {e}")
            return []


    def prune_stale_nodes(
        self,
        user_id: str,
        max_age_days: int = 90,
        min_degree: int = 0,
    ) -> Dict[str, int]:
        """Periodic cleanup: remove stale, orphaned, and invalid nodes.

        Should be called on a schedule (e.g., weekly) to prevent graph rot.
        Removes:
        1. Orphaned nodes (no relationships) older than max_age_days
        2. Nodes that fail is_valid_entity (retroactive filter)
        3. Nodes with None/empty names

        Args:
            user_id: User ID for isolation.
            max_age_days: Remove orphaned nodes older than this.
            min_degree: Minimum relationship count to keep (0 = keep connected nodes).

        Returns:
            Dict with counts: orphaned_removed, invalid_removed, total_remaining.
        """
        if not self.is_available:
            return {"orphaned_removed": 0, "invalid_removed": 0, "total_remaining": 0}

        try:
            with self.driver.session(database=self.database) as session:
                # 1. Remove orphaned nodes older than max_age_days
                orphan_result = session.run(
                    """
                    MATCH (n {user_id: $user_id})
                    WHERE COUNT { (n)--() } <= $min_degree
                      AND n.last_seen < datetime() - duration({days: $max_age_days})
                    WITH n, n.name AS name
                    DETACH DELETE n
                    RETURN count(name) AS removed
                    """,
                    user_id=user_id,
                    min_degree=min_degree,
                    max_age_days=max_age_days,
                )
                orphaned = orphan_result.single()["removed"]

                # 2. Remove nodes that fail is_valid_entity (retroactive)
                all_nodes = session.run(
                    "MATCH (n {user_id: $user_id}) RETURN elementId(n) AS eid, n.name AS name",
                    user_id=user_id,
                )
                invalid_ids = [
                    r["eid"] for r in all_nodes
                    if not is_valid_entity(r["name"])
                ]
                if invalid_ids:
                    # Delete in batches
                    for i in range(0, len(invalid_ids), 50):
                        batch = invalid_ids[i:i + 50]
                        session.run(
                            "MATCH (n) WHERE elementId(n) IN $ids DETACH DELETE n",
                            ids=batch,
                        )

                # 3. Count remaining
                remaining = session.run(
                    "MATCH (n {user_id: $user_id}) RETURN count(n) AS cnt",
                    user_id=user_id,
                ).single()["cnt"]

                stats = {
                    "orphaned_removed": orphaned,
                    "invalid_removed": len(invalid_ids),
                    "total_remaining": remaining,
                }
                logger.info(f"Graph pruned for user {user_id}: {stats}")
                return stats

        except Exception as e:
            logger.error(f"Graph pruning failed: {e}")
            return {"orphaned_removed": 0, "invalid_removed": 0, "total_remaining": 0}

    def get_recent_activity_summary(
        self,
        user_id: str,
        days: int = 7,
        limit: int = 15
    ) -> Dict[str, Any]:
        """
        Get a summary of recent knowledge graph activity.

        Useful for questions like "what have I been working on?" or
        providing conversational context about recent topics.

        Args:
            user_id: User ID for isolation
            days: Look back this many days
            limit: Maximum entities to return

        Returns:
            Dict with categorized recent entities and their connections
        """
        if not self.is_available:
            return {}

        try:
            with self.driver.session(database=self.database) as session:
                # Build duration string for Neo4j (P7D = 7 days)
                duration_str = f"P{days}D"
                result = session.run(
                    """
                    MATCH (n {user_id: $user_id})
                    WHERE n.node_type IS NOT NULL
                    AND n.last_seen > datetime() - duration($duration_str)
                    WITH n, COUNT { (n)--() } as connections
                    ORDER BY n.last_seen DESC, connections DESC
                    LIMIT $limit
                    OPTIONAL MATCH (n)-[r]-(related {user_id: $user_id})
                    WHERE related.node_type IS NOT NULL
                    AND related.last_seen > datetime() - duration($duration_str)
                    RETURN n.name as entity, n.node_type as type,
                           n.last_seen as last_seen, connections,
                           collect(DISTINCT {
                               name: related.name,
                               type: related.node_type,
                               rel: type(r)
                           })[0..3] as recent_connections
                    """,
                    user_id=user_id,
                    duration_str=duration_str,
                    limit=limit
                )

                # Categorize by type
                by_type = {}
                all_entities = []

                for record in result:
                    entity = record["entity"]
                    if not entity or not is_valid_entity(entity):
                        continue

                    etype = record["type"]
                    connections = [c for c in record["recent_connections"]
                                  if c["name"] and is_valid_entity(c["name"])]

                    entity_info = {
                        "name": entity,
                        "connections": record["connections"],
                        "recent_relations": connections
                    }

                    if etype not in by_type:
                        by_type[etype] = []
                    by_type[etype].append(entity_info)
                    all_entities.append(entity)

                return {
                    "by_type": by_type,
                    "all_entities": all_entities,
                    "period_days": days
                }

        except Exception as e:
            logger.error(f"Failed to get recent activity summary: {e}")
            return {}

    def format_activity_summary(self, summary: Dict[str, Any]) -> str:
        """Format recent activity summary for LLM context."""
        if not summary or not summary.get("by_type"):
            return ""

        lines = ["[Recent Activity Summary]"]
        lines.append(f"Topics discussed in the last {summary.get('period_days', 7)} days:")
        lines.append("")

        type_labels = {
            "technology": "Technologies",
            "framework": "Frameworks",
            "programming_language": "Languages",
            "tool": "Tools",
            "project": "Projects",
            "error_type": "Issues/Errors",
            "decision": "Decisions",
            "person": "People",
            "concept": "Concepts"
        }

        for etype, entities in summary.get("by_type", {}).items():
            label = type_labels.get(etype, etype.replace("_", " ").title())
            entity_names = [e["name"] for e in entities[:5]]
            if entity_names:
                lines.append(f"• {label}: {', '.join(entity_names)}")

        return "\n".join(lines)


# Noisy entities to filter out
NOISE_ENTITIES = {
    # Pronouns
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their", "this", "that", "these", "those",
    # Common words
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "what", "which", "who", "whom", "where", "when", "why", "how",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might",
    "not", "no", "yes", "so", "if", "then", "than", "also", "just", "only",
    # Punctuation and symbols
    "*", "-", "_", ".", ",", "!", "?", ":", ";", "/", "\\", "|",
    # Generic terms
    "thing", "stuff", "something", "anything", "nothing", "everything",
    "user", "app", "args", "none", "true", "false", "null", "data",
    "result", "value", "key", "name", "type", "list", "dict", "str", "int",
}

def is_valid_entity(name: str) -> bool:
    """Check if an entity name is valid (not noise).

    Rejects pronouns, common words, code fragments, overly long strings,
    numeric-only tokens, and other patterns that pollute the knowledge graph.

    Args:
        name: Candidate entity name to validate.

    Returns:
        True if the entity is meaningful and worth storing.
    """
    if not name or len(name.strip()) < 2:
        return False
    name_stripped = name.strip()
    name_lower = name_stripped.lower()
    # Filter out noise words
    if name_lower in NOISE_ENTITIES:
        return False
    # Filter out pure numbers or numeric patterns like "1.", "2.", "1-2"
    if name_stripped.replace(".", "").replace("-", "").replace(",", "").isdigit():
        return False
    # Filter out single characters or two-char noise (##, e}, etc.)
    if len(name_stripped) <= 2 and not name_stripped.isalpha():
        return False
    # Reject entities longer than 80 chars — likely code or sentence fragments
    if len(name_stripped) > 80:
        return False
    # Reject if it contains newlines — definitely a code block or multi-line fragment
    if "\n" in name_stripped:
        return False
    # Reject if it looks like code (contains common code patterns)
    _CODE_SIGNALS = ["()", "=>", "->", "==", "!=", "+=", "def ", "class ",
                     "import ", "return ", "async ", "{}", "[]", "//", "/*",
                     ".append(", ".get(", ".split(", "print(", "logger."]
    if any(sig in name_stripped for sig in _CODE_SIGNALS):
        return False
    # Reject if more than 30% of characters are symbols/punctuation
    alpha_count = sum(1 for c in name_stripped if c.isalnum() or c == ' ')
    if len(name_stripped) > 3 and alpha_count / len(name_stripped) < 0.7:
        return False
    # Reject markdown headers (# Section Name)
    if name_stripped.startswith('#'):
        return False
    # Reject strings starting with @ (decorators, mentions)
    if name_stripped.startswith('@'):
        return False
    # Reject CamelCase class/function names that are likely code identifiers
    # (e.g., AddinConfig, APIRouter, ConversationCreate) but allow real names
    if (len(name_stripped) > 3 and ' ' not in name_stripped
            and any(c.isupper() for c in name_stripped[1:])
            and name_stripped[0].isupper()
            and name_stripped.isidentifier()):
        # Allow known proper nouns (single capitalized words like "Python", "Neo4j")
        # Reject multi-cap identifiers like AddinConfig, APIRouter
        upper_count = sum(1 for c in name_stripped[1:] if c.isupper())
        if upper_count >= 2:
            return False
    # Reject strings that end with common code suffixes
    _CODE_SUFFIXES = ('Request', 'Response', 'Config', 'Router', 'Handler',
                      'Service', 'Store', 'Manager', 'Factory', 'Provider',
                      'Middleware', 'Schema', 'Model', 'Type', 'Error',
                      'Exception', 'Registry', 'Controller')
    if any(name_stripped.endswith(s) for s in _CODE_SUFFIXES) and ' ' not in name_stripped:
        return False
    return True


# Module-level singleton
_graph_store: Optional[Neo4jGraphStore] = None


def get_graph_store(
    uri: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    database: str = "neo4j"
) -> Optional[Neo4jGraphStore]:
    """
    Get or create the singleton Neo4jGraphStore instance.

    Args:
        uri: Neo4j connection URI
        username: Neo4j username
        password: Neo4j password
        database: Database name

    Returns:
        Neo4jGraphStore singleton instance or None if not available
    """
    global _graph_store
    # Create if not exists, or recreate if not available
    if uri and username and password:
        if _graph_store is None:
            logger.info(f"Creating new graph store: uri={uri}, user={username}")
            _graph_store = Neo4jGraphStore(
                uri=uri,
                username=username,
                password=password,
                database=database
            )
            logger.info(f"Graph store created, available: {_graph_store.is_available}")
        elif not _graph_store.is_available:
            logger.info(f"Recreating unavailable graph store: uri={uri}")
            _graph_store = Neo4jGraphStore(
                uri=uri,
                username=username,
                password=password,
                database=database
            )
            logger.info(f"Graph store recreated, available: {_graph_store.is_available}")
    return _graph_store
