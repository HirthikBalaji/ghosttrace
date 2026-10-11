"""Versioned, idempotent schema migrations for a workspace graph."""

from __future__ import annotations

import functools
import time
from collections.abc import Callable

from app.graph.client import GraphClient
from app.graph.queries import SCHEMA_VERSION_GET, SCHEMA_VERSION_SET
from app.model import ALL_FACT_EDGE_TYPES

NODE_INDEXES = [
    ("Entity", "id"),
    ("Entity", "workspace_id"),
    ("SourceRecord", "source_id"),
    ("SourceRecord", "workspace_id"),
    ("Investigation", "id"),
    ("AgentTask", "task_id"),
    ("AgentTask", "idempotency_key"),
    ("Memory", "memory_id"),
    ("Memory", "workspace_id"),
    ("AuditEvent", "investigation_id"),
    ("Certificate", "id"),
    ("Plan", "id"),
    ("Hypothesis", "id"),
    ("AgentOutput", "id"),
    ("SchemaVersion", "version"),
    ("Workspace", "id"),
]
# Historical: unique constraints created by migration 1 before 2026-10-11. FalkorDB v4.22.0 with AOF
# persistence crashes on the second restart after a graph that had a unique constraint is deleted
# (DECISIONS D-027, docs/upstream/falkordb-aof-unique-constraint-crash.md). Uniqueness is enforced by MERGE on
# stable ids instead; migration 3 removes existing constraints and compacts the AOF.
LEGACY_UNIQUE = [
    ("Entity", "id"),
    ("SourceRecord", "source_id"),
    ("Investigation", "id"),
    ("AgentTask", "task_id"),
    ("AgentTask", "idempotency_key"),
    ("Memory", "memory_id"),
]
# Only edge_id: FalkorDB v4.22.0 mis-binds multi-edge patterns when several relationships have
# index-eligible filters (Edge By Index Scan); see DECISIONS.md D-008 and tests/test_falkordb_regressions.py.
EDGE_INDEX_PROPS = ("edge_id",)


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
        _ignore_exists(functools.partial(g.create_node_range_index, label, prop))
    for t in ALL_FACT_EDGE_TYPES:
        for prop in EDGE_INDEX_PROPS:
            _ignore_exists(functools.partial(g.create_edge_range_index, t, prop))


def migration_2(client: GraphClient, ws: str) -> None:
    """Drop relationship range indexes on temporal/workspace props (FalkorDB v4.22.0 planner issue, D-008)."""
    g = client._g(ws)
    for t in ALL_FACT_EDGE_TYPES:
        for prop in ("tx_from", "valid_from", "workspace_id"):
            try:
                g.drop_edge_range_index(t, prop)
            except Exception as exc:
                if "not" not in str(exc).lower() and "unable" not in str(exc).lower():
                    raise


def _unique_constraints(g: object) -> list[tuple[str, tuple[str, ...]]]:
    rows = g.list_constraints()  # type: ignore[attr-defined]  # falkordb 1.7.1: list of dicts
    return [(r["label"], tuple(r["properties"])) for r in rows if r["type"] == "UNIQUE" and r["entitytype"] == "NODE"]


def migration_3(client: GraphClient, ws: str) -> None:
    """Drop legacy unique constraints (FalkorDB AOF-replay crash, D-027), then compact the AOF so the
    constraint history no longer appears in the incremental log."""
    g = client._g(ws)
    present = set(_unique_constraints(g))
    for label, prop in LEGACY_UNIQUE:
        if (label, (prop,)) in present:
            g.drop_node_unique_constraint(label, prop)
    for _ in range(100):
        if not _unique_constraints(g):
            break
        time.sleep(0.05)
    client.compact_aof()


MIGRATIONS: list[tuple[int, Callable[[GraphClient, str], None]]] = [
    (1, migration_1),
    (2, migration_2),
    (3, migration_3),
]
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
