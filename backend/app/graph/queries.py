"""Constant, parameterised Cypher. No query text is ever built from user or model input.

Labels and relationship types cannot be Cypher parameters, so per-label/per-type statements are
generated once at import time from the code-level allowlists in `app.model` (never from requests).
"""

from __future__ import annotations

from app.model import ALL_FACT_EDGE_TYPES, NODE_LABELS, TRAVERSAL_EDGE_TYPES
from app.temporal.predicate import TEMPORAL_STATUS_EXPR, temporal_predicate

TP = temporal_predicate("r")
VISIBLE = "(r.tx_from <= $tau AND (r.tx_to IS NULL OR $tau < r.tx_to))"

UPSERT_NODE: dict[str, str] = {
    label: f"UNWIND $rows AS row MERGE (n:Entity:{label} {{id: row.id}}) SET n += row.props"
    for label in NODE_LABELS
}
UPSERT_EDGE_VERSION: dict[str, str] = {
    t: ("UNWIND $rows AS row MATCH (a:Entity {id: row.src}), (b:Entity {id: row.dst}) "
        f"MERGE (a)-[r:{t} {{edge_id: row.edge_id, version: row.version}}]->(b) SET r += row.props")
    for t in ALL_FACT_EDGE_TYPES
}
UPSERT_SOURCE = "UNWIND $rows AS row MERGE (s:SourceRecord {source_id: row.source_id}) SET s += row.props"
LINK_SOURCE_DERIVED = ("UNWIND $rows AS row MATCH (a:SourceRecord {source_id: row.a}), (b:SourceRecord {source_id: row.b}) "
                       "MERGE (a)-[:DERIVED_FROM]->(b)")
LINK_CONTRADICTION = ("UNWIND $rows AS row MATCH (a:SourceRecord {source_id: row.a}), (b:SourceRecord {source_id: row.b}) "
                      "MERGE (a)-[:CONTRADICTED_BY]->(b)")
UPSERT_WORKSPACE = "MERGE (w:Workspace {id: $ws}) SET w.synthetic = true, w.updated_at = $now"
UPSERT_INCIDENT_EVIDENCE = ("UNWIND $rows AS row MATCH (s:SourceRecord {source_id: row.sid}), (i:Entity:Incident {id: row.iid}) "
                            "MERGE (s)-[:OBSERVED_IN]->(i)")
UPSERT_META = "MERGE (m:ScenarioMeta {workspace_id: $ws}) SET m.payload = $payload, m.scenario_id = $sid"
GET_META = "MATCH (m:ScenarioMeta {workspace_id: $ws}) RETURN m.payload"

ALL_NODES = "MATCH (n:Entity) WHERE n.workspace_id = $ws RETURN n.id, labels(n), properties(n)"
ALL_SOURCES = "MATCH (s:SourceRecord) WHERE s.workspace_id = $ws RETURN properties(s)"
_FACT_TYPES = list(ALL_FACT_EDGE_TYPES)
ALL_EDGE_VERSIONS = ("MATCH (a:Entity)-[r]->(b:Entity) WHERE type(r) IN $types AND r.workspace_id = $ws "
                     "RETURN type(r), a.id, b.id, labels(a), labels(b), properties(r)")
# Live path: FalkorDB evaluates the shared bitemporal predicate.
ACTIVE_EDGE_VERSIONS = ("MATCH (a:Entity)-[r]->(b:Entity) WHERE type(r) IN $types AND r.workspace_id = $ws "
                        f"AND {TP} RETURN type(r), a.id, b.id, labels(a), labels(b), properties(r), "
                        f"{TEMPORAL_STATUS_EXPR}")
VISIBLE_EDGE_VERSIONS = ("MATCH (a:Entity)-[r]->(b:Entity) WHERE type(r) IN $types AND r.workspace_id = $ws "
                         f"AND {VISIBLE} RETURN type(r), a.id, b.id, labels(a), labels(b), properties(r)")
FACT_HISTORY = ("MATCH (a:Entity)-[r]->(b:Entity) WHERE r.edge_id = $edge_id AND r.workspace_id = $ws "
                "RETURN type(r), a.id, b.id, properties(r) ORDER BY r.version")

