# argon-agents

[![PyPI](https://img.shields.io/pypi/v/argon-agents?logo=pypi&label=PyPI)](https://pypi.org/project/argon-agents/)
[![CI](https://github.com/argon-lab/argon-agents/actions/workflows/ci.yml/badge.svg)](https://github.com/argon-lab/argon-agents/actions/workflows/ci.yml)

Argon adapters for AI agent frameworks: **sandboxed, versioned MongoDB**
for LangGraph and Mem0.

[Argon](https://github.com/argon-lab/argon) versions MongoDB the way Git
versions code — branch, time-travel, diff, merge, undo. This package gives
agent frameworks the two things plain MongoDB can't:

1. **A disposable copy of state to work against.** Fork a sandbox with a
   TTL, point the agent at an ordinary connection string, and production
   data stays isolated until you explicitly merge the reviewed changes.
2. **An adopt-or-reject story for what the agent did.** Diff the sandbox,
   preview a merge and explicitly apply its reviewed plan, undo supported
   captured ranges within retained history, or let the running API reclaim
   the sandbox after its TTL.

## Install

SDK 0.2.0 requires Argon 2.1.1 or a compatible later 2.1 patch. We recommend
[Argon 2.1.2](https://github.com/argon-lab/argon/blob/v2.1.2/CHANGELOG.md): REST
branch creation synchronizes the parent's captured writes before forking,
imports require an explicitly quiesced source, and Go consumers have valid
`/v2` module paths. Version 2.1.1 remains compatible; 2.1.0 has a shutdown bug.
Release wheels and source archives are available
from [GitHub Releases](https://github.com/argon-lab/argon-agents/releases).

```bash
python3 -m pip install 'argon-agents==0.2.0'
python3 -m pip install 'argon-agents[langgraph]==0.2.0'
```

These commands install SDK 0.2.0 from PyPI. The release workflow verifies the
registry and installs its wheel in a fresh environment before declaring a
publication complete. See [release operations](RELEASING.md).

Requires a running [Argon API server](https://github.com/argon-lab/argon)
(`cd api && go run .`) backed by MongoDB 7 as a replica set. The managed
API waits for capture readiness, synchronizes versioned operations and
sweeps expired sandboxes every minute. Stop native writers before release
or discard. The public hosted demo does not expose native connection strings.

## The client

```python
from argon_agents import ArgonClient

argon = ArgonClient("http://localhost:8080")
argon.get_or_create_project("support-bot")

sandbox = argon.create_sandbox("support-bot", ttl_minutes=60, actor="agent:run-42")
db = sandbox.pymongo_database()        # plain pymongo, isolated copy
db.tickets.insert_one({"_id": "t1", "status": "resolved"})

print(sandbox.diff())                  # what the agent changed
plan = argon.merge_preview("support-bot", sandbox.branch)
print(plan)                            # inspect changes and conflicts
# After reviewing this exact plan, explicitly apply it:
# argon.merge_apply(plan["id"])
# Or reject the proposal with sandbox.discard().
```

`merge_preview` creates a plan without changing the target branch. Review that
plan before calling `merge_apply(plan["id"])`; a stale plan must be previewed
again. The convenience methods `sandbox.merge()` and `saver.merge()` preview
and apply immediately, with no pause or approval step. Use them only when
that automatic application is intentional in your own workflow.

The actor labels the entire branch/run, not individual MongoDB clients.
Use a separate sandbox for each agent. For a protected API, pass
`ArgonClient(api_url, token=...)`; never give an agent a production service
credential. Inspect `argon.capture_status()` if capture reports degraded.

New application collections must enable `changeStreamPreAndPostImages`
before rapid updates; the LangGraph and Mem0 adapters do this themselves.
An update without exact images or unsupported drop/rename stops capture
with an explicit degraded status. Retention limits history unless pinned.

## Run the complete review workflow

The [two-agent example](examples/two_agent_review.py) uses ordinary pymongo
and no paid model: both agents start from one pin, propose different order
prices, merge the reviewed result, surface the competing conflict, discard
it, then undo the adopted change and assert the original data is restored.

```bash
ARGON_API_URL=http://localhost:8080 python examples/two_agent_review.py
```

## LangGraph

```python
from argon_agents import ArgonClient, ArgonCheckpointSaver

argon = ArgonClient()
argon.get_or_create_project("support-bot")
saver = ArgonCheckpointSaver.from_sandbox(argon, "support-bot", ttl_minutes=60)

graph = builder.compile(checkpointer=saver)   # any LangGraph graph
graph.invoke(input, {"configurable": {"thread_id": "user-42"}})

plan = argon.merge_preview("support-bot", saver.sandbox.branch)
print(plan)                           # review the checkpoint-store changes
# After review: argon.merge_apply(plan["id"])
# Or saver.discard() to reject, or saver.fork(argon) to try another branch.
```

`ArgonCheckpointSaver` *is* the official `langgraph-checkpoint-mongodb`
saver — same wire format, same semantics — running on an Argon branch.
LangGraph's checkpoint ids give step-level rewind within a thread; Argon
adds branch-level fork/merge/undo/audit across the whole store.

## Mem0

Mem0 speaks MongoDB natively; Argon supplies the versioned sandbox:

**Semantic search requires MongoDB Atlas Search or a compatible Search
deployment.** A plain replica set supports versioned document storage but
does not implement `$vectorSearch`. Provision search indexes separately
for each branch; Argon versions documents, not search-index definitions.
Configure the LLM/embedder required by Mem0 before running `Memory`.

```python
from argon_agents import ArgonClient, sandboxed_mem0_config
from mem0 import Memory

argon = ArgonClient()
argon.get_or_create_project("support-bot")
config, sandbox = sandboxed_mem0_config(argon, "support-bot")
memory = Memory.from_config({"vector_store": config})

# ... let the agent read/write memories ...
plan = argon.merge_preview("support-bot", sandbox.branch)
print(plan)                           # review the memory changes
# After review: argon.merge_apply(plan["id"])
# Or sandbox.discard(); the running API also sweeps expired sandboxes.
```

## Reproducible evals: dataset pins

A pin is a named, immutable reference to a branch state. While the pin exists,
it protects the history it references from garbage collection and resets.
Deleting the pin removes that protection; keep independent backups for loss
of the underlying deployment. Pin the eval dataset once, then fork a fresh
sandbox from the same retained pin for each run:

```python
argon.create_pin("my-project", "eval-v1", note="golden dataset")

run = argon.sandbox_from_pin("my-project", "eval-v1", ttl_minutes=30)
# ... run the eval against run.connection_string ...
run.discard()          # the pin remains; fork it again while it exists
```

## Tests

```bash
pip install -e ".[dev]"
ARGON_REQUIRE_STACK=1 MEM0_TELEMETRY=false pytest
```

CI checks Python 3.10, 3.12 and 3.14 against Argon v2.1.2 and fails if the
stack is unavailable.
The dispatch input `engine_ref` accepts an exact engine commit or release tag;
the resolved SHA is logged. Tests exercise mandatory conflicts, actual undo,
LangGraph invoke/ainvoke and fork isolation, pinned input, and Mem0's real
MongoDB insert/get/update/delete methods. The Mem0 document test bypasses
Atlas index creation only; it does not claim semantic-search coverage on
plain MongoDB.
