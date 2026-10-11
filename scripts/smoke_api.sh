#!/usr/bin/env bash
# Smoke-test the running API end to end (synthetic demo). Usage: GT_DEMO_TOKEN=... scripts/smoke_api.sh [base_url]
set -euo pipefail
BASE="${1:-http://localhost:8000}"
TOKEN="${GT_DEMO_TOKEN:?set GT_DEMO_TOKEN}"
H=(-H "X-GT-Demo-Token: ${TOKEN}" -H "Content-Type: application/json")
j() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1]))" "$1"; }
echo "health: $(curl -sf "$BASE/health")"
echo "ready:  $(curl -sf "$BASE/ready")"
curl -sf "${H[@]}" -X POST "$BASE/api/v1/scenarios/ghost_credential_a/reset" | j "d['data']['edge_versions']" >/dev/null
INV=$(curl -sf "${H[@]}" -X POST -d '{}' "$BASE/api/v1/investigations" | j "d['data']['id']")
echo "investigation: $INV"
echo "run: $(curl -sf "${H[@]}" -X POST "$BASE/api/v1/investigations/$INV/run?sync=true" | j "d['data']['investigation']['status']")"
echo "pareto: $(curl -sf "${H[@]}" "$BASE/api/v1/investigations/$INV/containment" | j "[(p['k'], p['total_cost']) for p in d['data']['planner']['pareto']]")"
CID=$(curl -sf "${H[@]}" "$BASE/api/v1/investigations/$INV/containment" | j "d['data']['certificates'][0]['certificate_id']")
echo "verify $CID: $(curl -sf "${H[@]}" -X POST "$BASE/api/v1/investigations/$INV/certificate/$CID/verify" | j "(d['data']['accepted'], d['data']['output'])")"
echo "B0 simulate: $(curl -sf "${H[@]}" -X POST -d '{"action_ids":["disable_identity:id:dev-alice"]}' "$BASE/api/v1/investigations/$INV/containment/simulate" | j "d['data']['certificate']['status']")"
echo "owner as known then: $(curl -sf "${H[@]}" "$BASE/api/v1/company/owners?service_id=svc:payments-api&asof_T=2026-03-02T09:00:00Z&known_tau=2026-03-02T09:00:00Z" | j "d['data']['primary'][0]['team_id']")"
echo "owner as known now:  $(curl -sf "${H[@]}" "$BASE/api/v1/company/owners?service_id=svc:payments-api&asof_T=2026-03-02T09:00:00Z" | j "d['data']['primary'][0]['team_id']")"
code=$(curl -s -o /dev/null -w '%{http_code}' "${H[@]}" "$BASE/api/v1/company/owners?service_id=svc:payments-api&asof_T=2026-03-02T09:00:00")
echo "naive datetime rejected: HTTP $code"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/api/v1/scenarios")
echo "no token: HTTP $code"
echo "SMOKE OK"
