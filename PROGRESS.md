# Progress

Last updated 2026-10-11. **Degradation level reached: all four levels (A–D) are implemented, with their gates met by commands run
locally.** CI (`.github/workflows/ci.yml`) is green on GitHub.

| # | Milestone | Status | Gate evidence (commands actually run) |
|---|---|---|---|
| M0 | Reconnaissance | done | `scripts/check_environment.sh` → "environment OK". FalkorDB client smoke test verified `ro_query`, `timeout`, list params, `relationships(p)` predicates, indexes, unique constraints, `copy`, procedures. `DECISIONS.md` |
| M1 | Graph foundation + bitemporal | done | Migrations idempotent and seed/reset reproducible (`test_migrations_idempotent`, `test_seed_is_idempotent_and_reproducible`). All §3.1 temporal tests pass, including the Cypher-vs-Python differential against real FalkorDB |
| M2 | Deterministic core + verifier | done | Path classes, κ rules, reachability, certificates. The verifier accepts valid certificates and rejects 19/19 mutations in `test_every_mutation_rejected`; eval mutation runs kill 821/821 applied. Differential path tests pass |
| M3 | CEGAR planner (A→B) | done | Solver equals brute force on ≥ 30 small instances. Residual-path rejection. k-robustness and Pareto 3/10/14 on Ghost Credential. Depth-bound soundness test passes |
| M4 | Evidence calculus (C) | done | R1–R5 unit tests; false-flag and asymmetry scenarios; load-bearing sets verified for minimality |
| M5 | Orchestration, memory, red team | done | Restart recovery (process and FalkorDB container restart), idempotent retries, lease conflict, poisoning/taint, isolation tests |
| M6 | API + UI | done | OpenAPI equals `docs/api.md` (test). Playwright e2e of the full demo passes against the dev preview **and** the Docker Compose stack, with 0 serious/critical axe violations on 7 views. Health/ready tests |
| M7 | Benchmarks and evals | done | `evals/run_evals.py --n 100 --falkordb` → `evals/report.md`: **0 soundness violations / 900 certificates**. Scaling measured for 10–160 mid nodes |
| M8 | Hardening and docs | done | `make lint` (ruff + format) clean, `mypy --strict` clean, `tsc` clean, `pip-audit` and `npm audit` 0 known vulnerabilities, secret scan clean. README commands exercised. Claims ledger complete. Demo script rehearsed via e2e |

## Level D items

- Incremental warm-start replanning — done (`test_warm_start_equals_cold_after_new_evidence`; scaling table).
  The speedup is modest.
- Generator-scale benchmarks and scaling report — done.
- Read-only MCP server — done: `python -m app.mcp_server` (stdio JSON-RPC, allowlisted read-only tools;
  `tests/test_mcp_and_streaming.py`).
- Streaming progress and cancellation — done: `GET /investigations/{id}/events` (SSE, consumed by the UI via
  fetch-streaming with polling fallback) and `POST …/cancel`.

## Final verification run (2026-10-11)

```text
make lint            → ruff: All checks passed! / 70 files already formatted
make typecheck       → mypy: Success: no issues found in 51 source files; tsc: no errors
GT_RUN_DOCKER_TESTS=1 pytest → 86 passed
playwright (dev preview and Docker Compose) → 1 passed (full demo flow + axe)
evals --n 100 --falkordb → soundness violations = 0 (900 certificates), verifier 900/900
pip-audit → No known vulnerabilities found; npm audit → found 0 vulnerabilities
scripts/secret_scan.sh → clean
scripts/smoke_api.sh http://localhost:8080 (Compose) → SMOKE OK
backup → delete graph → restore → investigation restored
```

## Hardening round (2026-10-11, second pass)

| Item | Status | Evidence |
|---|---|---|
| Claude provider (official SDK) + model advisor gate | done | `tests/test_claude_provider.py` (10 tests, offline); e2e |
| OIDC/JWT auth, roles, workspace claims, production fail-closed | done | `tests/test_auth_production.py` |
| Approval workflow (four-eyes, verifier re-check, scrutiny acknowledgement) | done | `test_approval_gates`; e2e |
| Queue-mode workers, shared rate limits | done | `test_queue_mode_worker`, `test_rate_limiter_shared_across_replicas` |
| Production compose (Caddy TLS, password-protected FalkorDB, worker replicas) | done | local HTTPS smoke, recorded in `docs/operations.md` |
| FalkorDB AOF crash-loop: found, reproduced, worked around, recovery script, regression tests | done | `docs/upstream/falkordb-aof-unique-constraint-crash.md`; `tests/test_docker_persistence.py` (3 passed) |
| Story mode, demo video, judge FAQ | done | `docs/demo/ghosttrace-demo.webm`, `docs/judge-faq.md`; e2e |
| Evals regenerated on final code | done | `evals/report.md`: 0 soundness violations / 900 certificates |

Latest local run: 112 passed (3 Docker restart tests opt-in, passed with `GT_RUN_DOCKER_TESTS=1`); ruff, mypy strict,
tsc clean; e2e passed against the Compose stack. CI on GitHub: green.

## Not done / blocked

- **No real-data validation.** All data is synthetic; an exporter from a real environment into the ingestion format
  is not included.
- **No live model run recorded** (needs an Anthropic API key); the real provider code path is tested offline.
- **Production auth verified with a test signing key**, not against a specific commercial IdP.
- **No executor** for containment actions, by design.
- **No screen-reader manual audit**; accessibility checks are automated (axe) only.
- **Demo video is silent** (no narration).
- FalkorDB graph procedures (`algo.*`) are not used (see docs/why-falkordb.md).
