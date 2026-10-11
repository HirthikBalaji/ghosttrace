#!/usr/bin/env bash
# Verify the toolchain and that the pinned FalkorDB client works against a live server.
set -uo pipefail
ok=1
need() { if command -v "$1" >/dev/null; then echo "✓ $1: $($1 --version 2>&1 | head -1)"; else echo "✗ $1 missing"; ok=0; fi; }
need uv; need node; need npm; need docker
cd "$(dirname "$0")/../backend" || exit 1
uv run python - <<'PY' || ok=0
import sys
from app.graph.client import GraphClient
c = GraphClient()
if not c.ping():
    sys.exit("✗ FalkorDB not reachable on GT_FALKORDB_HOST/PORT (try: make falkordb)")
ws = "envcheck"
c.rw(ws, "CREATE (:Entity {id: 'a', workspace_id: $ws})", {"ws": ws})
assert c.ro(ws, "MATCH (n:Entity {id: $id}) RETURN count(n)", {"id": "a"})[0][0] == 1
try:
    c.ro(ws, "CREATE (:X)")
    sys.exit("✗ ro_query accepted a write")
except Exception:
    pass
c.drop_workspace(ws)
print("✓ FalkorDB reachable; parameterised query, ro_query write-rejection verified")
PY
[[ $ok == 1 ]] && echo "environment OK" || { echo "environment check FAILED"; exit 1; }
