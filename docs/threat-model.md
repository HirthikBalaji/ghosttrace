# Threat model (STRIDE + LLM-specific)

Scope: both profiles. The local profile is a single-machine demo; the production profile (OIDC, TLS, workers) is the
one to expose to users. Neither executes containment actions.

| Adversary | Threat (STRIDE) | Controls implemented | Evidence |
|---|---|---|---|
| Malicious evidence author | Tampering / elevation via prompt injection in logs, tickets, docs | Source text is never executed or parsed for tool calls. It reaches models only inside a delimited `UNTRUSTED_DATA` block. The heuristic detector flags it, and memory derived from it is tainted. Agents use typed, allowlisted tools only | `test_prompt_injection_treated_as_data`, `app/security/injection.py` |
| Compromised log source | Tampering / spoofing via planted decoys, fake revocations, suppressed records | `attacker_influenceable` derived from the declared compromised set. R1–R3 (decoys become LATENT `possible_false_flag`; fake removals only *dispute*). R4 trust-filtered diff. R5 load-bearing evidence, plus red-team tampering scenarios | `test_evidence.py`, eval "evidence-attack success" |
| Memory poisoner | Tampering via poisoned prior-incident memory | Provenance links, taint, promotion rule (≥2 independent roots, not disputed, not tainted), quarantine on unresolved citations or secret-like content, supersession history. Retrieval is relevance-scoped and memory informs but never decides | `test_poisoned_memory_not_promoted_or_relied_on`, `test_prior_incident_trap_*` |
| Cross-tenant actor | Information disclosure | Graph per workspace, a `workspace_id` filter in every query, workspace id regex, 404 for foreign ids | `test_tenant_isolation_*`, `test_cross_workspace_api_isolation`, `test_memory_workspace_isolation` |
| Tool abuser | DoS / elevation via arbitrary Cypher, deep queries | No endpoint or tool accepts Cypher. All query text is constant. Depth is clamped to 12, limits to ≤ 2000, server timeouts apply on every query. Read-only `GRAPH.RO_QUERY` for reads. Action ids are validated by regex and κ rules. Request body ≤ 256 KiB. Per-workspace rate limits on expensive endpoints | `test_injection_strings_are_inert_parameters`, `test_read_only_path_rejects_writes`, `test_query_timeout_enforced` |
| Supply chain | Malicious or typosquatted packages | Exact pins (`uv.lock`, `package-lock.json`), minimal dependencies (verifier: stdlib only), `pip-audit` + `npm audit` in CI | `make audit` (0 known vulnerabilities at build time) |
| Certificate forger | Tampering / repudiation | Snapshot hash binds header, edges and costs. The independent verifier recomputes κ, reachability, d, flows, cost and small-instance optimality. Mutation-tested | `verifier/tests`, eval mutation kill counts |
| Model misbehaviour | Fabricated facts or ids, malformed output | The model never creates facts or verdicts. Output is Pydantic-validated, and every cited id is checked against graph results. Malformed output is a handled `model` failure, retried once and then surfaced (never faked) | `test_malformed_model_output_fails_honestly` |
| Unauthenticated / wrong-tenant user | Spoofing / elevation | Production: OIDC JWT verified against JWKS, asymmetric algorithms only, `iss`/`aud`/`exp`/`iat`/`sub` required, `alg=none` and HS/RS key confusion rejected; roles and workspace allowlist from claims; `GT_ENV=production` refuses demo auth. Local: demo token, constant-time compare, fails closed. CORS restricted | `tests/test_auth_production.py`, `test_auth_fails_closed` |
| Insider pushing a bad plan | Elevation / repudiation | Approval needs the `approve` role, four-eyes (creator cannot approve), verifier re-check at approval time, explicit acknowledgement of scrutiny-flagged actions; audit trail with subject; no executor | `test_approval_gates` |

## Residual risks (not mitigated)

- **Local profile** has no real authentication and no TLS; use the production profile beyond a single machine.
- The production profile has been verified with a test signing key, not against a specific commercial IdP.
- Rate limits use fixed one-minute windows (bursts at window edges are possible).
- FalkorDB AOF crash-loop on deleted constrained graphs (upstream bug, worked around; recovery script provided).
- The injection detector is heuristic. The structural controls are the boundary; the detector is only a
  tripwire.
- Attacker-influenceable labelling depends on a correct declared threat model.
- If FalkorDB is unreachable, rate limiting falls back to a per-process bucket.
