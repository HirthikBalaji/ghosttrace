# Architecture

```text
 Browser (React/TS, Cytoscape)                    Independent verifier (stdlib-only, separate process)
        │  HTTPS-less local demo                          ▲  python -m verifier check cert.json edges.jsonl
        ▼                                                 │
 FastAPI  /api/v1 ── auth (demo token, fail-closed) ── rate limits ── envelopes ── security headers
        │
        ├── Orchestrator ── durable AgentTask state machine (lease CAS, HANDOFF_TO, retries, cancel, resume)
        │      ├─ A Investigator ──┐
        │      ├─ B Evidence verifier   typed I/O schemas, per-agent tool allowlists + budgets,
        │      ├─ C Containment planner   read-only graph tools, Mock/OpenAI-compatible provider
        │      ├─ F Red team ───────┘
        │      └─ E Memory curator ── Memory service (provenance, taint, promotion, quarantine)
        ├── D Company Brain (bitemporal traversal)
        │
        ├── Deterministic core (pure Python)
        │      temporal predicate · evidence calculus R1–R5 · snapshot builder · paths/0-1 BFS
        │      κ rules · candidate generation · CEGAR planner · certificates + canonical export
        │
        └── Graph repository (only writer) ── constant parameterised Cypher ── GraphClient (ro/rw + timeout)
                                                                    │
                                                    FalkorDB v4.22.0: one graph per workspace ws:<id>
                                                    facts · sources · investigations · tasks · memory · audit
```

## Data flow of one investigation

1. **Seed / ingest.** `scenario.load` replays a timestamped ingestion log into a `Ledger`. The ledger
   supersedes versions instead of deleting them, applies R2 to removal claims, and materialises derived facts.
   It accepts latent nominations only if template preconditions hold. The `Repository` upserts versions with
   `MERGE`. During seeding, every latent precondition is re-checked in FalkorDB.
2. **Investigator.** Enumerates time-valid paths in Cypher at T = now and at T = incident (as known now and as
   known then). Groups paths into hypotheses. Retrieves prior-incident memory by graph relevance as a
   *competing* hypothesis.
3. **Evidence verifier.** Re-fetches every cited record and re-derives path classes from its own snapshot. It
   checks temporal validity and knowability at incident time, R1–R3, independence and stale runbooks. Injection
   content is flagged.
4. **Containment planner.** Computes the Pareto set for k = 0..K, a certificate and canonical export per
   feasible plan, B0 (disable the alerted account) as a `not_contained` certificate, and the R4 sensitivity diff.
5. **Red team.** Nominates template instantiations via the model and checks each one against the Cypher
   precondition. Accepted nominations are written as LATENT facts at τ + 1 simulated minute. Any certificate
   that is now reopened within its k is downgraded, and replanning is triggered (persisted as extra stages).
   It also lists evidence-tampering scenarios from R5.
6. **Memory curator.** Writes episodic memories. It promotes only verifier-`supported` hypotheses with ≥ 2
   independent roots, and taints false-flag-derived and injection-derived memory.

Every stage persists state before and after it runs. Outputs are `:AgentOutput` nodes, and a handoff is
written before the next stage starts. A restarted process resumes at the first incomplete stage.

## Key modules

| Path | Responsibility |
|---|---|
| `app/temporal/predicate.py` | The one shared bitemporal predicate (Cypher constant + Python mirror); ISO parsing (naive rejected) |
| `app/ingestion/ledger.py` | Idempotent bitemporal fact ledger, R2 at ingestion, derived rule |
| `app/reasoning/evidence.py` | R1–R3, independence over the provenance DAG |
| `app/reasoning/snapshot.py` | (T, τ, policy, falsified) → classified snapshot |
| `app/reasoning/kappa.py` | Action types, κ rules, deterministic candidates |
| `app/planner/cegar.py` | Exact CEGAR solver, nogoods, warm start, budgets |
| `app/planner/engine.py` | Pareto, certificates, canonical export + hash, R3 scrutiny, R4, R5 |
| `verifier/core.py` | Independent re-check (< 450 lines, stdlib only) |
| `app/graph/queries.py` | Every Cypher statement (constants) |
| `app/orchestration/orchestrator.py` | Task state machine and recovery |
| `app/memory/service.py` | Memory rules |
| `app/agents/*` | Agent implementations, tools, provider adapter, Company Brain |
