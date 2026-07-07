"""REST client for the Argon control plane.

The control plane (this client) manages projects, branches, sandboxes,
merges and undos over the Argon API server. The data plane is native
MongoDB: sandboxes and checked-out branches hand back ordinary connection
strings, and the API server captures every write into versioned history
through the branch's change stream.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Optional

import requests


class ArgonError(RuntimeError):
    """An Argon control-plane call failed."""

    def __init__(self, status: int, message: str):
        super().__init__(f"{message} (HTTP {status})")
        self.status = status


class ArgonClient:
    """Client for the Argon REST API (default http://localhost:8080)."""

    def __init__(self, api_url: str = "http://localhost:8080", timeout: float = 30.0):
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()

    # -- plumbing ---------------------------------------------------------

    def _call(self, method: str, path: str, json: Optional[dict] = None) -> dict:
        response = self._session.request(
            method, f"{self.api_url}/api/v1{path}", json=json or {}, timeout=self.timeout
        )
        body: dict[str, Any] = {}
        if response.content:
            try:
                body = response.json()
            except ValueError:
                pass
        if response.status_code >= 400:
            raise ArgonError(response.status_code, body.get("error", response.text))
        return body

    # -- projects & branches ----------------------------------------------

    def create_project(self, name: str) -> dict:
        return self._call("POST", "/projects", {"name": name})

    def get_or_create_project(self, name: str) -> None:
        try:
            self.create_project(name)
        except ArgonError as exc:
            if exc.status != 409:
                raise

    def list_branches(self, project: str) -> list[dict]:
        return self._call("GET", f"/projects/{project}/branches")["branches"]

    def branch_info(self, project: str, branch: str) -> dict:
        return self._call("GET", f"/projects/{project}/branches/{branch}")

    def create_branch(self, project: str, name: str, from_branch: str = "main") -> dict:
        return self._call(
            "POST", f"/projects/{project}/branches", {"name": name, "from": from_branch}
        )

    def delete_branch(self, project: str, branch: str) -> None:
        self._call("DELETE", f"/projects/{project}/branches/{branch}")

    def checkout(self, project: str, branch: str) -> str:
        """Materialize a branch and return its MongoDB connection string."""
        return self._call("POST", f"/projects/{project}/branches/{branch}/checkout")[
            "connection_string"
        ]

    # -- sandboxes ----------------------------------------------------------

    def create_sandbox(
        self,
        project: str,
        from_branch: str = "main",
        name: Optional[str] = None,
        ttl_minutes: int = 60,
    ) -> "Sandbox":
        body = {"from": from_branch, "ttl_minutes": ttl_minutes}
        if name:
            body["name"] = name
        resp = self._call("POST", f"/projects/{project}/sandboxes", body)
        return Sandbox(
            _client=self,
            project=project,
            branch=resp["branch"],
            connection_string=resp["connection_string"],
            expires_at=resp["expires_at"],
            forked_from=resp["forked_from"],
        )

    # -- pins (reproducible eval datasets) -----------------------------------

    def create_pin(
        self,
        project: str,
        name: str,
        branch: str = "main",
        lsn: Optional[int] = None,
        note: Optional[str] = None,
    ) -> dict:
        """Pin a branch state under a name: a named, immutable dataset
        reference that survives garbage collection and resets forever.
        Defaults to the branch's current head."""
        body: dict[str, Any] = {"name": name, "branch": branch}
        if lsn is not None:
            body["lsn"] = lsn
        if note:
            body["note"] = note
        return self._call("POST", f"/projects/{project}/pins", body)

    def list_pins(self, project: str) -> list[dict]:
        return self._call("GET", f"/projects/{project}/pins")["pins"]

    def delete_pin(self, project: str, name: str) -> None:
        self._call("DELETE", f"/projects/{project}/pins/{name}")

    def sandbox_from_pin(
        self,
        project: str,
        pin: str,
        name: Optional[str] = None,
        ttl_minutes: int = 60,
    ) -> "Sandbox":
        """Fork a TTL sandbox that starts at exactly the pinned state —
        the reproducible-eval workflow: pin the dataset once, fork a fresh
        sandbox from it for every run."""
        body: dict[str, Any] = {"ttl_minutes": ttl_minutes}
        if name:
            body["name"] = name
        resp = self._call("POST", f"/projects/{project}/pins/{pin}/sandboxes", body)
        return Sandbox(
            _client=self,
            project=project,
            branch=resp["branch"],
            connection_string=resp["connection_string"],
            expires_at=resp["expires_at"],
            forked_from=resp["forked_from"],
        )

    # -- diff / merge / undo ------------------------------------------------

    def diff(self, project: str, branch: str) -> dict:
        return self._call("GET", f"/projects/{project}/branches/{branch}/diff")

    def merge_preview(self, project: str, branch: str) -> dict:
        return self._call("POST", f"/projects/{project}/branches/{branch}/merge-preview")

    def merge_apply(self, plan_id: str, strategy: Optional[str] = None) -> dict:
        body = {"strategy": strategy} if strategy else {}
        return self._call("POST", f"/merge-plans/{plan_id}/apply", body)

    def merge(self, project: str, branch: str, strategy: Optional[str] = None) -> dict:
        """Preview and apply in one step."""
        plan = self.merge_preview(project, branch)
        return self.merge_apply(plan["id"], strategy)

    def undo(
        self,
        project: str,
        branch: str,
        from_lsn: int,
        to_lsn: Optional[int] = None,
        actor: Optional[str] = None,
        dry_run: bool = False,
    ) -> dict:
        body: dict[str, Any] = {"from_lsn": from_lsn, "dry_run": dry_run}
        if to_lsn is not None:
            body["to_lsn"] = to_lsn
        if actor:
            body["actor"] = actor
        return self._call("POST", f"/projects/{project}/branches/{branch}/undo", body)

    def snapshot(self, project: str, branch: str) -> dict:
        return self._call("POST", f"/projects/{project}/branches/{branch}/snapshots")

    def time_travel_info(self, project: str, branch: str) -> dict:
        return self._call("GET", f"/projects/{project}/branches/{branch}/time-travel")


@dataclass
class Sandbox:
    """A disposable, versioned copy of a branch, with a TTL.

    Point any MongoDB client at ``connection_string``; every write becomes
    versioned history. ``merge()`` brings the work back to the parent,
    ``discard()`` throws it away, the TTL reclaims whatever is left.
    """

    project: str
    branch: str
    connection_string: str
    expires_at: str
    forked_from: str
    _client: ArgonClient = field(repr=False, default=None)

    @property
    def database_name(self) -> str:
        """The physical database name inside the connection string."""
        path = self.connection_string.split("://", 1)[1]
        db = path.split("/", 1)[1] if "/" in path else ""
        return db.split("?", 1)[0]

    def pymongo_database(self):
        """A pymongo Database handle for the sandbox (lazy import)."""
        from pymongo import MongoClient

        return MongoClient(self.connection_string).get_default_database()

    def diff(self) -> dict:
        return self._client.diff(self.project, self.branch)

    def merge(self, strategy: Optional[str] = None) -> dict:
        return self._client.merge(self.project, self.branch, strategy)

    def keep_days_note(self) -> str:  # pragma: no cover - convenience only
        return f"expires {self.expires_at}"

    def discard(self) -> None:
        self._client.delete_branch(self.project, self.branch)

    @property
    def expires(self) -> datetime.datetime:
        return datetime.datetime.fromisoformat(self.expires_at.replace("Z", "+00:00"))
