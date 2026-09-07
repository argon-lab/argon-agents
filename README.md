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
   merge it back (with conflict strategies), undo any range, or just let
   the TTL reclaim it.

## Install

The 0.2.0 source release candidate targets Argon 2.1.0 and its exact capture
guarantees. Until those versions are published, install this checkout with
`pip install -e ".[dev]"` and run the matching engine checkout. The commands
below install the currently published package.

```bash
pip install argon-agents            # client + Mem0 factory
pip install "argon-agents[langgraph]"  # + the LangGraph checkpointer
```

Requires a running [Argon API server](https://github.com/argon-lab/argon)
(`cd api && go run .`) backed by MongoDB 7 as a replica set. The managed
API waits for capture readiness, synchronizes versioned operations and
sweeps expired sandboxes every minute. Stop native writers before release
or discard. The public hosted demo does not expose native connection strings.

## The client

```python
from argon_agents import ArgonClient

argon = ArgonClient("http://localhost:8080")
argon.create_project("support-bot")

sandbox = argon.create_sandbox("support-bot", ttl_minutes=60, actor="agent:run-42")
db = sandbox.pymongo_database()        # plain pymongo, isolated copy
db.tickets.insert_one({"_id": "t1", "status": "resolved"})

print(sandbox.diff())                  # what the agent changed
sandbox.merge()                        # adopt it — or sandbox.discard()
```

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
saver = ArgonCheckpointSaver.from_sandbox(argon, "support-bot", ttl_minutes=60)

graph = builder.compile(checkpointer=saver)   # any LangGraph graph
graph.invoke(input, {"configurable": {"thread_id": "user-42"}})

saver.merge()          # keep the run's checkpoints
# saver.discard()      # or reject them
# saver.fork(argon)    # or branch the entire memory state and try both
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
config, sandbox = sandboxed_mem0_config(argon, "support-bot")
memory = Memory.from_config({"vector_store": config})

# ... let the agent read/write memories ...
sandbox.merge()   # adopt the new memories, or discard(), or let the TTL run
```

## Reproducible evals: dataset pins

A pin is a named, immutable reference to a branch state that survives
garbage collection and resets forever. Pin the eval dataset once; fork a
fresh sandbox from the pin for every run; every run starts identical:

```python
argon.create_pin("my-project", "eval-v1", note="golden dataset")

run = argon.sandbox_from_pin("my-project", "eval-v1", ttl_minutes=30)
# ... run the eval against run.connection_string ...
run.discard()          # the pin itself is untouched — fork again anytime
```

## Tests

```bash
pip install -e ".[dev]"
ARGON_REQUIRE_STACK=1 MEM0_TELEMETRY=false pytest
```

CI checks Python 3.10, 3.12 and 3.14 and fails if the stack is unavailable.
The dispatch input `engine_ref` accepts an exact engine commit or release tag;
the resolved SHA is logged. Tests exercise mandatory conflicts, actual undo,
LangGraph invoke/ainvoke and fork isolation, pinned input, and Mem0's real
MongoDB insert/get/update/delete methods. The Mem0 document test bypasses
Atlas index creation only; it does not claim semantic-search coverage on
plain MongoDB.
