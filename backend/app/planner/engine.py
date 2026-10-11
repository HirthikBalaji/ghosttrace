"""Planning engine: snapshot -> candidates -> CEGAR -> certificate + export; Pareto, R4, R5.

All functions are pure over a `World` (the facts loaded from FalkorDB for one workspace).
"""

from __future__ import annotations

import contextlib
import hashlib
import itertools
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.model import Flag, Flow, SnapEdge, SourceRecord, TrustPolicy
from app.planner.cegar import Budgets, Constraint, PlanResult, evaluate_plan, solve
from app.reasoning.kappa import Action, KappaError, generate_candidates, kappa, make_action
from app.reasoning.paths import INF, reachable, reopening_distance
from app.reasoning.snapshot import build_snapshot, traversal_edges
from app.temporal.predicate import to_iso

SCHEMA_VERSION = "1"
EDGE_HASH_KEYS = ("edge_id", "version", "type", "src", "dst", "src_type", "dst_type", "cls", "temporal")


@dataclass
class World:
    workspace_id: str
    versions: list[Any]  # EdgeVersion
    sources: dict[str, SourceRecord]
    node_props: dict[str, dict[str, Any]]
    flows: list[Flow]
    attack_sources: list[str]
    targets: list[str]
    meta: dict[str, Any] = field(default_factory=dict)


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def snapshot_edges(
    world: World, T: int, tau: int, policy: TrustPolicy, falsified: frozenset[str] = frozenset()
) -> list[SnapEdge]:
    return traversal_edges(build_snapshot(world.versions, world.sources, T, tau, policy, falsified))


def candidates_for(world: World, edges: list[SnapEdge], max_candidates: int = 64) -> list[Action]:
    return generate_candidates(edges, world.attack_sources, world.targets, world.node_props, max_candidates)


def plan(
    world: World, T: int, tau: int, policy: TrustPolicy, k: int, budgets: Budgets | None = None, warm: PlanResult | None = None
) -> tuple[list[SnapEdge], list[Action], PlanResult]:
    edges = snapshot_edges(world, T, tau, policy)
    cands = candidates_for(world, edges)
    ff = frozenset(e.edge_id for e in edges if Flag.POSSIBLE_FALSE_FLAG.value in e.flags)
    res = solve(
        edges,
        world.attack_sources,
        world.targets,
        world.flows,
        cands,
        k,
        budgets,
        warm_constraints=warm.constraints if warm else (),
        warm_nogoods=warm.nogoods if warm else (),
        false_flag_edges=ff,
    )
    return edges, cands, res


def pareto(world: World, T: int, tau: int, policy: TrustPolicy, K: int = 2, budgets: Budgets | None = None) -> list[PlanResult]:
    out: list[PlanResult] = []
    warm: PlanResult | None = None
    for k in range(K + 1):
        _, _, res = plan(world, T, tau, policy, k, budgets, warm)
        out.append(res)
        warm = res
    return out


def pareto_points(results: Sequence[PlanResult]) -> list[dict[str, Any]]:
    """(k, J*) points; a point is Pareto-optimal unless a higher-k plan costs no more."""
    pts = []
    for r in results:
        feasible = r.status == "contained"
        dominated = feasible and any(o.status == "contained" and o.k > r.k and o.total <= r.total for o in results)
        pts.append(
            {
                "k": r.k,
                "feasible": feasible,
                "total_cost": r.total if feasible else None,
                "actions": [a.id for a in r.actions],
                "reopening_distance": None if r.d == INF else int(r.d),
                "pareto_optimal": feasible and not dominated,
                "optimality": r.optimality,
                "infeasible_reason": r.infeasible_reason,
            }
        )
    return pts


def export_lines(
    world: World, T: int, tau: int, policy: TrustPolicy, edges: list[SnapEdge], cands: list[Action]
) -> list[dict[str, Any]]:
    header = {
        "kind": "header",
        "schema_version": SCHEMA_VERSION,
        "workspace_id": world.workspace_id,
        "T": T,
        "tau": tau,
        "trust_policy": policy.value,
        "sources": sorted(world.attack_sources),
        "targets": sorted(world.targets),
        "flows": sorted((f.to_dict() for f in world.flows), key=lambda f: f["flow_id"]),
    }
    lines = [header] + [e.export() for e in edges]
    lines += [
        {"kind": "action_cost", "action_id": a.id, "action_type": a.type, "target_id": a.target_id, "cost": a.cost}
        for a in sorted(cands, key=lambda a: a.id)
    ]
    return lines


