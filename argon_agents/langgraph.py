"""LangGraph checkpointing on versioned, sandboxed MongoDB.

``ArgonCheckpointSaver`` is the official ``langgraph-checkpoint-mongodb``
saver pointed at an Argon branch, plus the operations MongoDB alone cannot
give you:

- ``from_sandbox``: fork the whole memory state into a disposable,
  TTL-stamped copy and checkpoint an agent against it — production
  checkpoints are never at risk.
- ``fork``: branch the entire checkpoint history (every thread) at its
  current state, cheaply, and get an independent saver for the copy.
- ``merge`` / ``discard`` on the underlying sandbox to adopt or reject
  whatever the agent's run produced.

LangGraph's own checkpoint ids give you step-level rewind *within* a
thread; Argon gives you branch-level fork/undo/audit *across* the whole
store.
"""

from __future__ import annotations

from typing import Optional

from langgraph.checkpoint.mongodb import MongoDBSaver
from pymongo import MongoClient

from .client import ArgonClient, Sandbox


class ArgonCheckpointSaver(MongoDBSaver):
    """The official MongoDB checkpointer, running on an Argon branch."""

    def __init__(self, connection_string: str, *, sandbox: Optional[Sandbox] = None, **kwargs):
        client = MongoClient(connection_string)
        db_name = client.get_default_database().name
        # Prepare collections before the saver can upsert rapidly. MongoDB
        # cannot provide exact images retroactively for a newly created collection.
        db = client[db_name]
        for name in (kwargs.get("checkpoint_collection_name", "checkpoints"), kwargs.get("writes_collection_name", "checkpoint_writes")):
            if name not in db.list_collection_names():
                from pymongo.errors import CollectionInvalid
                try:
                    db.create_collection(name, changeStreamPreAndPostImages={"enabled": True})
                except CollectionInvalid:
                    pass
            db.command("collMod", name, changeStreamPreAndPostImages={"enabled": True})
        super().__init__(client, db_name=db_name, **kwargs)
        self.sandbox = sandbox

    # -- constructors -------------------------------------------------------

    @classmethod
    def from_sandbox(
        cls,
        argon: ArgonClient,
        project: str,
        from_branch: str = "main",
        name: Optional[str] = None,
        ttl_minutes: int = 60,
        actor: Optional[str] = None,
        **kwargs,
    ) -> "ArgonCheckpointSaver":
        """Fork a sandbox and checkpoint against it.

        The saver's ``sandbox`` attribute exposes ``merge()`` and
        ``discard()``; the TTL reclaims the sandbox if neither happens.
        """
        sandbox = argon.create_sandbox(
            project, from_branch=from_branch, name=name, ttl_minutes=ttl_minutes, actor=actor
        )
        return cls(sandbox.connection_string, sandbox=sandbox, **kwargs)

    @classmethod
    def for_branch(cls, argon: ArgonClient, project: str, branch: str = "main", **kwargs):
        """Checkpoint against a (checked-out) long-lived branch."""
        return cls(argon.checkout(project, branch), **kwargs)

    # -- Argon superpowers ---------------------------------------------------

    def fork(
        self,
        argon: ArgonClient,
        name: Optional[str] = None,
        ttl_minutes: int = 60,
    ) -> "ArgonCheckpointSaver":
        """Fork the entire checkpoint store (all threads) at its current
        state into a new sandbox and return a saver for the copy."""
        if self.sandbox is None:
            raise ValueError("fork() needs a saver created via from_sandbox()")
        self.sandbox.diff()  # the API synchronizes acknowledged writes before forking
        return self.from_sandbox(
            argon,
            self.sandbox.project,
            from_branch=self.sandbox.branch,
            name=name,
            ttl_minutes=ttl_minutes,
        )

    def merge(self, strategy: Optional[str] = None) -> dict:
        """Adopt the sandboxed checkpoints into the parent branch."""
        if self.sandbox is None:
            raise ValueError("merge() needs a saver created via from_sandbox()")
        return self.sandbox.merge(strategy)

    def discard(self) -> None:
        """Throw the sandboxed run away and reclaim its storage."""
        if self.sandbox is None:
            raise ValueError("discard() needs a saver created via from_sandbox()")
        self.sandbox.discard()
