"""
Knowledge Graph API router.

Provides endpoints for browsing, searching, and managing the Neo4j
knowledge graph from the frontend. All queries are user-isolated.
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from database import get_database
from routers.auth import get_current_user
from utils.encryption import decrypt_api_key

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# Helpers
# ============================================================

async def _get_graph_store(user_id: str):
    """Get the Neo4j graph store, using .env config first, user settings as fallback.

    Mirrors the pattern used by messages.py and openai_compat.py so the graph
    viewer works with the same Neo4j instance the rest of the app uses.
    """
    from knowledge_graph.graph_store import get_graph_store
    from config import get_settings

    env = get_settings()
    uri = env.neo4j_uri
    username = env.neo4j_username
    password = env.neo4j_password
    database = env.neo4j_database

    # Fall back to user's saved settings if .env doesn't have Neo4j config
    if not uri or not password:
        db = get_database()
        settings = await db.llm_settings.find_one({"userId": user_id})
        if settings:
            neo4j_cfg = settings.get("neo4j", {})
            uri = uri or neo4j_cfg.get("uri")
            username = username or neo4j_cfg.get("username")
            database = database or neo4j_cfg.get("database", "neo4j")
            if not password and neo4j_cfg.get("password"):
                try:
                    password = decrypt_api_key(neo4j_cfg["password"])
                except Exception:
                    pass

    if not uri or not password:
        raise HTTPException(503, "Neo4j not configured — set NEO4J_URI/NEO4J_PASSWORD in .env or Settings")

    store = get_graph_store(uri=uri, username=username, password=password, database=database)
    if not store or not store.is_available:
        raise HTTPException(503, "Neo4j is not reachable — check connection settings")

    return store


# ============================================================
# Response models
# ============================================================

class GraphStatsResponse(BaseModel):
    """High-level graph statistics."""
    total_nodes: int = 0
    total_relationships: int = 0
    node_types: Dict[str, int] = {}
    relationship_types: Dict[str, int] = {}


class GraphNodeResponse(BaseModel):
    """A single node for the frontend."""
    name: str
    node_type: str
    label: str
    created_at: Optional[str] = None
    last_seen: Optional[str] = None
    properties: Dict[str, Any] = {}
    connection_count: int = 0


class GraphEdgeResponse(BaseModel):
    """A single relationship for the frontend."""
    from_node: str
    to_node: str
    rel_type: str
    confidence: Optional[float] = None
    created_at: Optional[str] = None


class GraphNeighborhoodResponse(BaseModel):
    """A node and its immediate neighborhood."""
    center: GraphNodeResponse
    nodes: List[GraphNodeResponse] = []
    edges: List[GraphEdgeResponse] = []


# ============================================================
# Endpoints
# ============================================================

@router.get("/stats", response_model=GraphStatsResponse)
async def get_graph_stats(
    current_user: dict = Depends(get_current_user)
):
    """Get high-level graph statistics (node/relationship counts by type)."""
    user_id = current_user["id"]
    store = await _get_graph_store(user_id)

    def _query():
        with store.driver.session(database=store.database) as session:
            # Node counts by type
            node_result = session.run(
                """
                MATCH (n {user_id: $user_id})
                RETURN n.node_type AS type, count(n) AS cnt
                """,
                user_id=user_id
            )
            node_types = {}
            total_nodes = 0
            for record in node_result:
                t = record["type"] or "unknown"
                c = record["cnt"]
                node_types[t] = c
                total_nodes += c

            # Relationship counts by type
            rel_result = session.run(
                """
                MATCH (a {user_id: $user_id})-[r]->(b {user_id: $user_id})
                RETURN type(r) AS type, count(r) AS cnt
                """,
                user_id=user_id
            )
            rel_types = {}
            total_rels = 0
            for record in rel_result:
                t = record["type"]
                c = record["cnt"]
                rel_types[t] = c
                total_rels += c

            return GraphStatsResponse(
                total_nodes=total_nodes,
                total_relationships=total_rels,
                node_types=node_types,
                relationship_types=rel_types,
            )

    return await run_in_threadpool(_query)


@router.get("/nodes", response_model=List[GraphNodeResponse])
async def list_nodes(
    current_user: dict = Depends(get_current_user),
    search: Optional[str] = Query(None, description="Search by name substring"),
    node_type: Optional[str] = Query(None, description="Filter by node type"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List nodes with optional search and type filter. Sorted by last_seen descending."""
    user_id = current_user["id"]
    store = await _get_graph_store(user_id)

    def _query():
        with store.driver.session(database=store.database) as session:
            query = "MATCH (n {user_id: $user_id})"
            params: Dict[str, Any] = {"user_id": user_id, "limit": limit, "offset": offset}

            conditions = []
            if node_type:
                conditions.append("n.node_type = $node_type")
                params["node_type"] = node_type
            if search:
                conditions.append("toLower(n.name) CONTAINS toLower($search)")
                params["search"] = search

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            # Count connections per node
            query += """
                OPTIONAL MATCH (n)-[r]-()
                WITH n, count(r) AS conn_count
                RETURN n, labels(n) AS labels, conn_count
                ORDER BY n.last_seen DESC
                SKIP $offset LIMIT $limit
            """

            result = session.run(query, **params)
            nodes = []
            for record in result:
                nd = dict(record["n"])
                label = record["labels"][0] if record["labels"] else "Entity"
                created = nd.get("created_at")
                last_seen = nd.get("last_seen")
                nodes.append(GraphNodeResponse(
                    name=nd.get("name", ""),
                    node_type=nd.get("node_type", ""),
                    label=label,
                    created_at=str(created) if created else None,
                    last_seen=str(last_seen) if last_seen else None,
                    properties=_safe_props(nd.get("properties")),
                    connection_count=record["conn_count"],
                ))
            return nodes

    return await run_in_threadpool(_query)


