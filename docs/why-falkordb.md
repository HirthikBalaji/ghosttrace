# Why FalkorDB is central

FalkorDB is the only datastore and sits in the live path of every stage: facts, investigation state, tasks,
handoffs, certificates and memory. All query text is a module constant (`backend/app/graph/queries.py`); values
travel as parameters. Below are the actual queries and what each one decides.

## 1. Bitemporal as-of queries (all tracks)

The shared predicate (`app/temporal/predicate.py`) is spliced into every path, ownership and brain query:

```cypher
(r.tx_from <= $tau AND (r.tx_to IS NULL OR $tau < r.tx_to)
 AND (r.valid_to IS NULL OR $T < r.valid_to)
 AND (r.valid_from IS NULL OR r.valid_from <= $T))
```

The live snapshot used by the planner is loaded with it:

```cypher
MATCH (a:Entity)-[r]->(b:Entity) WHERE type(r) IN $types AND r.workspace_id = $ws AND <TP>
RETURN type(r), a.id, b.id, labels(a), labels(b), properties(r),
       CASE WHEN r.validity_unknown THEN 'UNCERTAIN' ELSE 'ACTIVE' END
```

Differential-tested against the Python mirror at more than 50 (T, τ) probe points
(`test_cypher_temporal_predicate_equals_python`).

## 2. Multi-hop time-valid path enumeration with a counterfactual overlay (Track 1)

```cypher
MATCH p=(s:Entity)-[*1..8]->(t:Entity) WHERE s.id IN $sources AND t.id IN $targets
  AND all(r IN relationships(p) WHERE r.workspace_id = $ws AND r.edge_id IN $allowed AND <TP>)
RETURN [r IN relationships(p) | r.edge_id], [n IN nodes(p) | n.id] LIMIT $limit
```

`$allowed` is the policy-filtered snapshot minus the removed ids of a candidate plan. This is the
counterfactual overlay: the graph is never mutated. Depth is clamped (one constant query per depth 1..12).
The investigator and red team use this to generate counterexamples. The **soundness verdict** uses exhaustive
0-1 BFS over the exported subgraph, so a path longer than the depth bound is still found
(`test_depth_bound_soundness_in_falkordb`). Path sets equal the pure-Python reference on scenario A and 12
generated instances (`test_differential_paths_*`).

## 3. Latent-template preconditions (Track 1)

An unverified edge exists only if a constant Cypher precondition holds. For example,
`group_inheritance_unmodeled`:

```cypher
MATCH (s {id:$src})-[m1:MEMBER_OF]->(g:Group)<-[m2:MEMBER_OF]-(peer)-[r:CAN_ASSUME]->(d {id:$dst})
WHERE peer.id <> s.id AND <TP(m1)> AND <TP(m2)> AND <TP(r)> RETURN count(*) > 0 AS ok
```

Building this exposed a FalkorDB v4.22.0 planner issue with multiple relationship index scans (DECISIONS
D-008); the schema avoids it and a differential test guards it.

## 4. Ownership / dependency traversal (Track 3)

```cypher
MATCH (t:Entity:Team)-[r:OWNS]->(s:Entity {id: $sid}) WHERE r.workspace_id = $ws AND <TP>
RETURN t.id, t.name, r.edge_id, r.version, r.source_ids, r.validity_unknown, r.stale, r.valid_from, r.valid_to, r.tx_from

MATCH p=(x:Entity)-[rels:DEPENDS_ON*1..4]->(s:Entity {id: $sid})
WHERE all(r IN rels WHERE r.workspace_id = $ws AND <TP>) RETURN [n IN nodes(p) | n.id], [r IN rels | r.edge_id]
```

"Who owned payments-api at incident time?" returns `team:payments` as known then (τ = T) and `team:platform`
as known now. The backfilled reorg record has `tx_from` after the incident (`test_backfill_ownership_as_known_then_vs_now`).

## 5. Memory retrieval by graph relevance (Track 2)

```cypher
MATCH (m:Memory) WHERE m.workspace_id = $ws AND m.status <> 'quarantined'
OPTIONAL MATCH (m)-[:DERIVED_FROM]->(s:SourceRecord)
WITH m, collect(s.source_id) AS srcs
WITH m, srcs, size([x IN coalesce(m.entity_ids, []) WHERE x IN $entity_ids]) AS ent_overlap,
     size([x IN srcs WHERE x IN $source_ids]) AS src_overlap
WHERE ent_overlap + src_overlap > 0 OR m.category = 'procedural'
RETURN properties(m), ent_overlap, src_overlap ORDER BY ent_overlap + src_overlap DESC LIMIT $limit
```

The prior-incident memory is retrieved because it shares the `inc:INC-2025-0912` entity reached via
`PRIOR_INCIDENTS`. Nothing is dumped into a prompt.

## 6. Durable coordination (Track 2)

Leases are claimed by an atomic compare-and-set. FalkorDB executes each query atomically:

```cypher
MATCH (t:AgentTask {task_id: $tid}) WHERE t.workspace_id = $ws AND
  (t.status = 'queued' OR (t.status = 'running' AND t.lease_expires_at < $now))
SET t.status = 'running', t.lease_owner = $owner, t.lease_expires_at = $exp,
    t.attempt_count = coalesce(t.attempt_count, 0) + 1, t.started_at = $now RETURN properties(t)
```

Completion is likewise conditioned on `t.lease_owner = $owner`, so a second worker cannot silently overwrite a
result (`test_idempotent_rerun_and_lease_conflict`). Handoffs are `HANDOFF_TO` edges. All of this survives a
container restart (`test_state_survives_container_restart_and_resumes`).

## 7. Graph-per-workspace tenancy

`ws:<workspace_id>` graphs, plus a `workspace_id` property filter in every query (tested: workspace A's graph
queried with workspace B's id returns nothing).

## Read-only enforcement

Agents and read paths call `GRAPH.RO_QUERY`; the server rejects writes (`test_read_only_path_rejects_writes`).
Every call carries a server-side timeout (`test_query_timeout_enforced`).

## What does not run in FalkorDB (stated honestly)

- **Evidence classification (R1–R3), the CEGAR solver, 0-1 BFS reopening distance and R5 falsification run in
  Python** over the snapshot that FalkorDB returns. The planner needs many overlay evaluations per solve, and
  exact 0-1 BFS with predecessor reconstruction is simpler to verify in code.
- FalkorDB's `algo.BFS` / `algo.SPpaths` procedures exist in v4.22.0 but are **not used**. They would need their
  own differential tests, and the brief allows them only with such tests.
- The baseline B1 uses degree centrality in Python, not `algo.betweenness`.
