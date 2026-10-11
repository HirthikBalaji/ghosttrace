# Claims ledger

Every quantitative or capability claim in the README, docs, UI or final report has a row here. Date for all
rows: 2026-10-11. Environment: macOS arm64 laptop, FalkorDB v4.22.0 in Docker.

## Capability claims

| Claim | Evidence | Status |
|---|---|---|
| Disabling only the alerted account leaves a CONFIRMED path (Ghost Credential) | `test_b0_disabling_alerted_account_leaves_confirmed_path`; planner B0 certificate `not_contained` | verified |
| Price of Certainty for scenario A is 3 / 10 / 14 at k = 0 / 1 / 2, all `proven_optimal` | `test_price_of_certainty_curve`, `test_full_pipeline_persists_tasks_handoffs_and_artifacts`, `scripts/smoke_api.sh` | verified |
| The k=0 plan is exactly 0-robust; witness and verification priority are correct | `test_latent_reopening_witness_and_priority` | verified |
| The independent verifier accepts the k = 0, 1, 2 certificates and rejects every non-equivalent mutation | `test_both_certificates_verified`, `test_every_mutation_rejected` (19/19), eval mutation runs (821/821 applied mutants killed; 14 identical mutants excluded; 20 not applicable) | verified |
| The verifier is stdlib-only, imports nothing from `app/`, and is < 450 lines | `test_verifier_is_stdlib_only_and_independent` | verified |
| UI/API verification runs the verifier as a separate process | `run_verifier` in `app/api/routes.py`; `test_end_to_end_demo_flow` (exit code 0) | verified |
| R2: an attacker-written "rotated" log does not remove the edge | `test_r2_untrusted_removal_disputes_not_removes`; scenario A `e:ci-token->ci-runner` disputed | verified |
| R3/R4: the false-flag-driven action is flagged and the trust-filtered plan differs | `test_r3_requires_human_scrutiny_in_certificate`, `test_r4_sensitivity_flags_false_flag_driven_action`, e2e | verified |
| R5: falsifying the IAM revocation record invalidates the k=0 certificate; reported sets are minimal | `test_r5_load_bearing_evidence` | verified (bounded to sets of size ≤ 2) |
| Duplicate alerts from one root count once | `test_duplicate_alerts_counted_once`, `test_independence_counts_distinct_roots_not_records` | verified |
| Bitemporal: revoked-before vs after, post-incident grant excluded, backfill as-known-then ≠ now, supersession history | `test_temporal.py` (12 tests), `test_backfill_ownership_as_known_then_vs_now` | verified |
| Cypher temporal predicate equals the Python mirror | `test_cypher_temporal_predicate_equals_python` (> 50 (T, τ) probes) | verified |
| FalkorDB path enumeration equals the Python reference (scenario A + 12 generated instances) | `test_differential_paths_scenario_a`, `test_differential_paths_generated` | verified |
| Latent-template Cypher preconditions equal the Python mirror over all type-compatible pairs | `test_latent_template_cypher_equals_python` | verified |
| A path longer than the Cypher depth bound is still found by the exhaustive check | `test_depth_bound_soundness_in_falkordb`, `test_exhaustive_check_independent_of_depth_bound` | verified |
| Production solver equals brute force whenever status is `proven_optimal` | `test_solver_matches_brute_force_on_small_instances` (≥ 30 comparisons); eval small family (0 mismatches listed) | verified |
| Warm-start replanning equals a cold solve | `test_warm_start_equals_cold_after_new_evidence`; asserted on every scaling sample | verified |
| Ghost Credential B yields a different, computed plan; the hard flow rules out the cheapest cut | `test_scenario_b_differs_by_computation` | verified |
| Idempotent ingestion; reset is reproducible | `test_seed_is_idempotent_and_reproducible`, `test_idempotent_reassert_and_corroboration` | verified |
| Investigation, tasks, handoffs and memory survive restarts; completed stages are not re-run | `test_restart_recovery_resumes_without_rerunning` (process), `test_state_survives_container_restart_and_resumes` (FalkorDB container restart); manual `docker compose restart backend` check | verified |
| Lease CAS prevents a second worker overwriting a result | `test_idempotent_rerun_and_lease_conflict` | verified |
| Workspace isolation for graph data, memory, API and tools | `test_tenant_isolation_graph_and_properties`, `test_memory_workspace_isolation`, `test_cross_workspace_api_isolation` | verified |
| Prompt injection is treated as data; no unauthorised tool call | `test_prompt_injection_treated_as_data` | verified |
| Tainted memory is not promoted or relied on | `test_poisoned_memory_not_promoted_or_relied_on`, `test_memory_assessment_rules` | verified |
| Prior-incident memory informs but does not dictate | `test_prior_incident_trap_memory_informs_not_dictates` | verified |
| Malformed model output fails honestly | `test_malformed_model_output_fails_honestly` | verified |
| No endpoint accepts Cypher; injection strings are inert | `test_openapi_matches_docs`, `test_injection_strings_are_inert_parameters` | verified |
| Health has no graph dependency; readiness leaks no secrets; auth fails closed | `test_health_has_no_graph_dependency`, `test_auth_fails_closed` | verified |
| Accessibility: no serious/critical axe (WCAG 2 A/AA) violations on the 7 demo views | `frontend/e2e/demo.spec.ts` (passed against dev preview and Docker Compose) | verified (automated checks only; no manual screen-reader audit) |
| FalkorDB persistence and backup/restore | container-restart test; manual backup → delete graph → restore check (see docs/operations.md) | verified |
| 0 known vulnerabilities in dependencies | `pip-audit` ("No known vulnerabilities found"), `npm audit` (0) at build time | verified (point in time) |
| Read-only MCP server exposes only allowlisted, validated tools; no writes | `test_mcp_tools_are_readonly_and_validated`, `test_mcp_stdio_roundtrip` | verified |
| Streaming progress via server-sent events (also through nginx) | `test_progress_events_stream`; manual `curl -N` through the Compose stack | verified |
| Model advisor: AI proposals are simulated/certified; wrong ones rejected with reasons, hallucinated ids rejected | `test_pipeline_through_real_provider_path_with_advisor_gate` (real provider code path via mock transport), e2e | verified (live model run not performed: needs an API key) |
| Claude provider request shape: `claude-opus-5-5`, closed JSON schema, refusal fallbacks; refusals/malformed/auth/rate-limit are handled errors | `tests/test_claude_provider.py` | verified (offline) |
| OIDC auth: JWKS, asymmetric-only, required claims; `alg=none`, key confusion, expired, wrong aud/iss rejected; roles and workspace claims enforced | `tests/test_auth_production.py` | verified |
| Production refuses demo auth | `test_production_refuses_demo_auth` | verified |
| Approval gates: four-eyes, verifier re-check, scrutiny acknowledgement, tampered certificate refused | `test_approval_gates`, e2e | verified |
| Queue mode: CAS claim (one of two workers), worker completes investigation | `test_queue_mode_worker`; production profile smoke | verified |
| Rate limits shared across replicas | `test_rate_limiter_shared_across_replicas` | verified (fake shared store) |
| Production profile end to end (HTTPS, OIDC, workers, four-eyes, password-protected FalkorDB not on host) | manual smoke 2026-10-11, recorded in docs/operations.md | verified locally with a test signing key; not against a commercial IdP |
| FalkorDB v4.22.0 AOF crash-loop after deleting a graph with a unique constraint; workaround prevents it | `scripts/repro/falkordb_aof_unique_constraint.sh`, `test_workspace_delete_then_restarts_does_not_crash`, `test_legacy_constraints_removed_by_migration_3` | verified (cause hypothesis unverified in FalkorDB source) |
| AOF recovery script restores a crash-looping volume from its RDB snapshot | run on the affected dev volume 2026-10-11 | verified (writes after the last RDB save are lost) |
| CI configuration | `.github/workflows/ci.yml` | verified: green on GitHub (backend, frontend, secrets jobs) |

