"""Typed, allowlisted graph tools for agents. No tool accepts Cypher; all graph access is read-only.

Each agent type has its own allowlist; each ToolBox enforces a tool-call budget, a wall-clock budget
and investigation cancellation, and records every call for the audit trail.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable
from typing import Any

from app.graph import queries as Q
from app.graph.repository import Repository
from app.memory.service import MemoryService
from app.model import Flag, SnapEdge, TrustPolicy
from app.planner import engine
from app.reasoning.paths import INF, classify_path, reopening_distance
from app.reasoning.snapshot import build_snapshot

ALLOWLIST: dict[str, frozenset[str]] = {
    "investigator": frozenset(
        {
            "get_incident_context",
            "find_attack_paths",
            "get_evidence",
            "get_related_prior_incidents",
            "get_memory",
            "get_service_owners",
            "get_node_details",
        }
    ),
    "evidence_verifier": frozenset(
        {"get_evidence", "find_attack_paths", "get_fact_history", "get_runbooks", "get_snapshot_edges", "get_contradictions"}
    ),
    "containment_planner": frozenset({"compute_pareto", "compute_certificate", "simulate_intervention", "evidence_sensitivity"}),
    "red_team": frozenset(
        {"get_certificate", "find_attack_paths", "latent_candidates", "check_latent_nomination", "get_snapshot_edges"}
    ),
    "memory_curator": frozenset({"get_evidence", "get_memory"}),
    "company_brain": frozenset({"get_service_owners", "get_node_details"}),
}


class ToolError(RuntimeError):
    pass


class BudgetExceeded(ToolError):
    pass


class Cancelled(ToolError):
    pass


class ToolBox:
    def __init__(
        self,
        repo: Repository,
        agent_type: str,
        investigation_id: str | None = None,
        max_calls: int = 60,
        timeout_s: float = 60.0,
        cancel_check: Callable[[], bool] | None = None,
    ):
        if agent_type not in ALLOWLIST:
            raise ToolError(f"unknown agent type {agent_type}")
        self.repo = repo
        self.agent_type = agent_type
        self.inv = investigation_id
        self.max_calls = max_calls
        self.deadline = time.monotonic() + timeout_s
        self.calls: list[dict[str, Any]] = []
        self.cancel_check = cancel_check
        self._world_cache: dict[int | None, engine.World] = {}

    def call(self, name: str, **kwargs: Any) -> Any:
        if name not in ALLOWLIST[self.agent_type]:
            raise ToolError(f"tool {name} is not allowlisted for {self.agent_type}")
        if len(self.calls) >= self.max_calls:
            raise BudgetExceeded(f"{self.agent_type} exceeded {self.max_calls} tool calls")
        if time.monotonic() > self.deadline:
            raise BudgetExceeded(f"{self.agent_type} exceeded its time budget")
        if self.cancel_check and self.cancel_check():
            raise Cancelled("investigation cancelled")
        t0 = time.monotonic()
        out = getattr(self, f"_t_{name}")(**kwargs)
        self.calls.append(
            {
                "tool": name,
                "args": {k: (v if isinstance(v, (int, str, bool)) else str(v)[:200]) for k, v in kwargs.items()},
                "ms": round((time.monotonic() - t0) * 1000, 2),
            }
        )
        return out

    # ------------------------------------------------------------------ helpers
    def world(self, tau: int | None = None) -> engine.World:
        if tau not in self._world_cache:
            self._world_cache[tau] = self.repo.world(tau)
        return self._world_cache[tau]

    # ------------------------------------------------------------------ tools
    def _t_get_incident_context(self, incident_id: str) -> dict[str, Any]:
        rows = self.repo.ro(Q.NODES_BY_IDS, {"ids": [incident_id]})
        evid = [dict(p) for (p,) in self.repo.ro(Q.INCIDENT_EVIDENCE, {"iid": incident_id})]
        meta = self.repo.meta()
        return {"incident": dict(rows[0][2]) if rows else None, "evidence": evid, "meta_incident": meta["incident"]}

    def _t_get_node_details(self, ids: list[str]) -> list[dict[str, Any]]:
        return [
            dict(p) | {"label": [x for x in lab if x != "Entity"][0]}
            for _, lab, p in self.repo.ro(Q.NODES_BY_IDS, {"ids": list(ids)[:200]})
        ]

    def _t_get_evidence(self, source_ids: list[str]) -> list[dict[str, Any]]:
        return [dict(p) for (p,) in self.repo.ro(Q.SOURCES_BY_IDS, {"ids": list(source_ids)[:500]})]

    def _t_get_contradictions(self, source_ids: list[str]) -> list[list[str]]:
        return [list(r) for r in self.repo.ro(Q.CONTRADICTIONS_FOR, {"ids": list(source_ids)})]

    def _t_get_fact_history(self, edge_id: str) -> list[dict[str, Any]]:
        return self.repo.fact_history(edge_id)

    def _t_get_related_prior_incidents(self, current: str) -> list[dict[str, Any]]:
        return [
            dict(zip(("id", "name", "text", "root_cause", "closed_at"), r, strict=True))
            for r in self.repo.ro(Q.PRIOR_INCIDENTS, {"current": current})
        ]

    def _t_get_memory(self, entity_ids: list[str], source_ids: list[str], now: int) -> list[dict[str, Any]]:
        return MemoryService(self.repo).relevant(entity_ids, source_ids, now)

    def _t_get_runbooks(self, ids: list[str], T: int, tau: int) -> list[dict[str, Any]]:
        keys = ("id", "name", "text", "valid_from", "applies_to", "edge_id", "source_ids")
        return [dict(zip(keys, r, strict=True)) for r in self.repo.ro(Q.RUNBOOKS_FOR, {"ids": ids, "T": T, "tau": tau})]

    def _t_get_service_owners(self, service_id: str, T: int, tau: int) -> list[dict[str, Any]]:
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
        return [dict(zip(keys, r, strict=True)) for r in self.repo.ro(Q.OWNERS, {"sid": service_id, "T": T, "tau": tau})]

    def _t_get_snapshot_edges(self, T: int, tau: int, policy: str = "conservative_defense") -> list[SnapEdge]:
        w = self.world(tau)
        snap = build_snapshot(w.versions, w.sources, T, tau, TrustPolicy(policy))
        return list(snap.values())

    def _t_find_attack_paths(
        self,
        T: int,
        tau: int,
        max_depth: int = 8,
        max_paths: int = 200,
        policy: str = "conservative_defense",
        removed: list[str] | None = None,
        extra_latent: list[SnapEdge] | None = None,
    ) -> dict[str, Any]:
        """Cypher enumeration (bounded) for counterexamples + exhaustive 0-1 BFS for the verdict."""
        w = self.world(tau)
        edges = engine.snapshot_edges(w, T, tau, TrustPolicy(policy)) + list(extra_latent or [])
        by_id = {e.edge_id: e for e in edges}
        rem = set(removed or [])
        allowed = [e.edge_id for e in edges if e.edge_id not in rem]
        rows = (
            self.repo.find_paths_cypher(w.attack_sources, w.targets, allowed, T, tau, max_depth, max_paths)
            if not extra_latent
            else []
        )
        paths = []
        seen: set[tuple[str, ...]] = set()
        for eids, nids in rows:
            if len(set(nids)) != len(nids) or tuple(eids) in seen:
                continue  # keep simple paths only
            seen.add(tuple(eids))
            pe = [by_id[x] for x in eids]
            info = classify_path(pe)
            paths.append(
                {
                    "edge_ids": list(info.edge_ids),
                    "node_ids": list(info.nodes),
                    "path_class": info.path_class,
                    "latent_count": info.latent_count,
                    "uncertain_count": info.uncertain_count,
                    "assumptions": list(info.assumptions),
                    "edge_classes": [
                        "CONFIRMED" if e.confirmed else e.cls if e.temporal == "ACTIVE" else "UNCERTAIN" for e in pe
                    ],
                }
            )
        d, wit = reopening_distance(edges, frozenset(rem), w.attack_sources, w.targets)
        return {
            "paths": paths,
            "reopening_distance": None if d == INF else int(d),
            "witness": [e.edge_id for e in wit],
            "edges": {e.edge_id: e for e in edges},
            "sources": w.attack_sources,
            "targets": w.targets,
            "cypher_depth": max_depth,
            "cypher_truncated": len(rows) >= max_paths,
        }

    def _t_compute_pareto(self, T: int, tau: int, K: int, policy: str) -> list[Any]:
        return engine.pareto(self.world(tau), T, tau, TrustPolicy(policy), K)

    def _t_compute_certificate(self, T: int, tau: int, policy: str, k: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        w = self.world(tau)
        edges, cands, res = engine.plan(w, T, tau, TrustPolicy(policy), k)
        return engine.certify_plan(w, T, tau, TrustPolicy(policy), edges, cands, res, k)

    def _t_simulate_intervention(
        self, T: int, tau: int, policy: str, action_ids: list[str]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        w = self.world(tau)
        edges, cands, res = engine.simulate(w, T, tau, TrustPolicy(policy), action_ids)
        return engine.certify_plan(w, T, tau, TrustPolicy(policy), edges, cands, res, 0, with_load_bearing=False)

    def _t_evidence_sensitivity(self, T: int, tau: int, K: int) -> list[dict[str, Any]]:
        return engine.evidence_sensitivity(self.world(tau), T, tau, K)

    def _t_get_certificate(self, cert_id: str) -> dict[str, Any] | None:
        return self.repo.get_artifact("Certificate", cert_id)

    def _t_latent_candidates(self, T: int, tau: int, limit: int = 20) -> list[dict[str, str]]:
        """Type-compatible (src, dst) pairs in the relevant region; the *nomination* is the model's job."""
        from app.reasoning.kappa import node_types
        from app.reasoning.latent import TEMPLATES
        from app.reasoning.paths import backward_set, forward_set

        w = self.world(tau)
        edges = engine.snapshot_edges(w, T, tau, TrustPolicy.CONSERVATIVE)
        types = node_types(edges) | {k: v["label"] for k, v in w.node_props.items()}
        fwd = forward_set(edges, frozenset(), w.attack_sources)
        bwd = backward_set(edges, frozenset(), w.targets)
        existing = {(e.src, e.dst) for e in edges}
        per_tpl: list[list[dict[str, str]]] = []
        for tpl in TEMPLATES.values():
            per_tpl.append(
                [
                    {"template_id": tpl.template_id, "src": a, "dst": b}
                    for a in sorted(fwd)
                    for b in sorted(bwd)
                    if a != b
                    and (a, b) not in existing
                    and types.get(a) in tpl.src_types
                    and types.get(b) in tpl.dst_types
                    and b not in w.attack_sources
                ]
            )
        out = [c for group in itertools.zip_longest(*per_tpl) for c in group if c]  # round-robin over templates
        return out[: max(1, min(limit, 200))]

    def _t_check_latent_nomination(self, template_id: str, src: str, dst: str, at: int) -> bool:
        from app.reasoning.latent import TEMPLATES

        if template_id not in TEMPLATES:
            return False
        rows = self.repo.ro(TEMPLATES[template_id].cypher, {"src": src, "dst": dst, "T": at, "tau": at})
        return bool(rows and rows[0][0])


def ff_edges(edges: list[SnapEdge]) -> list[str]:
    return [e.edge_id for e in edges if Flag.POSSIBLE_FALSE_FLAG.value in e.flags]
