# FalkorDB v4.22.0: server crash-loops after restart when a graph with a unique constraint was deleted (AOF)

Status: found and reproduced 2026-10-11 while hardening GHOSTTRACE; worked around (DECISIONS D-027). Intended for an
upstream issue report to FalkorDB.

## Environment
`falkordb/falkordb:v4.22.0` (Redis 8.10.2, FalkorDB module 4.22.0), Docker Desktop on macOS arm64, persistence
`--appendonly yes` (both `appendfsync always` and `everysec`).

## Reproduction (`scripts/repro/falkordb_aof_unique_constraint.sh con_delete`)
1. Create a graph with nodes, a range index on `(Entity.id)` and a unique constraint on `(Entity.id)`.
2. `GRAPH.DELETE` the graph.
3. Restart the server. It starts, and the incremental AOF now contains graph-effect records (constraint/attribute
   effects) for the **deleted** graph, appended after the load.
4. Restart again. The server segfaults (`signal 11`, accessing address `0x8`) while replaying the AOF and crash-loops.

| Variant | 3 restarts |
|---|---|
| index only, then `GRAPH.DELETE` | survives |
| unique constraint, contents cleared (`MATCH (n) DETACH DELETE n`) instead of `GRAPH.DELETE` | survives |
| unique constraint, then `GRAPH.DELETE` | **crash** |
| drop the constraint, then `GRAPH.DELETE` | **crash** (constraint history is still in the AOF) |
| drop the constraint, `BGREWRITEAOF`, then `GRAPH.DELETE` | survives |

Waiting for the constraint to become `OPERATIONAL` before deleting does not help.

## Likely cause (hypothesis, not verified in FalkorDB source)
On AOF load, replaying the graph's creation schedules the asynchronous unique-constraint build; the graph is deleted
by a later record in the same replay; the build completes afterwards and emits effects for a key that no longer
exists. Replaying an effect for a non-existent graph dereferences a null graph context.

Separately, the server should validate internal replication records and reject them instead of crashing; GHOSTTRACE
recommends that deployments do not grant application users the internal effect-replication command via ACL.

## Workaround in GHOSTTRACE
- Schema migration 1 no longer creates unique constraints; uniqueness is enforced by `MERGE` on stable ids
  (tested by the idempotent-ingestion tests).
- Migration 3 drops legacy constraints in existing workspaces and runs `BGREWRITEAOF`.
- `scripts/recover_falkordb_aof.sh` recovers an affected volume from its last RDB snapshot.
- Regression tests: `tests/test_docker_persistence.py` (delete + three restarts, legacy upgrade + three restarts).