def snapshot_hash(lines: list[dict[str, Any]]) -> str:
    header = lines[0]
    edges = [x for x in lines if x["kind"] == "edge"]
    costs = [{k: v for k, v in x.items()} for x in lines if x["kind"] == "action_cost"]
    payload = {
        "workspace_id": header["workspace_id"],
        "T": header["T"],
        "tau": header["tau"],
        "trust_policy": header["trust_policy"],
        "sources": sorted(header["sources"]),
        "targets": sorted(header["targets"]),
        "flows": sorted(header["flows"], key=lambda f: f["flow_id"]),
        "edges": sorted(({k: e[k] for k in EDGE_HASH_KEYS} for e in edges), key=lambda e: e["edge_id"]),
        "action_costs": sorted(costs, key=lambda c: c["action_id"]),
    }
    return "sha256:" + hashlib.sha256(canonical(payload).encode()).hexdigest()


def scrutiny_actions(edges: list[SnapEdge], world: World, res: PlanResult) -> list[dict[str, Any]]:
    """R3: an action is FF-justified if, ignoring possible_false_flag edges, the plan without it still holds."""
    ff = {e.edge_id for e in edges if Flag.POSSIBLE_FALSE_FLAG.value in e.flags}
    if not ff or res.status != "contained":
        return []
    out = []
    for a in res.actions:
        rest: set[str] = set()
        for b in res.actions:
            if b.id != a.id:
                rest |= b.removes
        d, _ = reopening_distance(edges, frozenset(rest | ff), world.attack_sources, world.targets)
        if d > res.k:
            _, wit = reopening_distance(edges, frozenset(rest), world.attack_sources, world.targets)
            out.append(
                {
                    "action_id": a.id,
                    "reason": "needed only to cut paths that rely on possible_false_flag "
                    "evidence (attacker-influenceable sources only)",
                    "false_flag_edges": sorted(ff & {e.edge_id for e in wit}),
                }
            )
    return out


