"""Argon adapters for AI agent frameworks.

Argon versions MongoDB the way Git versions code. These adapters give
agent frameworks the two things they are missing: a disposable, isolated
copy of state to work against (a sandbox with a TTL), and an undo/merge
story for whatever the agent did to it.
"""

from .client import ArgonClient, ArgonError, Sandbox
from .mem0 import sandboxed_mem0_config

__all__ = ["ArgonClient", "ArgonError", "Sandbox", "sandboxed_mem0_config"]

try:  # langgraph extras are optional
    from .langgraph import ArgonCheckpointSaver  # noqa: F401

    __all__.append("ArgonCheckpointSaver")
except ImportError:  # pragma: no cover
    pass