MAX_CYPHER_DEPTH = 12
# Bounded path enumeration over the snapshot overlay: $allowed = snapshot edge ids minus removed ids.
FIND_PATHS: dict[int, str] = {
    d: (f"MATCH p=(s:Entity)-[*1..{d}]->(t:Entity) WHERE s.id IN $sources AND t.id IN $targets "
        "AND all(r IN relationships(p) WHERE r.workspace_id = $ws AND r.edge_id IN $allowed AND "
        f"{TP}) "
        "RETURN [r IN relationships(p) | r.edge_id] AS edge_ids, [n IN nodes(p) | n.id] AS node_ids LIMIT $limit")
    for d in range(1, MAX_CYPHER_DEPTH + 1)
}
TRAVERSAL_TYPES = list(TRAVERSAL_EDGE_TYPES)

# ---- Company Brain (all bitemporal through the shared predicate)
OWNERS = ("MATCH (t:Entity:Team)-[r:OWNS]->(s:Entity {id: $sid}) WHERE r.workspace_id = $ws AND " + TP +
          " RETURN t.id, t.name, r.edge_id, r.version, r.source_ids, r.validity_unknown, r.stale, r.valid_from, "
          "r.valid_to, r.tx_from")
TEAM_MEMBERS = ("MATCH (p:Entity:Person)-[r:MEMBER_OF]->(t:Entity:Team {id: $tid}) WHERE r.workspace_id = $ws AND "
                + TP + " RETURN p.id, p.name, r.edge_id, r.source_ids")
EXPERTS = ("MATCH (p:Entity:Person)-[r:KNOWS_ABOUT]->(s:Entity {id: $sid}) WHERE r.workspace_id = $ws AND " + TP +
           " RETURN p.id, p.name, r.edge_id, r.source_ids")
DEPENDENTS = ("MATCH p=(x:Entity)-[rels:DEPENDS_ON*1..4]->(s:Entity {id: $sid}) WHERE all(r IN rels WHERE "
              "r.workspace_id = $ws AND " + TP + ") RETURN [n IN nodes(p) | n.id], [r IN rels | r.edge_id] LIMIT 200")
DEPENDENCIES = ("MATCH p=(s:Entity {id: $sid})-[rels:DEPENDS_ON*1..4]->(x:Entity) WHERE all(r IN rels WHERE "
                "r.workspace_id = $ws AND " + TP + ") RETURN [n IN nodes(p) | n.id], [r IN rels | r.edge_id] LIMIT 200")
RUNBOOKS_FOR = ("MATCH (rb:Entity:Runbook)-[r:APPLIES_TO]->(x:Entity) WHERE x.id IN $ids AND r.workspace_id = $ws "
                "AND " + TP + " RETURN rb.id, rb.name, rb.text, rb.valid_from, x.id, r.edge_id, r.source_ids")
DECISIONS_FOR = ("MATCH (d:Entity:Decision)-[r:AFFECTS]->(x:Entity) WHERE x.id IN $ids AND r.workspace_id = $ws AND "
                 + TP + " OPTIONAL MATCH (d)-[q:RECORDED_IN]->(doc:Entity) "
                 "RETURN d.id, d.name, d.text, d.decided_at, x.id, r.edge_id, r.source_ids, doc.id, doc.name")
PRIOR_INCIDENTS = ("MATCH (i:Entity:Incident) WHERE i.workspace_id = $ws AND i.id <> $current "
                   "RETURN i.id, i.name, i.text, i.root_cause, i.closed_at")
NODES_BY_IDS = "MATCH (n:Entity) WHERE n.workspace_id = $ws AND n.id IN $ids RETURN n.id, labels(n), properties(n)"
SOURCES_BY_IDS = ("MATCH (s:SourceRecord) WHERE s.workspace_id = $ws AND s.source_id IN $ids "
                  "RETURN properties(s)")
