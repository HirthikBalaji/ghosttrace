#!/usr/bin/env bash
# Reproduction for docs/upstream/falkordb-aof-unique-constraint-crash.md (uses throwaway container + volume).
# Usage: scripts/repro/falkordb_aof_unique_constraint.sh con_delete   (crashes)  |  idx_delete / con_clear / con_dropcon_rewrite_delete (survive)
# variants: idx_delete (index only, GRAPH.DELETE), con_clear (constraint, clear contents instead of delete)
set -u
docker rm -f gt-repro >/dev/null 2>&1; docker volume rm gt-repro-vol >/dev/null 2>&1
docker run -d --name gt-repro -v gt-repro-vol:/var/lib/falkordb/data -e REDIS_ARGS="--appendonly yes --appendfsync always" falkordb/falkordb:v4.22.0 >/dev/null
sleep 3
R() { docker exec gt-repro redis-cli "$@"; }
for i in 1 2 3; do
  R GRAPH.QUERY g$i "UNWIND range(1,2000) AS x CREATE (:Entity {id: x})" >/dev/null
  R GRAPH.QUERY g$i "CREATE INDEX FOR (n:Entity) ON (n.id)" >/dev/null
  [[ "$1" == con_* ]] && R GRAPH.CONSTRAINT CREATE g$i UNIQUE NODE Entity PROPERTIES 1 id >/dev/null
  if [[ "$1" == con_dropcon_rewrite_delete ]]; then
    R GRAPH.CONSTRAINT DROP g$i UNIQUE NODE Entity PROPERTIES 1 id >/dev/null
    until [[ "$(R GRAPH.QUERY g$i "CALL db.constraints() YIELD type RETURN count(type)" | sed -n 2p)" == "0" ]]; do sleep 0.1; done
    R BGREWRITEAOF >/dev/null; until R INFO persistence | grep -q "aof_rewrite_in_progress:0"; do sleep 0.1; done; sleep 0.5
    R GRAPH.DELETE g$i >/dev/null
  elif [[ "$1" == con_dropcon_delete ]]; then
    R GRAPH.CONSTRAINT DROP g$i UNIQUE NODE Entity PROPERTIES 1 id >/dev/null
    until [[ "$(R GRAPH.QUERY g$i "CALL db.constraints() YIELD type RETURN count(type)" | sed -n 2p)" == "0" ]]; do sleep 0.1; done
    R GRAPH.DELETE g$i >/dev/null
  elif [[ "$1" == *_delete ]]; then R GRAPH.DELETE g$i >/dev/null; else R GRAPH.QUERY g$i "MATCH (n) DETACH DELETE n" >/dev/null; fi
done
sleep 2
for r in 1 2 3; do docker restart gt-repro >/dev/null; sleep 6; done
echo "$1: running=$(docker inspect -f '{{.State.Running}}' gt-repro) crash-lines=$(docker logs gt-repro 2>&1 | grep -c 'crashed by signal')"
docker rm -f gt-repro >/dev/null; docker volume rm gt-repro-vol >/dev/null