## Quantitative claims (from `evals/report.md`, generated 2026-10-11, 100 instances per family)

| Claim | Evidence | Status |
|---|---|---|
| 0 certificate-soundness violations over 900 certificates; verifier accepted 900/900 | `evals/report.md` Headline; `evals/results.json` | verified (synthetic only) |
| GT_k1 residual exposure in modeled W\* 0.00–0.01 vs B0 0.85–0.87 | report family tables | verified (synthetic only) |
| GHOSTTRACE plans broke no hard flow (0/100 per family); B1 broke one in 0.62–0.75 | report family tables | verified (synthetic only) |
| Evidence-attack success 0 for GHOSTTRACE vs 0.46–0.51 for B2 | report family tables | verified (synthetic only; metric definition in docs/evaluation.md) |
| GT_k0 regret vs brute-force optimum = 0 (small family) | report small family | verified |
| Calibration: d = 1 plans reopened ≈ 0.28–0.33 of the time under the synthetic prior p = 0.3 | report calibration sections | verified (valid only under the synthetic prior) |
| Warm-start speedup ≈1.1–1.6× (noisy timings, n = 5 per size) | report scaling table | verified (modest; small sample n = 5 per size) |
| Hot-query latencies (snapshot ≈ 4 ms, path enumeration ≈ 2 ms on scenario A) | `docs/performance-profiles.md` | verified (single laptop, indicative) |
