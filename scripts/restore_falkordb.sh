#!/usr/bin/env bash
# Restore a backup into the compose FalkorDB volume (stops FalkorDB briefly). Usage: scripts/restore_falkordb.sh backups/x.tgz
set -euo pipefail
cd "$(dirname "$0")/.."
f="${1:?usage: restore_falkordb.sh <backup.tgz>}"
docker compose stop falkordb
vol="$(docker compose config --format json | python3 -c 'import json,sys;print(json.load(sys.stdin)["name"])')_falkordb-data"
docker run --rm -v "$vol:/data" -v "$PWD/$(dirname "$f"):/b:ro" alpine:3.22 sh -c "rm -rf /data/* && tar -C /data -xzf /b/$(basename "$f")"
docker compose start falkordb
echo "restored $f into volume $vol"
