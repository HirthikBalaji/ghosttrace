#!/usr/bin/env bash
# Back up the compose FalkorDB volume: BGSAVE, then tar the data dir. Usage: scripts/backup_falkordb.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
docker compose exec -T falkordb redis-cli BGSAVE >/dev/null
for _ in $(seq 1 30); do
  [[ "$(docker compose exec -T falkordb redis-cli INFO persistence | grep -c 'rdb_bgsave_in_progress:0')" == 1 ]] && break; sleep 1
done
f="backups/falkordb-$(date -u +%Y%m%dT%H%M%SZ).tgz"
docker compose exec -T falkordb tar -C /var/lib/falkordb/data -czf - . > "$f"
echo "backup written: $f ($(du -h "$f" | cut -f1))"
