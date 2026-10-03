"""MCP server tools against throwaway databases.

Calls go through the SDK's real tools/call handler, so a failing tool must come
back with isError=true (not as a normal-looking result).
"""
import asyncio
import json
import os
import subprocess
import sys
import types as pytypes
from pathlib import Path

import pytest

pytest.importorskip("mcp")
from mcp import types  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import mcp_databases  # noqa: E402
import mcp_knowledge_db  # noqa: E402
import mcp_server  # noqa: E402


@pytest.fixture
def mcp(tmp_path, monkeypatch):
    """MCP stores in tmp_path; the JSON learning stores and Neo4j switched off."""
    monkeypatch.setattr(mcp_knowledge_db, "_mcp_db", mcp_knowledge_db.MCPKnowledgeDB(tmp_path / "knowledge.db"))
    monkeypatch.setattr(mcp_databases, "_user_db", mcp_databases.UserInteractionsDB(tmp_path / "interactions.db"))
    monkeypatch.setattr(mcp_databases, "_ai_db", mcp_databases.AIReasoningDB(tmp_path / "reasoning.db"))
    monkeypatch.setattr(mcp_databases, "_unified_search", None)
    for getter in ("get_skill_store", "get_session_manager", "get_reflection_system", "get_graph_store"):
        monkeypatch.setattr(mcp_server, getter, lambda: None)
    return tmp_path


def call(name, arguments=None):
    """Run one tools/call; returns (is_error, parsed JSON or raw text)."""
    handler = mcp_server.server.request_handlers[types.CallToolRequest]
    request = types.CallToolRequest(
        method="tools/call", params=types.CallToolRequestParams(name=name, arguments=arguments or {}),
    )
    result = asyncio.run(handler(request)).root
    text = result.content[0].text
    try:
        body = json.loads(text)
    except ValueError:
        body = text
    return bool(result.isError), body


class FakeGraph:
    """A Neo4j store. ok=False: every write fails the way the real one does, by returning False."""
    is_available = True

    def __init__(self, ok):
        self.ok = ok
        self.calls = []

    def add_node(self, node, user_id):
        self.calls.append(("add_node", node.name))
        return self.ok

    def add_relationship_dynamic(self, **kwargs):
        self.calls.append(("rel", kwargs["from_node"], kwargs["to_node"]))
        return self.ok

    def invalidate_relationships(self, *args, **kwargs):
        return 0


# ── Errors are errors ──────────────────────────────────────────────

def test_unknown_tool_is_an_error(mcp):
    is_error, body = call("no_such_tool")
    assert is_error and "Unknown tool" in body


def test_record_outcome_for_unknown_ids_is_an_error(mcp):
    is_error, body = call("record_skill_outcome", {"skill_id": "nope", "successful": True})
    assert is_error and "Unknown skill_id" in body
    is_error, body = call("record_playbook_outcome", {"playbook_id": "nope", "successful": True})
    assert is_error and "Unknown playbook_id" in body


def test_record_skill_outcome_updates_a_real_skill(mcp):
    _, created = call("create_skill", {
        "name": "Fix CORS", "description": "d", "triggers": ["cors"], "solution_text": "add the header",
    })
    is_error, body = call("record_skill_outcome", {"skill_id": created["skill_id"], "successful": True})
    assert not is_error and body["updated_in"] == ["mcp-sqlite"]


def test_record_skill_outcome_accepts_solution_ids_from_find_skill(mcp):
    call("store_solution", {"problem": "cors error on fetch", "solution": "add the header"})
    _, found = call("find_skill", {"query": "cors error"})
    solution = found["skills"][0]
    assert solution["source"] == "sqlite_solutions"
    is_error, body = call("record_skill_outcome", {"skill_id": solution["id"], "successful": True})
    assert not is_error and body["updated_in"] == ["mcp-sqlite-solutions"]


