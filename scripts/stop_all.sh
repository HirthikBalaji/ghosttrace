#!/usr/bin/env bash
# Stop all local GHOSTTRACE processes.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "Stopping Frontend (Vite) and Backend (uvicorn)..."
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true

"${ROOT_DIR}/scripts/stop_falkordb.sh"
echo "All local GHOSTTRACE services stopped."
