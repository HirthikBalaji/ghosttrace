# Performance

All numbers come from measured runs on the development laptop: Apple Silicon (arm64), macOS. FalkorDB
v4.22.0 runs in Docker Desktop (8 CPUs and 3.8 GiB available to Docker). They are indicative only.

## Hot queries (scenario A, `scripts/profile_queries.py`, 30 runs each)

The full PROFILE output is in [performance-profiles.md](performance-profiles.md).

| Query | median ms | p95 ms |
|---|---|---|
| Active snapshot (shared bitemporal predicate) | 4.39 | 5.11 |
| Attack-path enumeration, depth 8 | 1.74–1.81 | 1.91–2.00 |
| As-of ownership | 0.70 | 0.93 |
| Memory retrieval by graph relevance | 0.73 | 0.84 |

Findings from PROFILE:

- Path enumeration starts with `Node By Index Scan (s:Entity)` on the `id` index, then runs a
  `Conditional Variable Length Traverse`. On scenario A the traversal emits 205 records and the filter reduces
  them to 10 paths. The relationship predicate inside `all(...)` is **not** pushed down into the traversal. It
  is fine at demo scale, and it is the first thing to optimise for larger graphs, for example by
  pre-filtering with `$allowed`.
- Index use on relationships is restricted to `edge_id` because of the planner issue in DECISIONS D-008.
  The active-snapshot query is therefore a label/type scan with a filter, linear in edge count.

## Scaling (from `evals/report.md`)

See the "Scaling (measured)" table in [evals/report.md](../evals/report.md). It reports solver time for k=1,
cold and warm replanning after new evidence, the FalkorDB snapshot query and Cypher path enumeration, at
generator sizes from 10 to 160 mid nodes, with sample counts. Incremental warm-start replanning gives a modest
measured speedup (≈1.1–1.6× (noisy timings, n = 5 per size)). Warm and cold results are asserted equal on every sample.
