"""Containment actions, cut-set rules kappa(a), and deterministic candidate generation (§3.5).

kappa is computed from the snapshot by fixed rules — never from model output. Notably, disabling an
identity cuts edges *from* that identity and credentials that authenticate *as* it, but not a credential
issued to a different principal (the Ghost Credential).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.model import SnapEdge
from app.reasoning.paths import backward_set, forward_set

GRANT_TYPES = frozenset({"CAN_ACCESS", "CAN_ASSUME"})
WORKLOAD_TYPES = frozenset({"Host", "Service", "BuildRunner", "Asset"})

ACTION_TYPES = (
    "disable_identity", "revoke_credential", "remove_access_grant", "isolate_workload",
    "pause_deployment", "block_communication",
)

# Default operational costs (integer "disruption units") when the scenario does not seed one.
DEFAULT_COSTS: dict[str, int] = {
    "disable_identity": 5, "revoke_credential": 3, "remove_access_grant": 4,
    "isolate_workload": 10, "pause_deployment": 6, "block_communication": 4,
}
REVERSIBILITY = {
    "disable_identity": "reversible (re-enable account)",
    "revoke_credential": "irreversible for the credential; re-issue required",
    "remove_access_grant": "reversible (re-grant)",
    "isolate_workload": "reversible (rejoin network); in-flight work lost",
    "pause_deployment": "reversible (resume)",
    "block_communication": "reversible (remove block rule)",
}
NODE_ACTION = {"Identity": "disable_identity", "Credential": "revoke_credential", "Deployment": "pause_deployment"}
COST_PROP = {
    "disable_identity": "cost_disable", "revoke_credential": "cost_revoke", "isolate_workload": "cost_isolate",
    "pause_deployment": "cost_pause",
}


class KappaError(ValueError):
    pass


@dataclass(frozen=True)
class Action:
    id: str
    type: str
    target_id: str
    target_type: str
    cost: int
    cost_basis: str
    reversibility: str
    removes: frozenset[str]
    supporting_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    mode: str = "proposed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "type": self.type, "target_id": self.target_id, "target_type": self.target_type,
            "cost": self.cost, "cost_basis": self.cost_basis, "reversibility": self.reversibility,
            "removes": sorted(self.removes), "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "mode": self.mode,
        }


def action_id(action_type: str, target_id: str) -> str:
    return f"{action_type}:{target_id}"


def node_types(edges: Iterable[SnapEdge]) -> dict[str, str]:
    out: dict[str, str] = {}
    for e in edges:
        out[e.src] = e.src_type
        out[e.dst] = e.dst_type
    return out


def kappa(action_type: str, target_id: str, edges: list[SnapEdge]) -> frozenset[str]:
    types = node_types(edges)
    if action_type == "disable_identity":
        if types.get(target_id) != "Identity":
            raise KappaError("disable_identity requires an Identity target")
        return frozenset(e.edge_id for e in edges
                         if e.src == target_id or (e.dst == target_id and e.type == "AUTHENTICATES_AS"))
    if action_type == "revoke_credential":
        if types.get(target_id) != "Credential":
            raise KappaError("revoke_credential requires a Credential target")
        return frozenset(e.edge_id for e in edges if target_id in (e.src, e.dst))
    if action_type == "isolate_workload":
        if types.get(target_id) not in WORKLOAD_TYPES:
            raise KappaError("isolate_workload requires a Host/Service/BuildRunner/Asset target")
        return frozenset(e.edge_id for e in edges if target_id in (e.src, e.dst))
    if action_type == "pause_deployment":
        if types.get(target_id) != "Deployment":
            raise KappaError("pause_deployment requires a Deployment target")
        return frozenset(e.edge_id for e in edges if target_id in (e.src, e.dst))
    if action_type in ("remove_access_grant", "block_communication"):
        match = [e for e in edges if e.edge_id == target_id]
        if not match:
            raise KappaError(f"edge {target_id} is not in the snapshot")
        e = match[0]
        if action_type == "remove_access_grant" and (e.type not in GRANT_TYPES or e.cls == "LATENT"):
            raise KappaError("remove_access_grant requires an observed/derived CAN_ACCESS or CAN_ASSUME edge")
        if action_type == "block_communication" and e.type != "CONNECTS_TO":
            raise KappaError("block_communication requires a CONNECTS_TO edge")
        return frozenset({target_id})
    raise KappaError(f"unknown action type {action_type}")


def make_action(action_type: str, target_id: str, edges: list[SnapEdge],
                node_props: Mapping[str, Mapping[str, Any]]) -> Action:
    removes = kappa(action_type, target_id, edges)
    types = node_types(edges)
    if action_type in ("remove_access_grant", "block_communication"):
        e = next(x for x in edges if x.edge_id == target_id)
        seeded = e.cost_remove
        target_type = e.type
        basis_src = f"edge {target_id}"
    else:
        seeded = node_props.get(target_id, {}).get(COST_PROP[action_type])
        target_type = types[target_id]
        basis_src = f"node {target_id}"
    cost = int(seeded) if seeded is not None else DEFAULT_COSTS[action_type]
    basis = (node_props.get(target_id, {}).get("cost_basis")
             if seeded is not None and action_type not in ("remove_access_grant", "block_communication") else None)
    basis = basis or (f"seeded on {basis_src}" if seeded is not None else f"default cost for {action_type}")
    support = sorted({s for e in edges if e.edge_id in removes for s in e.source_ids})
    return Action(action_id(action_type, target_id), action_type, target_id, target_type, cost, basis,
                  REVERSIBILITY[action_type], removes, tuple(support))


def generate_candidates(edges: list[SnapEdge], sources: Iterable[str], targets: Iterable[str],
                        node_props: Mapping[str, Mapping[str, Any]], max_candidates: int = 64) -> list[Action]:
    """Candidate actions on the relevant subgraph (nodes on some source->target path incl. latent edges)."""
    fwd = forward_set(edges, frozenset(), sources)
    bwd = backward_set(edges, frozenset(), targets)
    relevant = fwd & bwd
    types = node_types(edges)
    cands: dict[str, Action] = {}
    for n in sorted(relevant):
        t = types.get(n)
        at = NODE_ACTION.get(t or "") or ("isolate_workload" if t in WORKLOAD_TYPES else None)
        if at:
            a = make_action(at, n, edges, node_props)
            if a.removes:
                cands[a.id] = a
    for e in edges:
        if e.src in relevant and e.dst in relevant:
            if e.type in GRANT_TYPES and e.cls != "LATENT":
                a = make_action("remove_access_grant", e.edge_id, edges, node_props)
                cands[a.id] = a
            elif e.type == "CONNECTS_TO":
                a = make_action("block_communication", e.edge_id, edges, node_props)
                cands[a.id] = a
    ordered = sorted(cands.values(), key=lambda a: (a.cost, a.id))
    return ordered[:max_candidates]
