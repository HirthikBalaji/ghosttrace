# Progress

Last updated 2026-10-11. **Degradation level reached: all four levels (A–D) are implemented, with their gates
met by commands run locally.** CI exists as `.github/workflows/ci.yml` but has **not** run on GitHub, because the
repository has no remote. The same commands were run locally through `make`.

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

## Not done / blocked

- **GitHub Actions has not run** (no remote; pushing is out of scope). The workflow is untested on GitHub runners.
- **No real authentication** (demo token only, by design for this build) and no TLS.
- **No screen-reader manual audit**; accessibility checks are automated (axe) only.
- **No demo recording**; screenshots are in `docs/screenshots/`.
- FalkorDB graph procedures (`algo.*`) are not used (see docs/why-falkordb.md).
