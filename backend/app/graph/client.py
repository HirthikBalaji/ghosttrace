"""FalkorDB access. One graph per workspace (key `ws:<workspace_id>`).

Agents and read paths use `ro()` (GRAPH.RO_QUERY — the server rejects writes). Writes go only through
repository methods via `rw()`. Every call carries a server-side timeout. Query text is always a module
constant; values travel as parameters.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

from falkordb import FalkorDB

from app.config import get_settings

WORKSPACE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


class WorkspaceError(ValueError):
    pass


def graph_key(workspace_id: str) -> str:
    if not WORKSPACE_RE.fullmatch(workspace_id or ""):
        raise WorkspaceError("invalid workspace id")
    return f"ws:{workspace_id}"


class GraphClient:
    def __init__(
        self, host: str | None = None, port: int | None = None, password: str | None = None, timeout_ms: int | None = None
    ):
        s = get_settings()
        self.timeout_ms = timeout_ms or s.query_timeout_ms
        self.db = FalkorDB(
            host=host or s.falkordb_host,
            port=port or s.falkordb_port,
            password=password if password is not None else s.falkordb_password,
        )
        self._lock = threading.Lock()

    def ping(self) -> bool:
        try:
            return bool(self.db.connection.ping())
        except Exception:
            return False

    def _g(self, workspace_id: str) -> Any:
        return self.db.select_graph(graph_key(workspace_id))

    def ro(
        self, workspace_id: str, query: str, params: dict[str, Any] | None = None, timeout_ms: int | None = None
    ) -> list[list[Any]]:
        res = self._g(workspace_id).ro_query(query, params=params or {}, timeout=timeout_ms or self.timeout_ms)
        return list(res.result_set)

    def rw(
        self, workspace_id: str, query: str, params: dict[str, Any] | None = None, timeout_ms: int | None = None
    ) -> list[list[Any]]:
        res = self._g(workspace_id).query(query, params=params or {}, timeout=timeout_ms or self.timeout_ms)
        return list(res.result_set)

    def profile(self, workspace_id: str, query: str, params: dict[str, Any] | None = None) -> str:
        return "\n".join(self._g(workspace_id).profile(query, params=params or {}).plan)

    def explain(self, workspace_id: str, query: str, params: dict[str, Any] | None = None) -> str:
        return "\n".join(self._g(workspace_id).explain(query, params=params or {}).plan)

    def compact_aof(self, wait_s: float = 30.0) -> bool:
        """BGREWRITEAOF and wait for it; a no-op (False) when AOF is disabled or the command is not permitted."""
        conn = self.db.connection
        try:
            if conn.config_get("appendonly").get("appendonly") != "yes":
                return False
            conn.bgrewriteaof()
        except Exception as exc:
            if "already in progress" not in str(exc).lower():
                return False
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            info = conn.info("persistence")
            if not info.get("aof_rewrite_in_progress") and not info.get("aof_rewrite_scheduled"):
                return True
            time.sleep(0.1)
        return False

    def list_workspaces(self) -> list[str]:
        return sorted(k[3:] for k in self.db.list_graphs() if k.startswith("ws:"))

    def drop_workspace(self, workspace_id: str) -> None:
        key = graph_key(workspace_id)
        if key in self.db.list_graphs():
            self.db.select_graph(key).delete()

    def copy_workspace(self, src: str, dst: str) -> None:
        self._g(src).copy(graph_key(dst))


_client: GraphClient | None = None
_client_lock = threading.Lock()


def get_client() -> GraphClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = GraphClient()
        return _client


def set_client(c: GraphClient | None) -> None:
    global _client
    with _client_lock:
        _client = c