def test_record_skill_outcome_names_a_failed_write(mcp, monkeypatch):
    class Store:
        async def get_skill(self, skill_id):
            return pytypes.SimpleNamespace(confidence=0.5)

        async def update_skill_usage(self, skill_id, successful):
            raise PermissionError("read-only file")

    monkeypatch.setattr(mcp_server, "get_skill_store", lambda: Store())
    is_error, body = call("record_skill_outcome", {"skill_id": "abc", "successful": True})
    assert is_error and "read-only file" in body and "Unknown" not in body


def test_record_playbook_outcome_updates_a_real_playbook(mcp):
    _, created = call("create_playbook", {"name": "p", "description": "d", "steps": [{"step": 1, "action": "do it"}]})
    is_error, body = call("record_playbook_outcome", {"playbook_id": created["playbook_id"], "successful": True})
    assert not is_error and body["times_used"] == 1


# ── Reports only what was stored ───────────────────────────────────

@pytest.mark.parametrize("ok", [True, False])
def test_store_code_entity_reports_the_graph_write(mcp, monkeypatch, ok):
    graph = FakeGraph(ok)
    monkeypatch.setattr(mcp_server, "get_graph_store", lambda: graph)
    is_error, body = call("store_code_entity", {"name": "f", "entity_type": "function", "related_to": ["g"]})
    assert not is_error
    assert ("add_node", "f") in graph.calls  # the graph is really reached
    assert body["stored_in"] == (["neo4j", "mcp-sqlite"] if ok else ["mcp-sqlite"])
    assert body["relationships_created"] == (1 if ok else 0)


@pytest.mark.parametrize("ok", [True, False])
def test_link_entities_reports_the_graph_write(mcp, monkeypatch, ok):
    graph = FakeGraph(ok)
    monkeypatch.setattr(mcp_server, "get_graph_store", lambda: graph)
    _, body = call("link_entities", {"from_entity": "a", "to_entity": "b", "relationship": "USES"})
    assert graph.calls == [("rel", "a", "b")]
    assert body["stored_in"] == (["neo4j", "mcp-sqlite"] if ok else ["mcp-sqlite"])


@pytest.mark.parametrize("ok", [True, False])
def test_store_solution_reports_the_graph_write(mcp, monkeypatch, ok):
    graph = FakeGraph(ok)
    monkeypatch.setattr(mcp_server, "get_graph_store", lambda: graph)
    _, body = call("store_solution", {"problem": "p", "solution": "s"})
    assert sum(1 for c in graph.calls if c[0] == "add_node") == 2
    assert body["stored_in"] == (["neo4j", "mcp-sqlite"] if ok else ["mcp-sqlite"])


def test_memories_round_trip_through_the_mcp_store(mcp):
    _, stored = call("store_memory", {"content": "The project uses PostgreSQL 16"})
    assert stored["source"] == "mcp-sqlite"
    _, found = call("search_memories", {"query": "postgresql"})
    assert found["count"] == 1
    assert not hasattr(mcp_server, "get_memory_store")  # never opens the chat's Chroma folder


def test_no_result_claims_mongodb(mcp):
    source = (REPO / "mcp_server.py").read_text()
    assert "mongodb" not in source.lower()


# ── Crashes and silent no-ops ──────────────────────────────────────

def test_update_session_checkpoint_on_sqlite_path(mcp):
    # `datetime` used to be imported only inside other branches of call_tool, which
    # made it local to the whole function: this raised UnboundLocalError
    _, created = call("create_session", {"task_description": "t", "task_goal": "g", "plan_steps": ["a", "b"]})
    is_error, body = call("update_session", {"session_id": created["session_id"], "checkpoint": True})
    assert not is_error, body
    session = mcp_knowledge_db.get_mcp_knowledge_db().get_session(created["session_id"])
    assert len(session["checkpoints"]) == 1


