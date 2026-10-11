# Operations

## Configuration (12-factor, prefix `GT_`)

| Variable | Default | Notes |
|---|---|---|
| `GT_DEMO_TOKEN` | unset → API returns 401 (fail closed) | demo-only shared token |
| `GT_AUTH_MODE` | `demo_header` | `disabled_local` accepted only with `GT_ENV=local` |
| `GT_ENV` | `local` | `local` / `test` / `ci` |
| `GT_FALKORDB_HOST` / `GT_FALKORDB_PORT` / `GT_FALKORDB_PASSWORD` | localhost / 6379 / — | |
| `GT_QUERY_TIMEOUT_MS` | 2000 | server-side timeout for every query |
| `GT_CORS_ORIGINS` | localhost dev origins | comma-separated |
| `GT_RATE_LIMIT_PER_MINUTE` | 60 | per workspace and expensive endpoint |
| `GT_LLM_PROVIDER` | `mock` | `anthropic` (official SDK; credentials from `ANTHROPIC_API_KEY` or `ant auth login`; model `GT_LLM_MODEL`, default `claude-opus-5-5`), or `openai_compatible` (needs `GT_LLM_ENDPOINT`, `GT_LLM_MODEL`, `GT_LLM_API_KEY`) |
| `GT_ENV` = `production` | — | requires `GT_AUTH_MODE=oidc`; startup fails otherwise |
| `GT_OIDC_ISSUER` / `GT_OIDC_AUDIENCE` | — | required in `oidc` mode |
| `GT_OIDC_JWKS_URL` / `GT_OIDC_JWKS_JSON` | — | one is required; the URL must be https in production; JSON pins keys (air-gapped) |
| `GT_OIDC_ALGORITHMS` | `RS256,ES256` | asymmetric algorithms only |
| `GT_OIDC_ROLES_CLAIM` / `GT_OIDC_WORKSPACES_CLAIM` | `roles` / `gt_workspaces` | dotted paths allowed (e.g. `realm_access.roles`); `"*"` grants all workspaces |
| `GT_RUN_MODE` | `inline` | `queue`: the API enqueues, `python -m app.worker` replicas run investigations |
| `GT_REQUIRE_FOUR_EYES` | `true` | in OIDC mode, the creator of an investigation cannot approve its plans |

## Liveness, readiness, metrics

- `GET /health` — process liveness; never touches the graph.
- `GET /ready` — 200 only when FalkorDB answers. It reports the schema version per workspace and never returns
  connection strings.
- `GET /metrics` — Prometheus-style counters.
- Logs are JSON lines with `request_id`. `X-Request-ID` is echoed in responses. Secrets are redacted.

## Persistence

Compose runs FalkorDB with `--appendonly yes --appendfsync everysec --save 60 1 --save 300 10` on the named
volume `falkordb-data` (`/var/lib/falkordb/data`). `tests/test_docker_persistence.py`
(`GT_RUN_DOCKER_TESTS=1`) seeds a scenario, crashes an investigation mid-pipeline and restarts the FalkorDB
container. It then checks that tasks, handoffs and memory survived and that a fresh orchestrator resumes
without re-running completed stages.

## Backup and restore (tested on the Compose stack)

```bash
scripts/backup_falkordb.sh                         # BGSAVE + tar of the data dir → backups/falkordb-<ts>.tgz
scripts/restore_falkordb.sh backups/falkordb-<ts>.tgz   # stops FalkorDB, replaces volume contents, restarts
```

These scripts were verified by deleting `ws:demo`, restoring, and confirming the investigation was back.

## Lifecycle

- Migrations run on seed and reset (`Repository.init_schema`). They are idempotent and versioned
  (`:SchemaVersion`).
- Graceful shutdown: uvicorn `--timeout-graceful-shutdown 10`. Interrupted investigations keep their persisted
  state, and `resume_stale` re-runs them on the next start.
- Containers run as non-root. The backend container has a read-only root filesystem, tmpfs for verifier
  scratch files and `no-new-privileges`. Resource limits are set in Compose. Ports bind to 127.0.0.1.

## Demo reset

`make seed` (or the UI's "Reset scenario & investigate"). Either one drops and re-seeds the workspace graph.

## MCP (read-only)

```bash
cd backend && GT_MCP_WORKSPACE=demo uv run python -m app.mcp_server
```

This speaks JSON-RPC 2.0 over stdio. Methods: `initialize`, `tools/list`, `tools/call`. The tools are
`find_attack_paths`, `get_service_owners`, `get_asset_dependencies`, `get_evidence`, `get_price_of_certainty`
and `get_memory`. All are read-only and validated, and unknown arguments are rejected. MCP is an interface,
not a security boundary.

## Production profile

`docker-compose.prod.yml` overlays the base file (see README). Required variables: `GT_DOMAIN`, `GT_TLS`
(`internal` or an ACME e-mail), `GT_FALKORDB_PASSWORD`, `GT_OIDC_ISSUER`, `GT_OIDC_AUDIENCE`, `GT_OIDC_JWKS_URL`
(or `GT_OIDC_JWKS_JSON`), `GT_OIDC_CLIENT_ID` (public SPA client, authorization code + PKCE, redirect URI
`https://<GT_DOMAIN>/`), and `GT_OIDC_ORIGIN` (added to the UI's CSP `connect-src`). The IdP must issue access
tokens with `aud = GT_OIDC_AUDIENCE`, a roles claim and a workspaces claim.

Verified locally on 2026-10-11 (test signing key, `GT_DOMAIN=localhost`, `GT_TLS=internal`): no token or demo header
→ 401; viewer reset → 403; admin reset → 200; analyst run → queued → completed by a worker replica; creator approval
→ 403 (four-eyes); second approver → approved with verifier re-check; HSTS present; wrong FalkorDB password rejected;
FalkorDB port not reachable from the host.

## Schema migrations

Run automatically at API start for every workspace (`python -m app.migrate` runs them on demand). Migration 3 drops
legacy unique constraints and compacts the AOF (see below).

## FalkorDB AOF crash-loop (known upstream issue) and recovery

FalkorDB v4.22.0 with AOF persistence crash-loops after restart if a graph that had a unique constraint was deleted
(`docs/upstream/falkordb-aof-unique-constraint-crash.md`). GHOSTTRACE no longer creates unique constraints. If a
volume is already affected (server segfaults while "Reading RDB base file on AOF loading"), run:

```bash
scripts/recover_falkordb_aof.sh            # loads the last dump.rdb with AOF off, regenerates a clean AOF
```

Writes after the last RDB save are lost; the broken AOF is kept as `appendonlydir.broken-<timestamp>`. Never run the
integration test suite against a persistent instance (the suite refuses unless `GT_TESTS_ALLOW_PERSISTENT=1`).