def build_certificate(
    world: World,
    T: int,
    tau: int,
    policy: TrustPolicy,
    edges: list[SnapEdge],
    cands: list[Action],
    res: PlanResult,
    k_target: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lines = export_lines(world, T, tau, policy, edges, cands)
    by_id = {e.edge_id: e for e in edges}
    d = res.d
    fe_state = {f.flow_id: reachable(edges, res.removed, f.u, f.v) for f in world.flows}
    status = "contained" if d > 0 and all(fe_state[f.flow_id] for f in world.flows if f.kind == "hard") else "not_contained"
    residual: list[list[str]] = []
    if d == 0:
        residual = [[e.edge_id for e in res.witness]]
    non_confirmed = sum(1 for e in edges if not e.confirmed)
    k_cert = (int(d) - 1) if d not in (INF,) else non_confirmed
    k_cert = max(k_cert, 0) if status == "contained" else 0
    witness = [[e.edge_id for e in res.witness]] if (res.witness and d != INF and d > 0) else []
    priority = (
        sorted(
            (
                {
                    "edge_id": e.edge_id,
                    "template": e.template_id or ",".join(e.flags) or "uncertain_validity",
                    "verify_cost": e.verify_cost,
                }
                for e in res.witness
                if not e.confirmed
            ),
            key=lambda x: (x["verify_cost"], x["edge_id"]),
        )
        if witness
        else []
    )
    disputed = sorted({e.edge_id for e in edges if Flag.DISPUTED.value in e.flags})
    scrutiny = scrutiny_actions(edges, world, res)
    pen = sum(f.weight for f in world.flows if f.kind == "soft" and not fe_state[f.flow_id])
    op = sum(a.cost for a in res.actions)
    T_iso, tau_iso = to_iso(T), to_iso(tau)
    assumptions = [
        "The modeled graph is the attack surface; unmodeled paths not instantiated by an allowlisted latent "
        "template are outside this certificate.",
        "Epistemic classes follow rules R1-R3 under the stated trust policy.",
        f"Edges valid at world time T={T_iso} as known at knowledge time tau={tau_iso}.",
    ]
    if witness:
        assumptions.append(
            f"Latent/uncertain edges {sorted(e for p in witness for e in p if not by_id[e].confirmed)} "
            "are assumed absent for the confirmed-containment claim."
        )
    if disputed:
        assumptions.append(f"Disputed removals {disputed} are treated as NOT removed (defensive asymmetry R2).")
    limitations = [
        "Synthetic data; all actions are simulations, none were executed.",
        "Cannot prove absence of paths through facts that are not in the graph.",
        "Costs are seeded integers with a documented basis, not measured business impact.",
    ]
    if res.optimality != "proven_optimal":
        limitations.append(f"Optimality status is {res.optimality}; no optimality claim beyond that.")
    rob_text = f"plan is {k_cert}-robust" + (
        " (no path survives even if every latent edge were true)"
        if d == INF
        else f"; cheapest reopening requires {int(d)} unverified edge(s): {[p['edge_id'] for p in priority]}"
    )
    statement = (
        f"Within snapshot {snapshot_hash(lines)[:19]}… at (T={T_iso}, tau={tau_iso}), under trust policy "
        f"{policy.value} and the listed assumptions, "
        + (
            f"no CONFIRMED path from {sorted(world.attack_sources)} to {sorted(world.targets)} survives; {rob_text}."
            if status == "contained"
            else "a CONFIRMED path or a broken hard flow remains: NOT CONTAINED. Residual paths are listed."
        )
    )
    cert: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "workspace_id": world.workspace_id,
        "world_time_T": T,
        "knowledge_time_tau": tau,
        "snapshot_hash": snapshot_hash(lines),
        "sources": sorted(world.attack_sources),
        "targets": sorted(world.targets),
        "trust_policy": policy.value,
        "status": status,
        "actions": [
            {
                "id": a.id,
                "type": a.type,
                "target_id": a.target_id,
                "removes": sorted(a.removes),
                "cost": a.cost,
                "cost_basis": a.cost_basis,
                "reversibility": a.reversibility,
                "supporting_evidence_ids": list(a.supporting_evidence_ids),
                "mode": "simulated",
            }
            for a in res.actions
        ],
        "residual_confirmed_paths": residual,
        "robustness": {
            "k_target": k_target,
            "k_certified": k_cert,
            "min_reopening_latent_edges": None if d == INF else int(d),
            "witness_paths": witness,
            "verification_priority": priority,
        },
        "flows": [
            {"flow_id": f.flow_id, "kind": f.kind, "u": f.u, "v": f.v, "weight": f.weight, "preserved": fe_state[f.flow_id]}
            for f in sorted(world.flows, key=lambda f: f.flow_id)
        ],
        "cost": {"operational": op, "soft_flow_penalty": pen, "total": op + pen},
        "optimality": {
            "status": res.optimality,
            "gap": res.gap,
            "search_space": res.search_space,
            "lower_bound": res.lower_bound,
            "candidate_count": len(cands),
        },
        "disputed_removals": disputed,
        "requires_human_scrutiny": scrutiny,
        "load_bearing_evidence": [],
        "assumptions": assumptions,
        "limitations": limitations,
        "statement": statement,
        "mode": "simulated",
    }
    cert["certificate_id"] = "cert_" + hashlib.sha256(canonical(cert).encode()).hexdigest()[:16]
    return cert, lines


