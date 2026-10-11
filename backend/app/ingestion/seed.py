"""Seed / reset a workspace from a synthetic scenario (idempotent)."""

from __future__ import annotations

from typing import Any

from app.graph.client import GraphClient
from app.graph.repository import Repository
from app.ingestion.ledger import IngestionError
from app.ingestion.scenario import load, read_scenario
from app.memory.service import MemoryDraft, MemoryService
from app.reasoning.latent import TEMPLATES
from app.temporal.predicate import parse_iso


def cypher_precondition(repo: Repository, template_id: str, src: str, dst: str, at: int) -> bool:
    rows = repo.ro(TEMPLATES[template_id].cypher, {"src": src, "dst": dst, "T": at, "tau": at})
    return bool(rows and rows[0][0])


def seed(client: GraphClient, workspace_id: str, scenario_id: str, reset: bool = True) -> dict[str, Any]:
    repo = Repository(client, workspace_id)
    if reset:
        repo.reset()
    else:
        repo.init_schema()
    led, meta = load(read_scenario(scenario_id), workspace_id)
    stats = repo.persist_ledger(led, meta)
    # Differential guard in the live path: every latent accepted by the Python mirror must also satisfy
    # its constant Cypher precondition in FalkorDB; every rejected one must not.
    for n in meta.nominations:
        type_rejected = not n["accepted"] and n["reason"] != "preconditions not satisfied by the graph"
        if type_rejected:
            continue
        ok = cypher_precondition(repo, n["template_id"], n["src"], n["dst"], n["at"])
        if ok != n["accepted"]:
            raise IngestionError(f"precondition mismatch (Cypher={ok}) for nomination {n}")
        n["cypher_verified"] = True
    mem = MemoryService(repo)
    sources = repo.sources()
    for m in meta.memory_seed:
        mem.write(MemoryDraft(category=m["category"], content=m["content"], source_ids=m["source_ids"],
                              investigation_id=None, entity_ids=m.get("entity_ids", []), created_by="seed",
                              created_at=parse_iso(m["created_at"]), memory_id=m["memory_id"]), sources)
    stats["nominations"] = meta.nominations
    stats["scenario_id"] = scenario_id
    stats["workspace_id"] = workspace_id
    return stats
