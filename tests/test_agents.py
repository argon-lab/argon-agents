"""Integration tests against a live Argon stack.

Requirements: the Argon API server on ARGON_API_URL (default
http://localhost:8080) backed by a replica-set MongoDB. CI fails when the stack is unreachable; local optional runs may skip.
"""

import os
import time
import uuid

import pytest
import requests

from argon_agents import ArgonClient, ArgonError

API_URL = os.environ.get("ARGON_API_URL", "http://localhost:8080")


def _stack_available() -> bool:
    try:
        return requests.get(f"{API_URL}/health", timeout=2).status_code == 200
    except requests.RequestException:
        return False


_available = _stack_available()
if not _available and os.environ.get("ARGON_REQUIRE_STACK") == "1":
    raise RuntimeError(f"required Argon API is unavailable: {API_URL}")

pytestmark = pytest.mark.skipif(
    not _available, reason=f"no Argon API server at {API_URL}"
)


@pytest.fixture()
def argon() -> ArgonClient:
    return ArgonClient(API_URL, token=os.environ.get("ARGON_API_TOKEN"))


@pytest.fixture()
def project(argon: ArgonClient) -> str:
    name = f"agents-test-{uuid.uuid4().hex[:8]}"
    argon.create_project(name)
    return name


def wait_for_diff(sandbox, min_changes: int, timeout: float = 20.0) -> dict:
    """Poll until the sandbox's ingested diff shows the expected changes."""
    deadline = time.time() + timeout
    while True:
        diff = sandbox.diff()
        if len(diff.get("changes") or []) >= min_changes:
            return diff
        assert time.time() < deadline, f"diff never reached {min_changes} changes: {diff}"
        time.sleep(0.3)


def test_sandbox_write_merge_undo(argon: ArgonClient, project: str):
    sandbox = argon.create_sandbox(project, ttl_minutes=15)
    assert sandbox.connection_string.startswith("mongodb://")
    assert sandbox.forked_from == "main"

    # Data plane: plain pymongo against the sandbox.
    db = sandbox.pymongo_database()
    db.notes.insert_one({"_id": "n1", "text": "hello from the agent"})
    db.notes.insert_one({"_id": "n2", "text": "scratch"})
    db.notes.delete_one({"_id": "n2"})

    diff = wait_for_diff(sandbox, 1)
    ids = {c["document_id"] for c in diff["changes"]}
    assert "n1" in ids

    # Merge the surviving work back.
    result = sandbox.merge()
    assert result["applied"] >= 1

    # It landed on main.
    info = argon.branch_info(project, "main")
    head = info["branch"]["head_lsn"]
    assert head > 0

    entries = argon.entries(project, "main")
    writes = [e["lsn"] for e in entries if e["operation"] == "put"]
    assert writes
    undo = argon.undo(project, "main", from_lsn=min(writes), dry_run=False)
    assert undo["deleted"] >= 1
    check = argon.create_sandbox(project, ttl_minutes=15)
    assert check.pymongo_database().notes.count_documents({}) == 0
    check.discard()

    sandbox.discard()
    with pytest.raises(ArgonError):
        argon.branch_info(project, sandbox.branch)


def test_merge_conflict_strategies(argon: ArgonClient, project: str):
    # Seed main through a temporary sandbox.
    seed = argon.create_sandbox(project, ttl_minutes=15)
    seed.pymongo_database().cfg.insert_one({"_id": "c", "v": "base"})
    wait_for_diff(seed, 1)
    seed.merge()
    seed.discard()

    # Both fork the same base BEFORE either merge; the conflict is mandatory.
    a = argon.create_sandbox(project, ttl_minutes=15)
    b = argon.create_sandbox(project, ttl_minutes=15)
    a.pymongo_database().cfg.update_one({"_id": "c"}, {"$set": {"v": "from-a"}})
    b.pymongo_database().cfg.update_one({"_id": "c"}, {"$set": {"v": "from-b"}})
    a.merge()
    plan = argon.merge_preview(project, b.branch)
    assert len(plan["conflicts"]) == 1
    with pytest.raises(ArgonError):
        argon.merge_apply(plan["id"])
    result = argon.merge_apply(plan["id"], strategy="theirs")
    assert result["conflicts_resolved"] == 1
    check = argon.create_sandbox(project, ttl_minutes=15)
    assert check.pymongo_database().cfg.find_one({"_id":"c"})["v"] == "from-b"
    check.discard()
    a.discard()
    b.discard()