@router.get("/nodes/{node_name}/neighborhood", response_model=GraphNeighborhoodResponse)
async def get_node_neighborhood(
    node_name: str,
    current_user: dict = Depends(get_current_user),
    depth: int = Query(1, ge=1, le=3),
):
    """Get a node and its immediate neighborhood (connected nodes + edges)."""
    user_id = current_user["id"]
    store = await _get_graph_store(user_id)

    def _query():
        with store.driver.session(database=store.database) as session:
            # Get center node
            center_result = session.run(
                """
                MATCH (n {name: $name, user_id: $user_id})
                OPTIONAL MATCH (n)-[r]-()
                WITH n, labels(n) AS labels, count(r) AS conn_count
                RETURN n, labels, conn_count
                """,
                name=node_name, user_id=user_id
            )
            center_record = center_result.single()
            if not center_record:
                return None

            nd = dict(center_record["n"])
            center = GraphNodeResponse(
                name=nd.get("name", ""),
                node_type=nd.get("node_type", ""),
                label=center_record["labels"][0] if center_record["labels"] else "Entity",
                created_at=str(nd.get("created_at")) if nd.get("created_at") else None,
                last_seen=str(nd.get("last_seen")) if nd.get("last_seen") else None,
                properties=_safe_props(nd.get("properties")),
                connection_count=center_record["conn_count"],
            )

            # Get neighborhood
            neighborhood_result = session.run(
                f"""
                MATCH (center {{name: $name, user_id: $user_id}})-[r*1..{depth}]-(related)
                WHERE related.user_id = $user_id
                WITH DISTINCT related, r
                OPTIONAL MATCH (related)-[r2]-()
                WITH related, labels(related) AS labels, count(r2) AS conn_count, r
                RETURN related, labels, conn_count
                LIMIT 50
                """,
                name=node_name, user_id=user_id
            )

            nodes = []
            seen_names = {node_name}
            for record in neighborhood_result:
                rd = dict(record["related"])
                rname = rd.get("name", "")
                if rname in seen_names:
                    continue
                seen_names.add(rname)
                nodes.append(GraphNodeResponse(
                    name=rname,
                    node_type=rd.get("node_type", ""),
                    label=record["labels"][0] if record["labels"] else "Entity",
                    created_at=str(rd.get("created_at")) if rd.get("created_at") else None,
                    last_seen=str(rd.get("last_seen")) if rd.get("last_seen") else None,
                    properties=_safe_props(rd.get("properties")),
                    connection_count=record["conn_count"],
                ))

            # Get edges between all nodes in the neighborhood
            all_names = list(seen_names)
            edge_result = session.run(
                """
                MATCH (a {user_id: $user_id})-[r]->(b {user_id: $user_id})
                WHERE a.name IN $names AND b.name IN $names
                RETURN a.name AS from_name, b.name AS to_name, type(r) AS rel_type,
                       r.confidence AS confidence, r.created_at AS created_at
                """,
                user_id=user_id, names=all_names
            )

            edges = []
            for record in edge_result:
                edges.append(GraphEdgeResponse(
                    from_node=record["from_name"],
                    to_node=record["to_name"],
                    rel_type=record["rel_type"],
                    confidence=record["confidence"],
                    created_at=str(record["created_at"]) if record["created_at"] else None,
                ))

            return GraphNeighborhoodResponse(center=center, nodes=nodes, edges=edges)

    result = await run_in_threadpool(_query)
    if result is None:
        raise HTTPException(404, f"Node '{node_name}' not found")
    return result


@router.delete("/nodes/{node_name}")
async def delete_node(
    node_name: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a node and all its relationships from the graph."""
    user_id = current_user["id"]
    store = await _get_graph_store(user_id)

    def _delete():
        with store.driver.session(database=store.database) as session:
            result = session.run(
                """
                MATCH (n {name: $name, user_id: $user_id})
                DETACH DELETE n
                RETURN count(n) AS deleted
                """,
                name=node_name, user_id=user_id
            )
            record = result.single()
            return record["deleted"] if record else 0

    deleted = await run_in_threadpool(_delete)
    if deleted == 0:
        raise HTTPException(404, f"Node '{node_name}' not found")

    logger.info(f"Deleted graph node '{node_name}' for user {user_id}")
    return {"success": True, "deleted": node_name}


@router.delete("/nodes/{node_name}/edges/{target_name}")
async def delete_edge(
    node_name: str,
    target_name: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete all relationships between two specific nodes."""
    user_id = current_user["id"]
    store = await _get_graph_store(user_id)

    def _delete():
        with store.driver.session(database=store.database) as session:
            result = session.run(
                """
                MATCH (a {name: $from_name, user_id: $user_id})-[r]-(b {name: $to_name, user_id: $user_id})
                DELETE r
                RETURN count(r) AS deleted
                """,
                from_name=node_name, to_name=target_name, user_id=user_id
            )
            record = result.single()
            return record["deleted"] if record else 0

    deleted = await run_in_threadpool(_delete)
    logger.info(f"Deleted {deleted} edge(s) between '{node_name}' and '{target_name}' for user {user_id}")
    return {"success": True, "deleted_count": deleted}


# ============================================================
# Helpers
# ============================================================

def _safe_props(props: Any) -> Dict[str, Any]:
    """Safely parse properties which may be a JSON string or dict."""
    if not props:
        return {}
    if isinstance(props, str):
        import json
        try:
            return json.loads(props)
        except (json.JSONDecodeError, TypeError):
            return {"raw": props}
    if isinstance(props, dict):
        return props
    return {}
