#!/usr/bin/env bash
# Start FalkorDB locally on macOS without Docker using redis-server + FalkorDB module.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${GT_FALKORDB_PORT:-6379}"
DATA_DIR="${ROOT_DIR}/data/falkordb"
MODULE_PATH="${ROOT_DIR}/bin/falkordb.so"

mkdir -p "${DATA_DIR}" "${ROOT_DIR}/bin"

# Check if redis-server is installed
if ! command -v redis-server >/dev/null 2>&1; then
  echo "redis-server not found. Installing via Homebrew..."
  brew install redis
fi

# Ensure falkordb.so module is present
if [ ! -f "${MODULE_PATH}" ]; then
  echo "Downloading FalkorDB macOS ARM64 module..."
  curl -fsSL -o "${MODULE_PATH}" "https://github.com/FalkorDB/FalkorDB/releases/download/v4.22.0/falkordb-macos-arm64v8.so"
  chmod +x "${MODULE_PATH}"
fi

# Check if already running on the target port
if redis-cli -h localhost -p "${PORT}" ping >/dev/null 2>&1; then
  echo "✓ FalkorDB is already running on port ${PORT}"
  exit 0
fi

echo "Starting FalkorDB on port ${PORT}..."
redis-server \
  --port "${PORT}" \
  --dir "${DATA_DIR}" \
  --loadmodule "${MODULE_PATH}" MAX_QUEUED_QUERIES 25 TIMEOUT 5000 RESULTSET_SIZE 10000 \
  --appendonly yes \
  --appendfsync everysec \
  --save 60 1 \
  --save 300 10 \
  --daemonize yes

# Wait for ping
for i in $(seq 1 10); do
  if redis-cli -h localhost -p "${PORT}" ping >/dev/null 2>&1; then
    echo "✓ FalkorDB started successfully on port ${PORT}"
    exit 0
  fi
  sleep 0.5
done

echo "✗ Failed to start FalkorDB on port ${PORT}" >&2
exit 1