def test_langgraph_checkpointer(argon: ArgonClient, project: str):
    langgraph_mongodb = pytest.importorskip("langgraph.checkpoint.mongodb")
    del langgraph_mongodb
    from langgraph.checkpoint.base import empty_checkpoint

    from argon_agents import ArgonCheckpointSaver

    saver = ArgonCheckpointSaver.from_sandbox(argon, project, ttl_minutes=15)
    config = {"configurable": {"thread_id": "t1", "checkpoint_ns": ""}}

    checkpoint = empty_checkpoint()
    saved_config = saver.put(config, checkpoint, {"source": "input", "step": -1}, {})
    assert saved_config["configurable"]["checkpoint_id"]

    fetched = saver.get_tuple(config)
    assert fetched is not None
    assert fetched.checkpoint["id"] == checkpoint["id"]

    # The checkpoints are ordinary versioned data: the diff sees them.
    diff = wait_for_diff(saver.sandbox, 1)
    collections = {c["collection"] for c in diff["changes"]}
    assert any("checkpoint" in c for c in collections)

    # Fork the whole memory state and verify the copy reads the checkpoint.
    forked = saver.fork(argon, ttl_minutes=15)
    fetched_fork = forked.get_tuple(config)
    assert fetched_fork is not None
    assert fetched_fork.checkpoint["id"] == checkpoint["id"]

    forked.discard()
    saver.discard()


def test_pinned_eval_dataset(argon: ArgonClient, project: str):
    # Author the dataset through a sandbox and merge it to main.
    seed = argon.create_sandbox(project, ttl_minutes=15)
    seed_db = seed.pymongo_database()
    seed_db.eval_cases.insert_many([{"_id": f"case-{i}", "input": i} for i in range(3)])
    wait_for_diff(seed, 1)
    seed.merge()
    seed.discard()

    # Pin it.
    pin = argon.create_pin(project, "eval-v1", note="three cases")
    assert pin["lsn"] > 0
    assert any(p["name"] == "eval-v1" for p in argon.list_pins(project))

    # The dataset moves on after the pin.
    later = argon.create_sandbox(project, ttl_minutes=15)
    later.pymongo_database().eval_cases.insert_one({"_id": "case-99", "input": 99})
    wait_for_diff(later, 1)
    later.merge()
    later.discard()

    # Every run forked from the pin sees exactly the pinned three cases.
    run = argon.sandbox_from_pin(project, "eval-v1", ttl_minutes=15)
    docs = list(run.pymongo_database().eval_cases.find())
    assert {d["_id"] for d in docs} == {"case-0", "case-1", "case-2"}
    run.discard()

    argon.delete_pin(project, "eval-v1")


def test_mem0_config_factory(argon: ArgonClient, project: str):
    from argon_agents import sandboxed_mem0_config

    config, sandbox = sandboxed_mem0_config(argon, project, ttl_minutes=15)
    assert config["provider"] == "mongodb"
    assert config["config"]["mongo_uri"] == sandbox.connection_string
    assert config["config"]["db_name"] == sandbox.database_name
    assert config["config"]["db_name"].startswith("argon_br_")
    sandbox.discard()


def test_langgraph_invoke_async_and_fork(argon: ArgonClient, project: str):
    import asyncio
    from typing import TypedDict
    from langgraph.graph import StateGraph, START, END
    from argon_agents import ArgonCheckpointSaver

    class State(TypedDict):
        value: int

    def build(saver):
        graph = StateGraph(State)
        graph.add_node("increment", lambda state: {"value": state["value"] + 1})
        graph.add_edge(START, "increment")
        graph.add_edge("increment", END)
        return graph.compile(checkpointer=saver)

    saver = ArgonCheckpointSaver.from_sandbox(argon, project, actor="agent:graph")
    graph = build(saver)
    config = {"configurable": {"thread_id": "workflow"}}
    assert graph.invoke({"value": 1}, config)["value"] == 2
    assert asyncio.run(graph.ainvoke({"value": 3}, config))["value"] == 4
    fork = saver.fork(argon)
    fork_graph = build(fork)
    assert fork_graph.get_state(config).values["value"] == 4
    assert fork_graph.invoke({"value": 8}, config)["value"] == 9
    assert graph.get_state(config).values["value"] == 4
    fork.discard()
    saver.discard()


def test_mem0_provider_real_document_roundtrip(argon: ArgonClient, project: str):
    # Real Mem0 insert/get/update/delete and real MongoDB/WAL. Only Atlas
    # search-index setup is replaced: plain mongod cannot run vector search.
    # This test does NOT claim semantic retrieval coverage.
    from mem0.vector_stores.mongodb import MongoDB
    from argon_agents import sandboxed_mem0_config

    class DocumentStore(MongoDB):
        def create_col(self):
            return self.db[self.collection_name]

    config, box = sandboxed_mem0_config(argon, project, embedding_model_dims=3)
    store = DocumentStore(**config["config"])
    store.insert([[1.0, 0.0, 0.0]], [{"data": "agent memory", "user_id":"test"}], ["memory-1"])
    assert store.get("memory-1").payload["data"] == "agent memory"
    box.diff()
    store.update("memory-1", payload={"data": "updated memory"})
    assert store.get("memory-1").payload["data"] == "updated memory"
    box.diff()
    box.merge()
    check = argon.create_sandbox(project)
    assert check.pymongo_database().mem0.find_one({"_id":"memory-1"})["payload"]["data"] == "updated memory"
    store.delete("memory-1")
    assert store.get("memory-1") is None
    box.diff()
    assert any(e["operation"] == "delete" for e in argon.entries(project, box.branch))
    check.discard()
    box.discard()
    store.client.close()