CONTRADICTIONS_FOR = ("MATCH (a:SourceRecord)-[:CONTRADICTED_BY]->(b:SourceRecord) WHERE a.workspace_id = $ws AND "
                      "(a.source_id IN $ids OR b.source_id IN $ids) RETURN a.source_id, b.source_id")
INCIDENT_EVIDENCE = ("MATCH (s:SourceRecord)-[:OBSERVED_IN]->(i:Entity:Incident {id: $iid}) WHERE s.workspace_id = $ws "
                     "RETURN properties(s)")
SEARCH_NODES = ("MATCH (n:Entity) WHERE n.workspace_id = $ws AND (toLower(n.name) CONTAINS $q OR toLower(n.id) CONTAINS $q) "
                "RETURN n.id, labels(n), n.name LIMIT 25")

# ---- Investigations, tasks, handoffs, memory, audit (workspace graph = durable coordination state)
CREATE_INVESTIGATION = ("MERGE (i:Investigation {id: $id}) ON CREATE SET i += $props "
                        "WITH i MATCH (w:Workspace {id: $ws}) MERGE (w)-[:PART_OF]->(i) RETURN i.id")
UPDATE_INVESTIGATION = "MATCH (i:Investigation {id: $id}) WHERE i.workspace_id = $ws SET i += $props RETURN i.id"
GET_INVESTIGATION = "MATCH (i:Investigation {id: $id}) WHERE i.workspace_id = $ws RETURN properties(i)"
LIST_INVESTIGATIONS = ("MATCH (i:Investigation) WHERE i.workspace_id = $ws RETURN properties(i) "
                       "ORDER BY i.created_at DESC LIMIT $limit")

UPSERT_TASK = ("MATCH (i:Investigation {id: $inv}) WHERE i.workspace_id = $ws "
               "MERGE (t:AgentTask {idempotency_key: $key}) ON CREATE SET t += $props "
               "MERGE (i)-[:HAS_TASK]->(t) RETURN properties(t)")
# Atomic claim (FalkorDB executes a query atomically): only queued, or running with an expired lease.
CLAIM_TASK = ("MATCH (t:AgentTask {task_id: $tid}) WHERE t.workspace_id = $ws AND "
              "(t.status = 'queued' OR (t.status = 'running' AND t.lease_expires_at < $now)) "
              "SET t.status = 'running', t.lease_owner = $owner, t.lease_expires_at = $exp, "
              "t.attempt_count = coalesce(t.attempt_count, 0) + 1, t.started_at = $now RETURN properties(t)")
# Compare-and-set completion: only the current lease owner can write the result.
COMPLETE_TASK = ("MATCH (t:AgentTask {task_id: $tid}) WHERE t.workspace_id = $ws AND t.status = 'running' AND "
                 "t.lease_owner = $owner SET t += $props RETURN properties(t)")
GET_TASKS = ("MATCH (i:Investigation {id: $inv})-[:HAS_TASK]->(t:AgentTask) WHERE t.workspace_id = $ws "
             "RETURN properties(t) ORDER BY t.seq")
CANCEL_TASKS = ("MATCH (i:Investigation {id: $inv})-[:HAS_TASK]->(t:AgentTask) WHERE t.workspace_id = $ws AND "
                "t.status IN ['queued', 'running', 'blocked'] SET t.status = 'cancelled', t.finished_at = $now "
                "RETURN count(t)")
HANDOFF = ("MATCH (a:AgentTask {task_id: $a}), (b:AgentTask {task_id: $b}) WHERE a.workspace_id = $ws AND "
           "b.workspace_id = $ws MERGE (a)-[h:HANDOFF_TO]->(b) ON CREATE SET h.at = $now, h.refs = $refs, "
           "h.note = $note RETURN h.at")
GET_HANDOFFS = ("MATCH (i:Investigation {id: $inv})-[:HAS_TASK]->(a:AgentTask)-[h:HANDOFF_TO]->(b:AgentTask) "
                "WHERE a.workspace_id = $ws RETURN a.task_id, a.agent_type, b.task_id, b.agent_type, h.at, h.refs, h.note "
                "ORDER BY h.at")

