"""Versioned, idempotent schema migrations for a workspace graph."""

from __future__ import annotations

import time
from collections.abc import Callable

from app.graph.client import GraphClient
from app.graph.queries import SCHEMA_VERSION_GET, SCHEMA_VERSION_SET
from app.model import ALL_FACT_EDGE_TYPES

NODE_INDEXES = [
    ("Entity", "id"), ("Entity", "workspace_id"), ("SourceRecord", "source_id"), ("SourceRecord", "workspace_id"),
    ("Investigation", "id"), ("AgentTask", "task_id"), ("AgentTask", "idempotency_key"), ("Memory", "memory_id"),
    ("Memory", "workspace_id"), ("AuditEvent", "investigation_id"), ("Certificate", "id"), ("Plan", "id"),
    ("Hypothesis", "id"), ("AgentOutput", "id"), ("SchemaVersion", "version"), ("Workspace", "id"),
]
UNIQUE = [("Entity", "id"), ("SourceRecord", "source_id"), ("Investigation", "id"), ("AgentTask", "task_id"),
          ("AgentTask", "idempotency_key"), ("Memory", "memory_id")]
EDGE_INDEX_PROPS = ("edge_id", "tx_from", "valid_from", "workspace_id")


def _ignore_exists(fn: Callable[[], object]) -> None:
    try:
        fn()
    except Exception as exc:  # FalkorDB raises ResponseError for duplicates
        msg = str(exc).lower()
        if "already" not in msg and "exists" not in msg:
            raise


def migration_1(client: GraphClient, ws: str) -> None:
    g = client._g(ws)
    for label, prop in NODE_INDEXES:
        _ignore_exists(lambda label=label, prop=prop: g.create_node_range_index(label, prop))
    for t in ALL_FACT_EDGE_TYPES:
        for prop in EDGE_INDEX_PROPS:
            _ignore_exists(lambda t=t, prop=prop: g.create_edge_range_index(t, prop))
    for label, prop in UNIQUE:
        _ignore_exists(lambda label=label, prop=prop: g.create_node_unique_constraint(label, prop))


MIGRATIONS: list[tuple[int, Callable[[GraphClient, str], None]]] = [(1, migration_1)]
CURRENT_SCHEMA_VERSION = MIGRATIONS[-1][0]


def current_version(client: GraphClient, ws: str) -> int:
    rows = client.ro(ws, SCHEMA_VERSION_GET) if ws in client.list_workspaces() else [[None]]
    return int(rows[0][0] or 0) if rows else 0


def migrate(client: GraphClient, ws: str) -> list[int]:
    """Apply pending migrations in order; safe to call repeatedly."""
    applied = []
    have = current_version(client, ws)
    for v, fn in MIGRATIONS:
        if v > have:
            fn(client, ws)
            client.rw(ws, SCHEMA_VERSION_SET, {"v": v, "now": int(time.time() * 1000)})
            applied.append(v)
    return applied
