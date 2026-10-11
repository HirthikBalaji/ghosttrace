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
| `GT_LLM_PROVIDER` | `mock` | `openai_compatible` also needs `GT_LLM_ENDPOINT`, `GT_LLM_MODEL`, `GT_LLM_API_KEY` |

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
