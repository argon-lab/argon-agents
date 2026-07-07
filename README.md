# argon-agents

Argon adapters for AI agent frameworks: **sandboxed, versioned MongoDB**
for LangGraph and Mem0.

[Argon](https://github.com/argon-lab/argon) versions MongoDB the way Git
versions code — branch, time-travel, diff, merge, undo. This package gives
agent frameworks the two things plain MongoDB can't:

1. **A disposable copy of state to work against.** Fork a sandbox with a
   TTL, point the agent at an ordinary connection string, and production
   data is never at risk.
2. **An adopt-or-reject story for what the agent did.** Diff the sandbox,
   merge it back (with conflict strategies), undo any range, or just let
   the TTL reclaim it.

## Install

```bash
pip install argon-agents            # client + Mem0 factory
pip install "argon-agents[langgraph]"  # + the LangGraph checkpointer
```

Requires a running [Argon API server](https://github.com/argon-lab/argon)
(`cd api && go run .`) backed by a MongoDB replica set.

## The client

```python
from argon_agents import ArgonClient

argon = ArgonClient("http://localhost:8080")
argon.create_project("support-bot")

sandbox = argon.create_sandbox("support-bot", ttl_minutes=60)
db = sandbox.pymongo_database()        # plain pymongo, isolated copy
db.tickets.insert_one({"_id": "t1", "status": "resolved"})

print(sandbox.diff())                  # what the agent changed
sandbox.merge()                        # adopt it — or sandbox.discard()
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
pytest              # skips itself unless an Argon stack is reachable
```

CI builds the engine from `argon-lab/argon@master`, starts a replica-set
MongoDB and the API server, and runs the full suite.
