"""Bitemporal fact ledger: idempotent ingestion with supersession (never deletion).

Pure in-memory state machine. The FalkorDB repository persists its versions; re-ingesting the same
event stream produces exactly the same versions (stable ids), so writes are idempotent MERGEs.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable
from typing import Any

from app.model import ALL_FACT_EDGE_TYPES, EdgeVersion, Node, SourceRecord
from app.reasoning.evidence import trusted_removal
from app.temporal.predicate import parse_iso, validity_unknown


class IngestionError(ValueError):
    pass


def _ts(v: Any) -> int | None:
    return None if v is None else parse_iso(v)


class Ledger:
    def __init__(self, workspace_id: str):
        self.workspace_id = workspace_id
        self.nodes: dict[str, Node] = {}
        self.sources: dict[str, SourceRecord] = {}
        self.versions: dict[str, list[EdgeVersion]] = {}
        self.log: list[dict[str, Any]] = []  # ingestion decisions (for audit / UI)
        self.contradictions: list[tuple[str, str]] = []

    # ------------------------------------------------------------------ nodes & sources
    def add_node(self, node: Node) -> None:
        if node.workspace_id != self.workspace_id:
            raise IngestionError("node workspace mismatch")
        self.nodes[node.id] = node

    def add_source(self, rec: SourceRecord) -> None:
        old = self.sources.get(rec.source_id)
        if old is not None and old != rec:
            raise IngestionError(f"source {rec.source_id} re-ingested with different content")
        self.sources[rec.source_id] = rec

    def _type(self, node_id: str) -> str:
        if node_id not in self.nodes:
            raise IngestionError(f"unknown node {node_id}")
        return self.nodes[node_id].label

    def current(self, fact_id: str) -> EdgeVersion | None:
        for v in self.versions.get(fact_id, []):
            if v.tx_to is None:
                return v
        return None

    def _check_sources(self, ids: Iterable[str]) -> list[str]:
        out = sorted(set(ids))
        for s in out:
            if s not in self.sources:
                raise IngestionError(f"unknown source record {s}")
        return out

    def _supersede(self, cur: EdgeVersion, at: int, **changes: Any) -> EdgeVersion:
        if at < cur.tx_from:
            raise IngestionError("ingestion time precedes current version")
        cur.tx_to = at
        new = dataclasses.replace(cur, version=cur.version + 1, tx_from=at, tx_to=None, supersedes=cur.version,
                                  **changes)
        new.validity_unknown = validity_unknown(new.valid_from, new.valid_to, new.valid_open_ended)
        self.versions[cur.edge_id].append(new)
        return new

    # ------------------------------------------------------------------ facts
    def assert_edge(self, *, fact_id: str, type: str, src: str, dst: str, at: int | str, source_ids: list[str],
                    valid_from: Any = None, valid_to: Any = None, valid_open_ended: bool = False,
                    stale: bool = False, cost_remove: int | None = None, note: str = "") -> str:
        if type not in ALL_FACT_EDGE_TYPES:
            raise IngestionError(f"edge type {type} not allowed")
        at_ms = parse_iso(at)
        vf, vt = _ts(valid_from), _ts(valid_to)
        if vf is not None and vt is not None and vt <= vf:
            raise IngestionError("valid_to must be after valid_from")
        srcs = self._check_sources(source_ids)
        cur = self.current(fact_id)
        fields = dict(type=type, src=src, dst=dst, src_type=self._type(src), dst_type=self._type(dst),
                      valid_from=vf, valid_to=vt, valid_open_ended=bool(valid_open_ended) and vt is None)
        if cur is None:
            if fact_id in self.versions:
                raise IngestionError(f"fact {fact_id} has no current version")
            v = EdgeVersion(edge_id=fact_id, version=1, workspace_id=self.workspace_id, tx_from=at_ms,
                            source_ids=srcs, stale=stale, cost_remove=cost_remove, note=note, **fields)  # type: ignore[arg-type]
            v.validity_unknown = validity_unknown(v.valid_from, v.valid_to, v.valid_open_ended)
            self.versions[fact_id] = [v]
            self._log("assert", fact_id, at_ms, "created")
            return "created"
        same = all(getattr(cur, k) == val for k, val in fields.items())
        if same and set(srcs) <= set(cur.source_ids) and cur.stale == stale:
            self._log("assert", fact_id, at_ms, "duplicate (no-op)")
            return "noop"
        merged = sorted(set(cur.source_ids) | set(srcs)) if same else srcs
        self._supersede(cur, at_ms, source_ids=merged, stale=stale,
                        cost_remove=cost_remove if cost_remove is not None else cur.cost_remove, **fields)
        self._log("assert", fact_id, at_ms, "corroborated" if same else "superseded (content changed)")
        return "superseded"

    def remove_edge(self, *, fact_id: str, removed_at: Any, at: int | str, source_ids: list[str]) -> str:
        """A surface-removing claim (revocation/rotation). R2: untrusted claims only dispute the edge."""
        at_ms, rem = parse_iso(at), parse_iso(removed_at)
        srcs = self._check_sources(source_ids)
        cur = self.current(fact_id)
        if cur is None:
            raise IngestionError(f"removal for unknown fact {fact_id}")
        if trusted_removal(srcs, self.sources):
            if cur.valid_to is not None and cur.valid_to <= rem and set(srcs) <= set(cur.valid_to_source_ids):
                return "noop"
            self._supersede(cur, at_ms, valid_to=rem, valid_open_ended=False, valid_to_source_ids=srcs, prior_valid_to=cur.valid_to,
                            prior_valid_open_ended=cur.valid_open_ended)
            self._log("remove", fact_id, at_ms, "closed validity (trusted removal)")
            return "closed"
        if set(srcs) <= set(cur.dispute_source_ids):
            return "noop"
        self._supersede(cur, at_ms, dispute_source_ids=sorted(set(cur.dispute_source_ids) | set(srcs)))
        self._log("remove", fact_id, at_ms, "disputed (R2: untrusted removal does not remove the edge)")
        return "disputed"

    def correct_edge(self, *, fact_id: str, at: int | str, source_ids: list[str], **changes: Any) -> str:
        """Backfill/correction of validity (e.g. ownership learned late). tx_from = ingestion time."""
        at_ms = parse_iso(at)
        srcs = self._check_sources(source_ids)
        cur = self.current(fact_id)
        if cur is None:
            raise IngestionError(f"correction for unknown fact {fact_id}")
        upd: dict[str, Any] = {}
        for k in ("valid_from", "valid_to"):
            if k in changes:
                upd[k] = _ts(changes[k])
        if "valid_open_ended" in changes:
            upd["valid_open_ended"] = bool(changes["valid_open_ended"])
        if "valid_to" in upd and upd["valid_to"] is not None:
            upd["valid_open_ended"] = False
            upd["valid_to_source_ids"] = srcs
            upd["prior_valid_to"], upd["prior_valid_open_ended"] = cur.valid_to, cur.valid_open_ended
        if all(getattr(cur, k) == v for k, v in upd.items()) and set(srcs) <= set(cur.source_ids):
            return "noop"
        self._supersede(cur, at_ms, source_ids=sorted(set(cur.source_ids) | set(srcs)), **upd)
        self._log("correct", fact_id, at_ms, "superseded (correction/backfill)")
        return "superseded"

    def add_latent(self, *, template_id: str, type: str, src: str, dst: str, at: int | str, verify_cost: int,
                   source_ids: list[str] | None = None, created_by: str = "template_engine", note: str = "") -> str:
        fact_id = f"lat:{template_id}:{src}->{dst}"
        if self.current(fact_id) is not None:
            return "noop"
        at_ms = parse_iso(at)
        v = EdgeVersion(edge_id=fact_id, version=1, type=type, src=src, dst=dst, src_type=self._type(src),
                        dst_type=self._type(dst), workspace_id=self.workspace_id, tx_from=at_ms, kind="latent",
                        template_id=template_id, verify_cost=verify_cost, valid_open_ended=True,
                        source_ids=self._check_sources(source_ids or []), created_by=created_by, note=note)
        # Latent: existence is the assumption (class LATENT); if it exists it is assumed valid at every T
        # while visible, so paths through it classify as CONDITIONAL(k), not TEMPORALLY_UNCERTAIN.
        v.validity_unknown = False
        self.versions[fact_id] = [v]
        self._log("latent", fact_id, at_ms, f"instantiated template {template_id}")
        return "created"

    # ------------------------------------------------------------------ derived rules
    def derive(self) -> None:
        """Rule `policy_expansion`: (i)-[HAS_POLICY]->(p)-[APPLIES_TO]->(s) => (i)-[CAN_ACCESS]->(s).

        Each derived version is the bitemporal intersection of one version of each parent. Fully
        recomputed (deterministic), so re-running is idempotent.
        """
        for fid in [f for f in self.versions if f.startswith("drv:")]:
            del self.versions[fid]
        hp = [v for vs in self.versions.values() for v in vs if v.type == "HAS_POLICY"]
        ap = [v for vs in self.versions.values() for v in vs if v.type == "APPLIES_TO"
              and self.nodes[v.src].label == "Policy"]
        out: dict[str, list[EdgeVersion]] = {}
        for a in hp:
            for b in ap:
                if a.dst != b.src:
                    continue
                tx_from = max(a.tx_from, b.tx_from)
                tx_to = min((x for x in (a.tx_to, b.tx_to) if x is not None), default=None)
                if tx_to is not None and tx_to <= tx_from:
                    continue
                vf = None if a.valid_from is None or b.valid_from is None else max(a.valid_from, b.valid_from)
                ends = [x.valid_to for x in (a, b) if x.valid_to is not None]
                vt = min(ends) if ends else None
                open_ = vt is None and a.valid_open_ended and b.valid_open_ended
                fid = f"drv:policy_expansion:{a.src}->{b.dst}"
                lst = out.setdefault(fid, [])
                v = EdgeVersion(edge_id=fid, version=0, type="CAN_ACCESS", src=a.src, dst=b.dst,
                                src_type=self.nodes[a.src].label, dst_type=self.nodes[b.dst].label,
                                workspace_id=self.workspace_id, tx_from=tx_from, tx_to=tx_to, valid_from=vf,
                                valid_to=vt, valid_open_ended=open_, kind="derived", rule_id="policy_expansion",
                                parent_ids=[a.edge_id, b.edge_id], cost_remove=a.cost_remove,
                                source_ids=sorted(set(a.source_ids) | set(b.source_ids)),
                                created_by="rule:policy_expansion")
                v.validity_unknown = validity_unknown(vf, vt, open_)
                lst.append(v)
        for fid, lst in out.items():
            lst.sort(key=lambda v: v.tx_from)
            for i, v in enumerate(lst, 1):
                v.version = i
                v.supersedes = i - 1 if i > 1 else None
            self.versions[fid] = lst

    # ------------------------------------------------------------------ views
    def all_versions(self) -> list[EdgeVersion]:
        return [v for vs in self.versions.values() for v in vs]

    def _log(self, op: str, fact_id: str, at: int, decision: str) -> None:
        self.log.append({"op": op, "fact_id": fact_id, "at": at, "decision": decision})
