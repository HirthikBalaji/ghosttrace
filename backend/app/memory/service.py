"""Durable, poison-resistant memory (§8), stored as :Memory nodes in the workspace graph.

- provenance: every memory links DERIVED_FROM its SourceRecords; unresolved citations => quarantine
- taint: derived from content with embedded instructions, possible_false_flag evidence, or only
  attacker-influenceable sources. Tainted memory is retrievable (shown as tainted) but never promoted
  and never relied on for a certificate.
- promotion: episodic -> semantic only with >= 2 independent roots, not disputed, not tainted
- supersession: corrections create a new memory that SUPERSEDES the old one (history preserved)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from app.graph import queries as Q
from app.graph.repository import Repository, now_ms
from app.model import SourceRecord
from app.reasoning.evidence import independent_root_count
from app.security.injection import contains_instructions

CATEGORIES = ("episodic", "semantic", "procedural")
SECRET_RX = re.compile(r"(AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|ghp_[A-Za-z0-9]{20,}|"
                       r"xox[baprs]-[A-Za-z0-9-]{10,}|(?i:password\s*[:=]\s*\S+))")
MAX_CONTENT = 2000
DEFAULT_FRESHNESS_DAYS = {"episodic": 365, "semantic": 90, "procedural": 180}


@dataclass
class MemoryDraft:
    category: str
    content: str
    source_ids: list[str]
    investigation_id: str | None
    entity_ids: list[str] = field(default_factory=list)
    created_by: str = "memory_curator"
    disputed: bool = False
    false_flag: bool = False
    created_at: int | None = None
    memory_id: str | None = None


def _mid(d: MemoryDraft) -> str:
    h = hashlib.sha256(f"{d.category}|{d.investigation_id}|{d.content}|{sorted(d.source_ids)}".encode()).hexdigest()
    return f"mem_{h[:16]}"


def assess(d: MemoryDraft, sources: dict[str, SourceRecord]) -> tuple[str, bool, list[str]]:
    """Return (status, taint, reasons). Pure; unit-tested."""
    reasons: list[str] = []
    if d.category not in CATEGORIES:
        return "quarantined", True, [f"unknown category {d.category}"]
    if not d.content or len(d.content) > MAX_CONTENT:
        return "quarantined", True, ["empty or oversized content"]
    if SECRET_RX.search(d.content):
        return "quarantined", True, ["content looks like a secret; memory must not hold secrets"]
    missing = [s for s in d.source_ids if s not in sources]
    if missing or not d.source_ids:
        return "quarantined", True, [f"citations do not resolve: {missing or 'no sources'}"]
    taint = False
    if contains_instructions(d.content) or any(sources[s].contains_instructions for s in d.source_ids):
        taint = True
        reasons.append("derived from content containing embedded instructions")
    if all(sources[s].attacker_influenceable for s in d.source_ids):
        taint = True
        reasons.append("only attacker-influenceable sources")
    if d.false_flag:
        taint = True
        reasons.append("derived from possible_false_flag evidence")
    return "active", taint, reasons


def can_promote(d: MemoryDraft, sources: dict[str, SourceRecord], taint: bool) -> tuple[bool, str]:
    if taint:
        return False, "tainted memory cannot be promoted"
    if d.disputed:
        return False, "disputed: a disputed hypothesis is never stored as an unqualified fact"
    roots = independent_root_count(d.source_ids, sources)
    if roots < 2:
        return False, f"only {roots} independent root(s); promotion requires >= 2"
    return True, f"{roots} independent roots"


class MemoryService:
    def __init__(self, repo: Repository):
        self.repo = repo

    def write(self, d: MemoryDraft, sources: dict[str, SourceRecord] | None = None) -> dict[str, Any]:
        sources = sources if sources is not None else self.repo.sources()
        status, taint, reasons = assess(d, sources)
        mid = d.memory_id or _mid(d)
        created = d.created_at or now_ms()
        props = {
            "memory_id": mid, "workspace_id": self.repo.ws, "category": d.category, "content": d.content,
            "source_ids": sorted(d.source_ids), "entity_ids": sorted(d.entity_ids),
            "investigation_id": d.investigation_id or "", "scope": "investigation" if d.investigation_id else "workspace",
            "created_at": created, "freshness_days": DEFAULT_FRESHNESS_DAYS.get(d.category, 90),
            "expires_at": created + DEFAULT_FRESHNESS_DAYS.get(d.category, 90) * 86_400_000,
            "taint": taint, "taint_reasons": reasons, "status": status, "created_by": d.created_by,
            "disputed": d.disputed,
        }
        self.repo.rw(Q.UPSERT_MEMORY, {"id": mid, "props": props, "source_ids": [s for s in d.source_ids if s in sources]})
        if d.investigation_id:
            self.repo.rw(Q.LINK_MEMORY_INV, {"id": mid, "inv": d.investigation_id})
        return props

    def promote(self, d: MemoryDraft, episodic_id: str, sources: dict[str, SourceRecord] | None = None) -> dict[str, Any]:
        sources = sources if sources is not None else self.repo.sources()
        status, taint, reasons = assess(d, sources)
        ok, why = can_promote(d, sources, taint or status != "active")
        if not ok:
            return {"promoted": False, "reason": why, "episodic_id": episodic_id}
        sem = MemoryDraft("semantic", d.content, d.source_ids, None, d.entity_ids, created_by="memory_curator:promotion")
        props = self.write(sem, sources)
        self.repo.rw(Q.UPDATE_MEMORY, {"id": props["memory_id"], "props": {"promoted_from": episodic_id}})
        return {"promoted": True, "reason": why, "memory_id": props["memory_id"], "episodic_id": episodic_id}

    def correct(self, old_id: str, new: MemoryDraft) -> dict[str, Any]:
        props = self.write(new)
        self.repo.rw(Q.SUPERSEDE_MEMORY, {"new": props["memory_id"], "old": old_id, "now": now_ms()})
        return props

    def quarantine(self, memory_id: str, reason: str) -> None:
        self.repo.rw(Q.UPDATE_MEMORY, {"id": memory_id, "props": {"status": "quarantined",
                                                                   "quarantine_reason": reason}})

    def list(self, limit: int = 200) -> list[dict[str, Any]]:
        return [dict(p) for (p,) in self.repo.ro(Q.LIST_MEMORY, {"limit": max(1, min(limit, 500))})]

    def relevant(self, entity_ids: list[str], source_ids: list[str], now: int, limit: int = 20) -> list[dict[str, Any]]:
        """Graph-relevance retrieval: provenance or entity overlap with the active investigation."""
        out = []
        for p, ent, src in self.repo.ro(Q.RELEVANT_MEMORY, {"entity_ids": entity_ids, "source_ids": source_ids,
                                                             "limit": max(1, min(limit, 100))}):
            m = dict(p)
            m["relevance"] = {"entity_overlap": ent, "source_overlap": src}
            m["stale"] = bool(m.get("expires_at") and m["expires_at"] < now)
            m["usable_for_certificate"] = bool(not m.get("taint") and m.get("status") == "active")
            out.append(m)
        return out