def certify_plan(
    world: World,
    T: int,
    tau: int,
    policy: TrustPolicy,
    edges: list[SnapEdge],
    cands: list[Action],
    res: PlanResult,
    k_target: int,
    with_load_bearing: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cert, lines = build_certificate(world, T, tau, policy, edges, cands, res, k_target)
    if with_load_bearing and cert["status"] == "contained":
        lb = load_bearing(world, T, tau, policy, res, cert)
        cert["load_bearing_evidence"] = [x["sources"] for x in lb]
        cert["load_bearing_detail"] = lb
        cert.pop("certificate_id")
        cert["certificate_id"] = "cert_" + hashlib.sha256(canonical(cert).encode()).hexdigest()[:16]
    return cert, lines


def simulate(
    world: World, T: int, tau: int, policy: TrustPolicy, action_ids: Sequence[str]
) -> tuple[list[SnapEdge], list[Action], PlanResult]:
    edges = snapshot_edges(world, T, tau, policy)
    cands = candidates_for(world, edges)
    by_id = {a.id: a for a in cands}
    acts = []
    for aid in action_ids:
        if aid in by_id:
            acts.append(by_id[aid])
            continue
        at, _, target = aid.partition(":")
        acts.append(make_action(at, target, edges, world.node_props))  # raises KappaError if invalid
    extra = [a for a in acts if a.id not in by_id]
    return edges, cands + extra, evaluate_plan(edges, world.attack_sources, world.targets, world.flows, acts)


# ---------------------------------------------------------------- R5: load-bearing evidence


def _claims_hold(
    world: World, T: int, tau: int, policy: TrustPolicy, res: PlanResult, cert: dict[str, Any], falsified: frozenset[str]
) -> str | None:
    edges = snapshot_edges(world, T, tau, policy, falsified)
    removed: set[str] = set()
    for a in res.actions:
        with contextlib.suppress(KappaError):  # target vanished in the falsified world: removes nothing
            removed |= kappa(a.type, a.target_id, edges)
    d, wit = reopening_distance(edges, frozenset(removed), world.attack_sources, world.targets)
    if d == 0:
        return f"a CONFIRMED path survives: {[e.edge_id for e in wit]}"
    if d <= cert["robustness"]["k_certified"]:
        return f"reopening distance drops to {int(d)} <= k_certified"
    for f in world.flows:
        if f.kind == "hard" and not reachable(edges, frozenset(removed), f.u, f.v):
            return f"hard flow {f.flow_id} is no longer preserved"
    return None


def load_bearing(
    world: World,
    T: int,
    tau: int,
    policy: TrustPolicy,
    res: PlanResult,
    cert: dict[str, Any],
    max_size: int = 2,
    max_records: int = 40,
) -> list[dict[str, Any]]:
    """Minimal source-record sets (size <= max_size) whose falsification invalidates the certificate."""
    snap = build_snapshot(world.versions, world.sources, T, tau, policy)
    relevant: set[str] = set()
    for e in snap.values():
        relevant |= set(e.source_ids)
    for v in world.versions:
        relevant |= set(v.valid_to_source_ids)
    cands = sorted(s for s in relevant if s in world.sources)[:max_records]
    found: list[dict[str, Any]] = []
    for size in range(1, max_size + 1):
        for combo in itertools.combinations(cands, size):
            fs = frozenset(combo)
            if any(set(f["sources"]) <= fs for f in found):
                continue
            why = _claims_hold(world, T, tau, policy, res, cert, fs)
            if why:
                found.append({"sources": sorted(fs), "invalidates": why})
    return found


# ---------------------------------------------------------------- R4: evidence sensitivity


def evidence_sensitivity(world: World, T: int, tau: int, K: int = 2, budgets: Budgets | None = None) -> list[dict[str, Any]]:
    out = []
    cons = pareto(world, T, tau, TrustPolicy.CONSERVATIVE, K, budgets)
    filt = pareto(world, T, tau, TrustPolicy.TRUST_FILTERED, K, budgets)
    for c, f in zip(cons, filt, strict=True):
        ca, fa = {a.id for a in c.actions}, {a.id for a in f.actions}
        out.append(
            {
                "k": c.k,
                "conservative": {
                    "status": c.status,
                    "actions": sorted(ca),
                    "total": c.total if c.status == "contained" else None,
                },
                "trust_filtered": {
                    "status": f.status,
                    "actions": sorted(fa),
                    "total": f.total if f.status == "contained" else None,
                },
                "only_conservative": sorted(ca - fa),
                "only_trust_filtered": sorted(fa - ca),
                "differs": ca != fa or c.status != f.status,
            }
        )
    return out


def residual_constraint(path: list[str]) -> Constraint:
    return Constraint(tuple(path))
