"""D. Company Brain — ownership / expertise / dependency / runbook / decision provenance.

Graph traversal first (constant Cypher with the shared bitemporal predicate). Every answer carries the
supporting edge ids, source ids, its temporal scope (T, tau), freshness/contradiction warnings and
explicit unknowns.
"""

from __future__ import annotations

from typing import Any

from app.agents.schemas import BrainAnswer, BrainQuery
from app.graph import queries as Q
from app.graph.repository import Repository
from app.reasoning.evidence import meets_r1
from app.temporal.predicate import to_iso

TRUST_RANK = {"high": 2, "medium": 1, "low": 0}


class CompanyBrain:
    def __init__(self, repo: Repository):
        self.repo = repo

    def ask(self, q: BrainQuery) -> BrainAnswer:
        ans: BrainAnswer = getattr(self, f"_{q.question}")(q)
        return ans

    def _scope(self, q: BrainQuery) -> dict[str, Any]:
        return {
            "T": q.T,
            "tau": q.tau,
            "T_iso": to_iso(q.T),
            "tau_iso": to_iso(q.tau),
            "meaning": "facts valid at world time T, as known at knowledge time tau",
        }

    def _sources(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        return {p["source_id"]: dict(p) for (p,) in self.repo.ro(Q.SOURCES_BY_IDS, {"ids": ids})} if ids else {}

    def _owner(self, q: BrainQuery) -> BrainAnswer:
        keys = (
            "team_id",
            "team_name",
            "edge_id",
            "version",
            "source_ids",
            "validity_unknown",
            "stale",
            "valid_from",
            "valid_to",
            "tx_from",
        )
        rows = [dict(zip(keys, r, strict=True)) for r in self.repo.ro(Q.OWNERS, {"sid": q.subject_id, "T": q.T, "tau": q.tau})]
        all_src = sorted({s for r in rows for s in (r["source_ids"] or [])})
        srcs = self._sources(all_src)
        sources_rec = self.repo.sources()
        warnings: list[str] = []
        scored = []
        for r in rows:
            rs = [srcs[s] for s in r["source_ids"] or [] if s in srcs]
            best_trust = max((TRUST_RANK.get(s.get("trust_class", "low"), 0) for s in rs), default=0)
            strong = meets_r1(r["source_ids"] or [], sources_rec)
            r["trust"] = best_trust
            r["meets_r1"] = strong
            r["learned_at"] = to_iso(r["tx_from"])
            r["valid_from_iso"], r["valid_to_iso"] = to_iso(r["valid_from"]), to_iso(r["valid_to"])
            if r["stale"]:
                warnings.append(f"{r['team_id']}: record flagged stale (source last verified long ago)")
            if r["validity_unknown"]:
                warnings.append(f"{r['team_id']}: validity interval unknown (undated record) — uncertain, not current")
            if not strong:
                warnings.append(f"{r['team_id']}: weakly supported (fails R1)")
            scored.append(((not r["validity_unknown"], not r["stale"], strong, best_trust), r))
        scored.sort(key=lambda x: x[0], reverse=True)
        primary = [scored[0][1]] if scored else []
        others = [r for _, r in scored[1:]]
        contradictions = [{"a": a, "b": b} for a, b in self.repo.ro(Q.CONTRADICTIONS_FOR, {"ids": all_src})]
        if others:
            contradictions.append({"conflicting_owner_facts": [o["edge_id"] for o in others]})
        members: list[dict[str, Any]] = []
        for p in primary:
            members = [
                dict(zip(("person_id", "name", "edge_id", "source_ids"), m, strict=True))
                for m in self.repo.ro(Q.TEAM_MEMBERS, {"tid": p["team_id"], "T": q.T, "tau": q.tau})
            ]
            p["members"] = members
        if primary:
            p0 = primary[0]
            ans = (
                f"{p0['team_name']} ({p0['team_id']}) owned {q.subject_id} at {to_iso(q.T)}, as known at "
                f"{to_iso(q.tau)}"
                + (" — but this record is stale/weak; treat with caution" if (p0["stale"] or not p0["meets_r1"]) else "")
                + (f". {len(others)} conflicting record(s) shown." if others else ".")
            )
        else:
            ans = f"No ownership fact for {q.subject_id} is valid at {to_iso(q.T)} as known at {to_iso(q.tau)}."
        unknowns = [] if primary else ["owner unknown at this (T, tau)"]
        return BrainAnswer(
            question="owner",
            subject_id=q.subject_id,
            answer=ans,
            primary=primary + others,
            supporting_edge_ids=[r["edge_id"] for r in rows] + [m["edge_id"] for m in members],
            source_ids=all_src,
            temporal_scope=self._scope(q),
            warnings=warnings,
            contradictions=contradictions,
            unknowns=unknowns,
        )

    def _experts(self, q: BrainQuery) -> BrainAnswer:
        rows = [
            dict(zip(("person_id", "name", "edge_id", "source_ids"), r, strict=True))
            for r in self.repo.ro(Q.EXPERTS, {"sid": q.subject_id, "T": q.T, "tau": q.tau})
        ]
        src = sorted({s for r in rows for s in r["source_ids"] or []})
        return BrainAnswer(
            question="experts",
            subject_id=q.subject_id,
            answer=(", ".join(r["name"] for r in rows) + f" know about {q.subject_id}")
            if rows
            else f"No recorded expertise for {q.subject_id} at this (T, tau).",
            primary=rows,
            supporting_edge_ids=[r["edge_id"] for r in rows],
            source_ids=src,
            temporal_scope=self._scope(q),
            warnings=[],
            contradictions=[],
            unknowns=[] if rows else ["no KNOWS_ABOUT facts"],
        )

    def _deps(self, q: BrainQuery, query: str, label: str) -> BrainAnswer:
        rows = self.repo.ro(query, {"sid": q.subject_id, "T": q.T, "tau": q.tau})
        paths = [list(n) for n, _ in rows]
        eids = sorted({e for _, es in rows for e in es})
        nodes = sorted({n for p in paths for n in p if n != q.subject_id})
        return BrainAnswer(
            question=label,
            subject_id=q.subject_id,
            answer=(f"{len(nodes)} {label}: " + ", ".join(nodes)) if nodes else f"No {label} recorded.",
            primary=[{"node_id": n} for n in nodes],
            supporting_edge_ids=eids,
            source_ids=[],
            temporal_scope=self._scope(q),
            warnings=[],
            contradictions=[],
            unknowns=[] if nodes else [f"no {label} facts at this (T, tau)"],
            paths=paths,
        )

    def _dependencies(self, q: BrainQuery) -> BrainAnswer:
        return self._deps(q, Q.DEPENDENCIES, "dependencies")

    def _dependents(self, q: BrainQuery) -> BrainAnswer:
        return self._deps(q, Q.DEPENDENTS, "dependents")

    def _runbooks(self, q: BrainQuery) -> BrainAnswer:
        keys = ("id", "name", "text", "valid_from", "applies_to", "edge_id", "source_ids")
        rows = [
            dict(zip(keys, r, strict=True)) for r in self.repo.ro(Q.RUNBOOKS_FOR, {"ids": [q.subject_id], "T": q.T, "tau": q.tau})
        ]
        return BrainAnswer(
            question="runbooks",
            subject_id=q.subject_id,
            answer="; ".join(f"{r['name']}: {r['text']}" for r in rows) or "No runbook applies.",
            primary=rows,
            supporting_edge_ids=[r["edge_id"] for r in rows],
            source_ids=sorted({s for r in rows for s in r["source_ids"] or []}),
            temporal_scope=self._scope(q),
            warnings=["Runbook text is guidance, not a verified plan; check it against current graph facts."] if rows else [],
            contradictions=[],
            unknowns=[] if rows else ["no runbook"],
        )

    def _decisions(self, q: BrainQuery) -> BrainAnswer:
        keys = ("id", "name", "text", "decided_at", "affects", "edge_id", "source_ids", "doc_id", "doc_name")
        rows = [
            dict(zip(keys, r, strict=True))
            for r in self.repo.ro(Q.DECISIONS_FOR, {"ids": [q.subject_id], "T": q.T, "tau": q.tau})
        ]
        return BrainAnswer(
            question="decisions",
            subject_id=q.subject_id,
            answer="; ".join(f"{r['name']} — {r['text']} (recorded in {r['doc_name']})" for r in rows)
            or "No recorded decision affects this entity.",
            primary=rows,
            supporting_edge_ids=[r["edge_id"] for r in rows],
            source_ids=sorted({s for r in rows for s in r["source_ids"] or []}),
            temporal_scope=self._scope(q),
            warnings=[],
            contradictions=[],
            unknowns=[] if rows else ["no decision record"],
        )
