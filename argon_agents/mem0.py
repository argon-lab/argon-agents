"""Sandboxed Mem0 configuration on versioned MongoDB.

Mem0 speaks MongoDB natively; what it lacks is a way to experiment on a
copy of an agent's memory and merge or reject the outcome. This factory
provisions an Argon sandbox and returns a Mem0 ``config`` dict whose
MongoDB vector store points at it — plus the sandbox handle for
``merge()`` / ``discard()`` and TTL-based cleanup.
"""

from __future__ import annotations

from typing import Optional, Tuple

from .client import ArgonClient, Sandbox


def sandboxed_mem0_config(
    argon: ArgonClient,
    project: str,
    from_branch: str = "main",
    collection_name: str = "mem0",
    embedding_model_dims: int = 1536,
    ttl_minutes: int = 60,
    name: Optional[str] = None,
    actor: Optional[str] = None,
) -> Tuple[dict, Sandbox]:
    """Provision a sandbox and return (mem0_config, sandbox).

    Mem0's MongoDB vector provider requires Atlas Search (or a compatible
    MongoDB Search deployment). A plain replica set supports versioned
    documents but not semantic vector retrieval. Search indexes must be
    provisioned separately on each physical branch; they are not WAL data.

    Usage::

        config, sandbox = sandboxed_mem0_config(argon, "my-project")
        memory = Memory.from_config({"vector_store": config, ...})
        ...  # let the agent read and write memories
        sandbox.merge()      # adopt the new memories
        # or sandbox.discard(), or just let the TTL reclaim it
    """
    sandbox = argon.create_sandbox(
        project, from_branch=from_branch, name=name, ttl_minutes=ttl_minutes, actor=actor
    )
    db = sandbox.pymongo_database()
    if collection_name not in db.list_collection_names():
        db.create_collection(collection_name, changeStreamPreAndPostImages={"enabled": True})
    db.command("collMod", collection_name, changeStreamPreAndPostImages={"enabled": True})
    config = {
        "provider": "mongodb",
        "config": {
            "mongo_uri": sandbox.connection_string,
            "db_name": sandbox.database_name,
            "collection_name": collection_name,
            "embedding_model_dims": embedding_model_dims,
        },
    }
    return config, sandbox
