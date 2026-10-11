"""Workspace-scoped graph repository: the only module that writes to FalkorDB.

Defense in depth: one graph per workspace AND a `workspace_id` property checked in every query.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterable
from typing import Any

from app.graph import queries as Q
from app.graph.client import GraphClient, graph_key
from app.graph.schema import migrate
from app.ingestion.ledger import Ledger
from app.ingestion.scenario import ScenarioMeta
from app.model import ALL_FACT_EDGE_TYPES, NODE_LABELS, EdgeVersion, Flow, SourceRecord
from app.planner.engine import World

EDGE_FIELDS = (
    "valid_from", "valid_to", "valid_open_ended", "validity_unknown", "tx_from", "tx_to", "kind", "source_ids",
    "dispute_source_ids", "valid_to_source_ids", "prior_valid_to", "prior_valid_open_ended", "rule_id",
    "parent_ids", "template_id", "verify_cost", "stale", "cost_remove", "created_by", "note", "supersedes",
)


def now_ms() -> int:
    return int(time.time() * 1000)


def _primitive(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool)) or (
        isinstance(v, list) and all(isinstance(x, (str, int, float, bool)) for x in v))


def _label_of(labels: list[str]) -> str:
    return next((x for x in labels if x != "Entity"), "Entity")


class Repository:
    def __init__(self, client: GraphClient, workspace_id: str):
        graph_key(workspace_id)  # validates
        self.c = client
        self.ws = workspace_id

    # ------------------------------------------------------------------ lifecycle
    def init_schema(self) -> list[int]:
        self.c.rw(self.ws, Q.UPSERT_WORKSPACE, {"ws": self.ws, "now": now_ms()})
        return migrate(self.c, self.ws)

    def reset(self) -> None:
        self.c.drop_workspace(self.ws)
        self.init_schema()

    # ------------------------------------------------------------------ ingestion (idempotent upserts)
    def persist_ledger(self, led: Ledger, meta: ScenarioMeta) -> dict[str, int]:
        if led.workspace_id != self.ws:
            raise ValueError("ledger belongs to another workspace")
        by_label: dict[str, list[dict[str, Any]]] = {}
        for n in led.nodes.values():
            if n.label not in NODE_LABELS:
                raise ValueError(f"label {n.label} not allowlisted")
            props = {k: v for k, v in n.props.items() if _primitive(v)}
            props.update({"workspace_id": self.ws, "name": n.name, "synthetic": True})
            by_label.setdefault(n.label, []).append({"id": n.id, "props": props})
        for label, rows in by_label.items():
            self.c.rw(self.ws, Q.UPSERT_NODE[label], {"rows": rows})
        srows = []
        for s in led.sources.values():
            p = s.to_dict()
            p["workspace_id"] = self.ws
            srows.append({"source_id": s.source_id, "props": p})
        self.c.rw(self.ws, Q.UPSERT_SOURCE, {"rows": srows})
        drows = [{"a": s.source_id, "b": d} for s in led.sources.values() for d in s.derived_from]
        if drows:
            self.c.rw(self.ws, Q.LINK_SOURCE_DERIVED, {"rows": drows})
        if meta.contradictions:
            self.c.rw(self.ws, Q.LINK_CONTRADICTION, {"rows": [{"a": a, "b": b} for a, b in meta.contradictions]})
        n_edges = self.write_versions(led.all_versions())
        inc = meta.incident
        self.c.rw(self.ws, Q.UPSERT_NODE["Incident"], {"rows": [{"id": inc["incident_id"], "props": {
            "workspace_id": self.ws, "name": inc["title"], "severity": inc["severity"], "synthetic": True,
            "text": inc.get("summary", ""), "current": True}}]})
        self.c.rw(self.ws, Q.UPSERT_INCIDENT_EVIDENCE,
                  {"rows": [{"sid": s, "iid": inc["incident_id"]} for s in meta.incident_evidence]})
        self.c.rw(self.ws, Q.UPSERT_META, {"ws": self.ws, "sid": meta.scenario_id, "payload": json.dumps({
            "scenario_id": meta.scenario_id, "title": meta.title, "description": meta.description,
            "incident": inc, "now": meta.now, "flows": [f.to_dict() | {"description": f.description} for f in meta.flows],
            "nominations": meta.nominations, "ingestion_log": led.log[-400:],
        })})
        return {"nodes": len(led.nodes), "sources": len(led.sources), "edge_versions": n_edges}

    def write_versions(self, versions: Iterable[EdgeVersion]) -> int:
        by_type: dict[str, list[dict[str, Any]]] = {}
        n = 0
        for v in versions:
            if v.type not in ALL_FACT_EDGE_TYPES or v.workspace_id != self.ws:
                raise ValueError("edge type or workspace not allowed")
            props = {k: getattr(v, k) for k in EDGE_FIELDS}
            props["workspace_id"] = self.ws
            props["schema_version"] = 1
            by_type.setdefault(v.type, []).append(
                {"src": v.src, "dst": v.dst, "edge_id": v.edge_id, "version": v.version, "props": props})
            n += 1
        for t, rows in by_type.items():
            for i in range(0, len(rows), 500):
                self.c.rw(self.ws, Q.UPSERT_EDGE_VERSION[t], {"rows": rows[i:i + 500]})
        return n

    # ------------------------------------------------------------------ world loading
    def meta(self) -> dict[str, Any]:
        rows = self.c.ro(self.ws, Q.GET_META, {"ws": self.ws})
        if not rows:
            raise LookupError("workspace has no scenario loaded")
        out: dict[str, Any] = json.loads(rows[0][0])
        return out

    def _version_from_row(self, row: list[Any]) -> EdgeVersion:
        t, a, b, la, lb, p = row[:6]
        return EdgeVersion(edge_id=p["edge_id"], version=int(p["version"]), type=t, src=a, dst=b,
                           src_type=_label_of(la), dst_type=_label_of(lb), workspace_id=self.ws,
                           **{k: p.get(k) for k in EDGE_FIELDS if k in p and k != "workspace_id"}
                           | {k: p.get(k) or [] for k in ("source_ids", "dispute_source_ids", "valid_to_source_ids",
                                                         "parent_ids")}
                           | {"valid_open_ended": bool(p.get("valid_open_ended")),
                              "validity_unknown": bool(p.get("validity_unknown")),
                              "prior_valid_open_ended": bool(p.get("prior_valid_open_ended")),
                              "stale": bool(p.get("stale")), "verify_cost": int(p.get("verify_cost") or 1),
                              "kind": p.get("kind") or "asserted", "created_by": p.get("created_by") or "",
                              "note": p.get("note") or ""})

    def all_versions(self) -> list[EdgeVersion]:
        rows = self.c.ro(self.ws, Q.ALL_EDGE_VERSIONS, {"ws": self.ws, "types": list(ALL_FACT_EDGE_TYPES)})
        return [self._version_from_row(r) for r in rows]

    def active_versions(self, T: int, tau: int) -> list[tuple[EdgeVersion, str]]:
        """Versions satisfying the shared bitemporal predicate, evaluated inside FalkorDB."""
        rows = self.c.ro(self.ws, Q.ACTIVE_EDGE_VERSIONS,
                         {"ws": self.ws, "types": list(ALL_FACT_EDGE_TYPES), "T": T, "tau": tau})
        return [(self._version_from_row(r), r[6]) for r in rows]

    def visible_versions(self, tau: int) -> list[EdgeVersion]:
        rows = self.c.ro(self.ws, Q.VISIBLE_EDGE_VERSIONS, {"ws": self.ws, "types": list(ALL_FACT_EDGE_TYPES),
                                                            "tau": tau})
        return [self._version_from_row(r) for r in rows]

    def sources(self) -> dict[str, SourceRecord]:
        out = {}
        for (p,) in self.c.ro(self.ws, Q.ALL_SOURCES, {"ws": self.ws}):
            fields = {k: p.get(k) for k in SourceRecord.__dataclass_fields__}
            fields["derived_from"] = list(fields.get("derived_from") or [])
            fields["attacker_influenceable"] = bool(fields["attacker_influenceable"])
            fields["contains_instructions"] = bool(fields.get("contains_instructions"))
            out[p["source_id"]] = SourceRecord(**fields)
        return out

    def nodes(self) -> dict[str, dict[str, Any]]:
        out = {}
        for nid, labels, props in self.c.ro(self.ws, Q.ALL_NODES, {"ws": self.ws}):
            out[nid] = dict(props) | {"label": _label_of(labels)}
        return out

    def world(self, tau: int | None = None) -> World:
        """Load the facts as known at tau (visible versions) — FalkorDB applies the visibility predicate."""
        m = self.meta()
        inc = m["incident"]
        versions = self.visible_versions(tau) if tau is not None else self.all_versions()
        return World(workspace_id=self.ws, versions=versions, sources=self.sources(), node_props=self.nodes(),
                     flows=[Flow(f["flow_id"], f["u"], f["v"], int(f["weight"]), f["kind"], f.get("description", ""))
                            for f in m["flows"]],
                     attack_sources=list(inc["compromised_set"]), targets=list(inc["targets"]),
                     meta={"scenario_id": m["scenario_id"], "now": m["now"]})

    def fact_history(self, edge_id: str) -> list[dict[str, Any]]:
        rows = self.c.ro(self.ws, Q.FACT_HISTORY, {"ws": self.ws, "edge_id": edge_id})
        return [{"type": t, "src": a, "dst": b, **p} for t, a, b, p in rows]

    def find_paths_cypher(self, sources: list[str], targets: list[str], allowed: list[str], T: int, tau: int,
                          max_depth: int, limit: int) -> list[tuple[list[str], list[str]]]:
        depth = max(1, min(int(max_depth), Q.MAX_CYPHER_DEPTH))
        rows = self.c.ro(self.ws, Q.FIND_PATHS[depth], {"ws": self.ws, "sources": sources, "targets": targets,
                                                         "allowed": allowed, "T": T, "tau": tau,
                                                         "limit": max(1, min(int(limit), 2000))})
        return [(list(e), list(n)) for e, n in rows]

    # ------------------------------------------------------------------ generic read helpers
    def ro(self, query: str, params: dict[str, Any]) -> list[list[Any]]:
        """Read-only access for agents/tools. Only module-constant queries are passed in."""
        return self.c.ro(self.ws, query, {"ws": self.ws} | params)

    def rw(self, query: str, params: dict[str, Any]) -> list[list[Any]]:
        return self.c.rw(self.ws, query, {"ws": self.ws} | params)

    # ------------------------------------------------------------------ artifacts & audit
    def save_artifact(self, label: str, inv: str, art_id: str, payload: dict[str, Any], **props: Any) -> str:
        p = {"id": art_id, "workspace_id": self.ws, "investigation_id": inv, "created_at": now_ms(),
             "payload": json.dumps(payload, sort_keys=True)} | {k: v for k, v in props.items() if _primitive(v)}
        self.rw(Q.UPSERT_ARTIFACT[label], {"id": art_id, "inv": inv, "props": p})
        return art_id

    def get_artifact(self, label: str, art_id: str) -> dict[str, Any] | None:
        rows = self.ro(Q.GET_ARTIFACT[label], {"id": art_id})
        if not rows:
            return None
        p = dict(rows[0][0])
        p["payload"] = json.loads(p["payload"])
        return p

    def list_artifacts(self, label: str, inv: str) -> list[dict[str, Any]]:
        out = []
        for (p,) in self.ro(Q.LIST_ARTIFACTS[label], {"inv": inv}):
            p = dict(p)
            p["payload"] = json.loads(p["payload"])
            out.append(p)
        return out

    def audit(self, inv: str, actor: str, action: str, detail: dict[str, Any]) -> None:
        self.rw(Q.AUDIT, {"id": f"aud_{uuid.uuid4().hex[:12]}", "inv": inv, "at": now_ms(), "actor": actor,
                          "action": action, "detail": json.dumps(detail, sort_keys=True, default=str)[:20000]})

    def get_audit(self, inv: str) -> list[dict[str, Any]]:
        out = []
        for (p,) in self.ro(Q.GET_AUDIT, {"inv": inv}):
            p = dict(p)
            p["detail"] = json.loads(p["detail"])
            out.append(p)
        return out