UPSERT_ARTIFACT: dict[str, str] = {
    label: (f"MERGE (x:{label} {{id: $id}}) ON CREATE SET x += $props "
            "WITH x MATCH (i:Investigation {id: $inv}) WHERE i.workspace_id = $ws MERGE (x)-[:PART_OF]->(i) "
            "RETURN x.id")
    for label in ("Hypothesis", "Plan", "Certificate", "AgentOutput")
}
GET_ARTIFACT: dict[str, str] = {
    label: f"MATCH (x:{label} {{id: $id}}) WHERE x.workspace_id = $ws RETURN properties(x)"
    for label in ("Hypothesis", "Plan", "Certificate", "AgentOutput")
}
LIST_ARTIFACTS: dict[str, str] = {
    label: (f"MATCH (x:{label})-[:PART_OF]->(i:Investigation {{id: $inv}}) WHERE x.workspace_id = $ws "
            "RETURN properties(x) ORDER BY x.created_at")
    for label in ("Hypothesis", "Plan", "Certificate", "AgentOutput")
}

UPSERT_MEMORY = ("MERGE (m:Memory {memory_id: $id}) ON CREATE SET m += $props "
                 "WITH m UNWIND $source_ids AS sid OPTIONAL MATCH (s:SourceRecord {source_id: sid}) "
                 "WHERE s.workspace_id = $ws FOREACH (_ IN CASE WHEN s IS NULL THEN [] ELSE [1] END | "
                 "MERGE (m)-[:DERIVED_FROM]->(s)) RETURN count(*)")
LINK_MEMORY_INV = ("MATCH (m:Memory {memory_id: $id}), (i:Investigation {id: $inv}) WHERE m.workspace_id = $ws "
                   "MERGE (i)-[:HAS_MEMORY]->(m)")
SUPERSEDE_MEMORY = ("MATCH (new:Memory {memory_id: $new}), (old:Memory {memory_id: $old}) WHERE new.workspace_id = $ws "
                    "AND old.workspace_id = $ws SET old.status = 'superseded', old.superseded_at = $now "
                    "MERGE (new)-[:SUPERSEDES]->(old)")
UPDATE_MEMORY = "MATCH (m:Memory {memory_id: $id}) WHERE m.workspace_id = $ws SET m += $props RETURN properties(m)"
LIST_MEMORY = "MATCH (m:Memory) WHERE m.workspace_id = $ws RETURN properties(m) ORDER BY m.created_at DESC LIMIT $limit"
# Retrieval by graph relevance: memories whose provenance shares source records or entities with the investigation.
RELEVANT_MEMORY = ("MATCH (m:Memory) WHERE m.workspace_id = $ws AND m.status <> 'quarantined' "
                   "OPTIONAL MATCH (m)-[:DERIVED_FROM]->(s:SourceRecord) "
                   "WITH m, collect(s.source_id) AS srcs "
                   "WITH m, srcs, size([x IN coalesce(m.entity_ids, []) WHERE x IN $entity_ids]) AS ent_overlap, "
                   "size([x IN srcs WHERE x IN $source_ids]) AS src_overlap "
                   "WHERE ent_overlap + src_overlap > 0 OR m.category = 'procedural' "
                   "RETURN properties(m), ent_overlap, src_overlap ORDER BY ent_overlap + src_overlap DESC LIMIT $limit")

AUDIT = ("CREATE (a:AuditEvent {id: $id, workspace_id: $ws, investigation_id: $inv, at: $at, actor: $actor, "
         "action: $action, detail: $detail})")
GET_AUDIT = ("MATCH (a:AuditEvent) WHERE a.workspace_id = $ws AND a.investigation_id = $inv "
             "RETURN properties(a) ORDER BY a.at, a.id")
SCHEMA_VERSION_GET = "MATCH (v:SchemaVersion) RETURN max(v.version)"
SCHEMA_VERSION_SET = "MERGE (v:SchemaVersion {version: $v}) ON CREATE SET v.applied_at = $now"
COUNT_ALL = "MATCH (n) RETURN count(n)"
COUNT_EDGES = "MATCH ()-[r]->() RETURN count(r)"
