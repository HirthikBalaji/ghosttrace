# Graph schema (schema version 2)

One FalkorDB graph per workspace: `ws:<workspace_id>`. Every node and relationship carries `workspace_id`.
Migrations (`app/graph/schema.py`) are versioned via `:SchemaVersion` nodes and are idempotent.

## Nodes

Entity nodes carry two labels, `:Entity:<Label>`, with `id` (unique), `name`, `workspace_id`, `synthetic=true`
and optional props. The optional props are: `segment` (network segment, used by templates),
`wildcard_prefix` (Policy), seeded costs (`cost_disable`, `cost_revoke`, `cost_isolate`, `cost_pause`) with a
`cost_basis`, and `text`/`valid_from` for Runbook, Decision and Incident.

Labels: `Person, Team, Identity, Credential, Asset, Service, Repository, Deployment, BuildRunner, Host, Group,
Policy, Runbook, Document, Decision, SecurityEvent, Incident`.

Coordination and provenance nodes (no `:Entity`):

| Label | Key | Purpose |
|---|---|---|
| `Workspace` | `id` | tenancy anchor |
| `SourceRecord` | `source_id` | evidence record: `integrity` (signed / hash_verified / none), `attacker_influenceable`, `root_id`, `derived_from`, `trust_class`, `observed_at`, `ingested_at`, `content` (untrusted text), `contains_instructions` |
| `ScenarioMeta` | `workspace_id` | loaded scenario: incident, flows, ingestion log |
| `Investigation` | `id` | status, analysis clock (T, τ), K, policy |
| `AgentTask` | `task_id`, `idempotency_key` | state machine: `status`, `attempt_count`, `lease_owner`, `lease_expires_at`, `input_ref_ids`, `output_ref_ids`, `parent_task_id`, `error_category` |
| `AgentOutput`, `Hypothesis`, `Plan`, `Certificate` | `id` | persisted artifacts (`payload` JSON), `PART_OF` the investigation |
| `Memory` | `memory_id` | category, content, `source_ids`, `entity_ids`, scope, `taint`, `taint_reasons`, `status` (active / quarantined / superseded), `expires_at`, `promoted_from` |
| `AuditEvent` | `id` | append-only actor/action/detail |
| `SchemaVersion` | `version` | migration ledger |

## Fact relationships (bitemporal)

Each **version** of a fact is its own relationship, keyed by `(edge_id, version)`, with these properties:

`edge_id, version, workspace_id, valid_from, valid_to, valid_open_ended, validity_unknown, tx_from, tx_to,
kind (asserted | derived | latent), source_ids, dispute_source_ids, valid_to_source_ids, prior_valid_to,
prior_valid_open_ended, rule_id, parent_ids, template_id, verify_cost, stale, cost_remove, created_by, note,
supersedes, schema_version`.

An update closes the current version (`tx_to = at`) and inserts version + 1 with `supersedes` set to the prior
version number. Backfilled facts get `tx_from = ingestion time`, even when `valid_from` is in the past.

### Traversal (capability) types — `TRAVERSAL_EDGE_TYPES`

Direction is capability flow: `u → v` means control of `u` yields capability over `v`.

| Type | From → To | Meaning |
|---|---|---|
| `HAS_CREDENTIAL` | Identity/Host/Service → Credential | holder can use the credential (e.g. token cached on a host) |
| `AUTHENTICATES_AS` | Credential → Identity | the credential acts as that principal |
| `CAN_ASSUME` | Identity/Service/Repository → Identity | role assumption / trust (incl. latent templates) |
| `CAN_ACCESS` | Identity/Service/Host → Service/Asset/Host/Repository | grant (asserted, or DERIVED by `policy_expansion`) |
| `CONNECTS_TO` | Host/Service → Service/Asset/Host | modeled network reachability |
| `DEPLOYS_TO` | Deployment → Service | deployment control |

### Knowledge types (Company Brain; same bitemporal schema, never traversed for attacks)

`OWNS` (Team→Service), `MEMBER_OF` (Person/Identity/Service→Team/Group), `KNOWS_ABOUT` (Person→Service),
`DEPENDS_ON` (Service→Service/Asset), `APPLIES_TO` (Runbook→entity; Policy→Service), `HAS_POLICY`
(Identity→Policy), `BUILT_BY` (Repository→Identity), `RUNS_ON`, `RECORDED_IN` (Decision→Document), `AFFECTS`
(Decision→entity), `MITIGATES`, `RECOMMENDS`, `RELATED_TO`, `DEPLOYED_FROM`.

### Provenance and coordination relationships

`DERIVED_FROM` (SourceRecord→SourceRecord; Memory→SourceRecord), `CONTRADICTED_BY` (SourceRecord→SourceRecord),
`OBSERVED_IN` (SourceRecord→Incident), `HAS_TASK` (Investigation→AgentTask), `HANDOFF_TO` (AgentTask→AgentTask:
`at`, `refs`, `note`), `HAS_MEMORY` (Investigation→Memory), `SUPERSEDES` (Memory→Memory), `PART_OF` (artifact →
Investigation; Workspace → Investigation).

## Indexes and constraints

- Node range indexes: `Entity(id)`, `Entity(workspace_id)`, `SourceRecord(source_id|workspace_id)`,
  `Investigation(id)`, `AgentTask(task_id|idempotency_key)`, `Memory(memory_id|workspace_id)`,
  `AuditEvent(investigation_id)`, artifact ids.
- Unique constraints: `Entity.id`, `SourceRecord.source_id`, `Investigation.id`, `AgentTask.task_id`,
  `AgentTask.idempotency_key`, `Memory.memory_id`.
- Relationship range indexes: `edge_id` only, on every fact type. Migration 2 removes temporal and workspace
  relationship indexes (see DECISIONS D-008).

## Rules

Ingestion is idempotent on stable ids. Changed facts supersede and are never erased. Contradictions are kept
and linked with `CONTRADICTED_BY`. An LLM claim is never stored as OBSERVED: latent edges come only from
templates whose preconditions hold. Reset: `POST /api/v1/scenarios/{id}/reset` or `make seed`.
