#!/usr/bin/env bash
# Start all GHOSTTRACE services (FalkorDB, Backend API, Frontend UI) without Docker.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT_DIR}"

export GT_DEMO_TOKEN="${GT_DEMO_TOKEN:-dev-demo-token}"
export GT_FALKORDB_PORT="${GT_FALKORDB_PORT:-6379}"
export GT_FALKORDB_HOST="${GT_FALKORDB_HOST:-localhost}"
export VITE_GT_DEMO_TOKEN="${GT_DEMO_TOKEN}"

# 1. Start FalkorDB
"${ROOT_DIR}/scripts/start_falkordb.sh"

# 2. Seed demo workspace if needed
echo "Seeding demo workspace..."
cd "${ROOT_DIR}/backend"
uv run python ../scripts/seed_demo.py ghost_credential_a demo >/dev/null 2>&1 || true

# 3. Start Backend API
echo "Starting Backend API on http://localhost:8000..."
cd "${ROOT_DIR}/backend"
uv run uvicorn app.main:app --port 8000 &
BACKEND_PID=$!

# 4. Start Frontend UI
echo "Starting Frontend UI on http://localhost:5174..."
cd "${ROOT_DIR}/frontend"
npm run dev &
FRONTEND_PID=$!

cleanup() {
  echo ""
  echo "Shutting down..."
  kill "${BACKEND_PID}" 2>/dev/null || true
  kill "${FRONTEND_PID}" 2>/dev/null || true
  wait "${BACKEND_PID}" 2>/dev/null || true
  wait "${FRONTEND_PID}" 2>/dev/null || true
  echo "Services stopped."
}

trap cleanup INT TERM EXIT

echo ""
echo "=========================================="
echo " GHOSTTRACE is running without Docker!"
echo " UI:      http://localhost:5174"
echo " API:     http://localhost:8000"
echo " Docs:    http://localhost:8000/docs"
echo " DB:      FalkorDB on port ${GT_FALKORDB_PORT}"
echo " Token:   ${GT_DEMO_TOKEN}"
echo "=========================================="
echo "Press Ctrl+C to stop the app."
echo ""

wait
