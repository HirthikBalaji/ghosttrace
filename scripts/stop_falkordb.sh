#!/usr/bin/env bash
# Stop the local native FalkorDB instance.
set -euo pipefail

PORT="${GT_FALKORDB_PORT:-6379}"

if redis-cli -h localhost -p "${PORT}" ping >/dev/null 2>&1; then
  echo "Stopping FalkorDB on port ${PORT}..."
  redis-cli -h localhost -p "${PORT}" shutdown
  echo "✓ FalkorDB stopped"
else
  echo "FalkorDB is not running on port ${PORT}"
fi