def test_create_session_only_passes_supported_arguments(mcp, monkeypatch):
    seen = {}

    class Manager:
        async def create_session(self, user_id, task_description, task_goal="", plan_steps=None):
            seen.update(task_description=task_description)
            return pytypes.SimpleNamespace(id="s1", task_description=task_description, plan_steps=plan_steps or [])

    monkeypatch.setattr(mcp_server, "get_session_manager", lambda: Manager())
    _, body = call("create_session", {"task_description": "t", "task_goal": "g", "technologies": ["python"]})
    assert body["source"] == "json-file" and seen  # used to TypeError and fall back to SQLite


def test_find_skill_omits_empty_related_context(mcp):
    _, body = call("find_skill", {"query": "nothing stored yet"})
    assert "related_context" not in body


def test_find_skill_returns_related_context(mcp, monkeypatch):
    class Search:
        def find_relevant_context(self, task_description):  # no max_items parameter
            return f"context for {task_description}"

    monkeypatch.setattr(mcp_databases, "get_unified_search", lambda: Search())
    _, body = call("find_skill", {"query": "cors error"})
    assert body["related_context"] == "context for cors error"


def test_tool_calls_are_not_logged_as_user_history(mcp):
    call("store_memory", {"content": "something"})
    call("find_skill", {"query": "anything"})
    stats = mcp_databases.get_user_interactions_db().get_stats()
    assert stats["total_interactions"] == 0


def test_old_auto_logged_tool_calls_stay_out_of_searches(mcp):
    db = mcp_databases.get_user_interactions_db()
    db.add_interaction(user_message="Tool: store_memory(content=postgres password hunter2)", message_type="tool_call")
    db.add_interaction(user_message="How do I tune postgres?", message_type="question")
    for mode in (mcp_databases.SearchMode.KEYWORD, mcp_databases.SearchMode.SEMANTIC):
        found = [r["user_message"] for r in db.search("postgres", mode=mode)]
        assert found == ["How do I tune postgres?"], mode
    _, body = call("find_skill", {"query": "postgres"})
    assert "hunter2" not in json.dumps(body)


def test_stats_fallbacks_match_the_schema(mcp, monkeypatch):
    def broken():
        raise RuntimeError("primary store down")

    monkeypatch.setitem(sys.modules, "skills.skill_ab_testing",
                        pytypes.SimpleNamespace(get_skill_ab_tester=broken))
    monkeypatch.setitem(sys.modules, "skills.auto_skill_learner",
                        pytypes.SimpleNamespace(get_auto_skill_learner=broken))
    call("create_skill", {"name": "s", "description": "d", "triggers": ["t"], "solution_text": "x"})
    # used to fail on a column that doesn't exist (success_count)
    is_error, body = call("get_experiment_stats")
    assert not is_error and body["source"] == "sqlite", body
    # used to pass min_occurrences, which the function doesn't take
    is_error, body = call("get_auto_learning_status")
    assert not is_error and body["source"] == "sqlite", body


# ── Keywords ───────────────────────────────────────────────────────

def test_top_keywords_most_frequent_then_first_seen():
    assert mcp_knowledge_db.top_keywords(["b", "a", "b", "c", "a", "b"], 2) == ["b", "a"]
    assert mcp_knowledge_db.top_keywords(["x", "y", "z"], 2) == ["x", "y"]


def test_keyword_extraction_does_not_depend_on_hash_seed():
    text = " ".join(f"word{chr(97 + i)}{chr(97 + j)}" for i in range(6) for j in range(6)) + " cors cors"
    script = (
        "import sys; sys.path.insert(0, 'backend'); "
        "from mcp_knowledge_db import MCPKnowledgeDB; "
        f"print(MCPKnowledgeDB._extract_keywords(None, {text!r}))"
    )
    outputs = {
        subprocess.run([sys.executable, "-c", script], cwd=REPO, capture_output=True, text=True,
                       env={**os.environ, "PYTHONHASHSEED": seed}, check=True).stdout
        for seed in ("1", "2", "3")
    }
    assert len(outputs) == 1 and "cors" in outputs.pop()
