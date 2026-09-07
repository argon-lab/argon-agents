"""A real database review workflow, with no LLM or paid API dependency.

Run the Argon API against a MongoDB 7 replica set, then:
  pip install -e .
  python examples/two_agent_review.py
Set ARGON_API_URL and optionally ARGON_API_TOKEN for your local deployment.
The hosted anonymous demo intentionally does not grant native MongoDB access.
"""

import json
import os
import uuid

from argon_agents import ArgonClient


def run_review(argon, project):
    argon.create_project(project)
    seed = argon.create_sandbox(project, name="seed", actor="setup")
    seed.pymongo_database().orders.insert_one({"_id": "order-1", "price": 49, "status": "pending"})
    seed.merge()
    seed.discard()
    pin = argon.create_pin(project, "baseline", note="Identical input for both agent runs")
    planner = argon.sandbox_from_pin(project, "baseline", name="planner", actor="agent:planner")
    executor = argon.sandbox_from_pin(project, "baseline", name="executor", actor="agent:executor")
    a, b = planner.pymongo_database(), executor.pymongo_database()
    assert a.orders.find_one()["price"] == b.orders.find_one()["price"] == 49
    a.orders.update_one({"_id": "order-1"}, {"$set": {"price": 44}})
    b.orders.update_one({"_id": "order-1"}, {"$set": {"price": 1}})
    approved = argon.merge_preview(project, planner.branch)
    assert not approved["conflicts"]
    argon.merge_apply(approved["id"])
    rejected = argon.merge_preview(project, executor.branch)
    assert len(rejected["conflicts"]) == 1
    executor_writes = [e["lsn"] for e in argon.entries(project, executor.branch)
                       if e.get("actor") == "agent:executor" and e["operation"] == "put"]
    assert executor_writes
    argon.undo(project, executor.branch, from_lsn=min(executor_writes), actor="agent:executor")
    assert b.orders.find_one()["price"] == 49
    executor.discard()
    adopted = argon.create_sandbox(project, name="verify-adopted")
    assert adopted.pymongo_database().orders.find_one()["price"] == 44
    adopted.discard()
    merge_writes = [e["lsn"] for e in argon.entries(project, "main")
                    if e.get("actor") == "merge:planner" and e["operation"] == "put"]
    assert merge_writes
    argon.undo(project, "main", from_lsn=min(merge_writes), to_lsn=max(merge_writes))
    restored = argon.create_sandbox(project, name="verify-undo")
    assert restored.pymongo_database().orders.find_one()["price"] == 49
    restored.discard()
    planner.discard()
    argon.delete_pin(project, "baseline")
    return {"project": project, "pin_lsn": pin["lsn"], "reviewed_price": 44,
            "conflicts": len(rejected["conflicts"]), "restored_price": 49}


if __name__ == "__main__":
    client = ArgonClient(os.environ.get("ARGON_API_URL", "http://localhost:8080"),
                         token=os.environ.get("ARGON_API_TOKEN"))
    print(json.dumps(run_review(client, "review-" + uuid.uuid4().hex[:8]), indent=2))
