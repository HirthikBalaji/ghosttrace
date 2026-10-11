#!/usr/bin/env bash
# Recover a FalkorDB volume whose append-only file can no longer be replayed (server crash-loops on start).
# Loads the last RDB snapshot (dump.rdb) with AOF disabled, then regenerates a clean AOF from that state.
# Writes after the last RDB save are lost; the broken AOF directory is kept as appendonlydir.broken-<ts>.
# Usage: scripts/recover_falkordb_aof.sh [volume]   (default: the compose project's falkordb-data volume)
set -euo pipefail
cd "$(dirname "$0")/.."
vol="${1:-$(docker compose config --format json | python3 -c 'import json,sys;print(json.load(sys.stdin)["name"])')_falkordb-data}"
image="falkordb/falkordb:v4.22.0"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
docker compose stop falkordb >/dev/null 2>&1 || true
docker run --rm -v "$vol:/data" alpine:3.22 sh -c "
  test -f /data/dump.rdb || { echo 'no dump.rdb snapshot in volume: cannot recover from RDB'; exit 2; }
  echo \"RDB snapshot: \$(stat -c '%y' /data/dump.rdb)\"
  if [ -d /data/appendonlydir ]; then mv /data/appendonlydir /data/appendonlydir.broken-$ts; fi"
docker rm -f gt-recover >/dev/null 2>&1 || true
docker run -d --name gt-recover -v "$vol:/var/lib/falkordb/data" -e REDIS_ARGS="--appendonly no" "$image" >/dev/null
for _ in $(seq 1 60); do docker exec gt-recover redis-cli ping >/dev/null 2>&1 && break; sleep 1; done
echo "graphs loaded from RDB: $(docker exec gt-recover redis-cli GRAPH.LIST | wc -l | tr -d ' ')"
docker exec gt-recover redis-cli CONFIG SET appendonly yes >/dev/null
for _ in $(seq 1 120); do
  docker exec gt-recover redis-cli INFO persistence | grep -q "aof_rewrite_in_progress:0" && \
    docker exec gt-recover redis-cli INFO persistence | grep -q "aof_enabled:1" && break; sleep 1
done
docker exec gt-recover redis-cli SAVE >/dev/null
docker rm -f gt-recover >/dev/null
docker compose start falkordb >/dev/null
echo "recovered; broken AOF kept as appendonlydir.broken-$ts"
