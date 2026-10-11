"""GHOSTTRACE independent certificate verifier.

Minimal trusted base: Python standard library only. This module must never import
anything from the application package (`app`). It re-derives every checkable claim
in a containment certificate from a canonical snapshot export (JSON Lines):

  line kind "header"      -> workspace, (T, tau), trust policy, sources, targets, flows
  line kind "edge"        -> one active (or validity-uncertain) edge of the snapshot
  line kind "action_cost" -> one candidate action and its seeded operational cost

The verifier trusts the export's per-edge epistemic class and temporal status as data
(they are bound by the snapshot hash); it independently re-implements reachability,
reopening distance, the cut-set (kappa) rules, flow preservation, cost arithmetic and,
for small `proven_optimal` claims, the optimum by exhaustive enumeration.
"""

from __future__ import annotations

import hashlib
import itertools
import json
from collections import deque
from typing import Any

SCHEMA_VERSION = "1"
TRAVERSAL = {"HAS_CREDENTIAL", "AUTHENTICATES_AS", "CAN_ASSUME", "CAN_ACCESS", "CONNECTS_TO", "DEPLOYS_TO"}
GRANT_TYPES = {"CAN_ACCESS", "CAN_ASSUME"}
WORKLOAD_TYPES = {"Host", "Service", "BuildRunner", "Asset"}
CONFIRMED_CLASSES = {"OBSERVED", "DERIVED"}
ENUMERATION_LIMIT = 20
INF = float("inf")


class VerificationError(Exception):
    pass


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


EDGE_KEYS = ("edge_id", "version", "type", "src", "dst", "src_type", "dst_type", "cls", "temporal")


def snapshot_hash(header: dict[str, Any], edges: list[dict[str, Any]], costs: list[dict[str, Any]]) -> str:
    payload = {
        "workspace_id": header["workspace_id"],
        "T": header["T"],
        "tau": header["tau"],
        "trust_policy": header["trust_policy"],
        "sources": sorted(header["sources"]),
        "targets": sorted(header["targets"]),
        "flows": sorted(header["flows"], key=lambda f: f["flow_id"]),
        "edges": sorted(({k: e[k] for k in EDGE_KEYS} for e in edges), key=lambda e: e["edge_id"]),
        "action_costs": sorted(costs, key=lambda c: c["action_id"]),
    }
    return "sha256:" + hashlib.sha256(canonical(payload).encode()).hexdigest()


def load_export(path: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    header: dict[str, Any] | None = None
    edges: list[dict[str, Any]] = []
    costs: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            rec = json.loads(line)
            kind = rec.get("kind")
            if kind == "header":
                if header is not None:
                    raise VerificationError(f"line {n}: duplicate header")
                header = rec
            elif kind == "edge":
                edges.append(rec)
            elif kind == "action_cost":
                costs.append(rec)
            else:
                raise VerificationError(f"line {n}: unknown record kind {kind!r}")
    if header is None:
        raise VerificationError("export has no header")
    ids = [e["edge_id"] for e in edges]
    if len(ids) != len(set(ids)):
        raise VerificationError("export has duplicate edge ids")
    return header, edges, costs


def kappa(action_type: str, target_id: str, edges: list[dict[str, Any]]) -> set[str]:
    """Cut-set rules, re-implemented independently of the application."""
    node_types = {e["src"]: e["src_type"] for e in edges} | {e["dst"]: e["dst_type"] for e in edges}
    if action_type == "disable_identity":
        if node_types.get(target_id) != "Identity":
            raise VerificationError(f"disable_identity target {target_id} is not an Identity")
        return {
            e["edge_id"]
            for e in edges
            if e["src"] == target_id or (e["dst"] == target_id and e["type"] == "AUTHENTICATES_AS")
        }
    if action_type == "revoke_credential":
        if node_types.get(target_id) != "Credential":
            raise VerificationError(f"revoke_credential target {target_id} is not a Credential")
        return {e["edge_id"] for e in edges if target_id in (e["src"], e["dst"])}
    if action_type in ("isolate_workload", "pause_deployment"):
        want = WORKLOAD_TYPES if action_type == "isolate_workload" else {"Deployment"}
        if node_types.get(target_id) not in want:
            raise VerificationError(f"{action_type} target {target_id} has wrong type")
        return {e["edge_id"] for e in edges if target_id in (e["src"], e["dst"])}
    if action_type in ("remove_access_grant", "block_communication"):
        match = [e for e in edges if e["edge_id"] == target_id]
        if not match:
            raise VerificationError(f"{action_type} target edge {target_id} not in snapshot")
        e = match[0]
        if action_type == "remove_access_grant" and (e["type"] not in GRANT_TYPES or e["cls"] == "LATENT"):
            raise VerificationError(f"edge {target_id} is not a removable observed grant")
        if action_type == "block_communication" and e["type"] != "CONNECTS_TO":
            raise VerificationError(f"edge {target_id} is not a communication edge")
        return {target_id}
    raise VerificationError(f"unknown action type {action_type!r}")


def _weight(e: dict[str, Any]) -> int:
    return 0 if e["cls"] in CONFIRMED_CLASSES and e["temporal"] == "ACTIVE" else 1


def reopening_distance(edges: list[dict[str, Any]], removed: set[str], sources: list[str],
                       targets: list[str]) -> float:
    """0-1 BFS: minimum number of non-confirmed edges on any surviving source->target path."""
    adj: dict[str, list[tuple[str, int]]] = {}
    for e in edges:
        if e["edge_id"] in removed or e["type"] not in TRAVERSAL:
            continue
        adj.setdefault(e["src"], []).append((e["dst"], _weight(e)))
    dist: dict[str, float] = {s: 0 for s in sources}
    dq: deque[str] = deque(sources)
    while dq:
        u = dq.popleft()
        for v, w in adj.get(u, []):
            nd = dist[u] + w
            if nd < dist.get(v, INF):
                dist[v] = nd
                if w == 0:
                    dq.appendleft(v)
                else:
                    dq.append(v)
    return min((dist.get(t, INF) for t in targets), default=INF)


def confirmed_reachable(edges: list[dict[str, Any]], removed: set[str], u: str, v: str) -> bool:
    adj: dict[str, list[str]] = {}
    for e in edges:
        if e["edge_id"] not in removed and e["type"] in TRAVERSAL and _weight(e) == 0:
            adj.setdefault(e["src"], []).append(e["dst"])
    seen, stack = {u}, [u]
    while stack:
        x = stack.pop()
        if x == v:
            return True
        for y in adj.get(x, []):
            if y not in seen:
                seen.add(y)
                stack.append(y)
    return False


def _check_path(path: list[str], by_id: dict[str, dict[str, Any]], removed: set[str], sources: set[str],
                targets: set[str]) -> int:
    if not path:
        raise VerificationError("empty path")
    cur = None
    latent = 0
    for i, eid in enumerate(path):
        e = by_id.get(eid)
        if e is None or eid in removed:
            raise VerificationError(f"path edge {eid} missing or removed")
        if i == 0 and e["src"] not in sources:
            raise VerificationError("path does not start at a source")
        if cur is not None and e["src"] != cur:
            raise VerificationError("path is not contiguous")
        cur = e["dst"]
        latent += _weight(e)
    if cur not in targets:
        raise VerificationError("path does not end at a target")
    return latent


def _flows_state(flows: list[dict[str, Any]], edges: list[dict[str, Any]], removed: set[str]) -> dict[str, bool]:
    return {f["flow_id"]: confirmed_reachable(edges, removed, f["u"], f["v"]) for f in flows}


def _penalty(flows: list[dict[str, Any]], state: dict[str, bool]) -> int:
    return sum(int(f["weight"]) for f in flows if f["kind"] == "soft" and not state[f["flow_id"]])


def check(cert: dict[str, Any], export_path: str) -> list[str]:
    """Return a list of failure reasons (empty list = certificate accepted)."""
    try:
        return _check(cert, export_path)
    except VerificationError as exc:
        return [str(exc)]
    except (KeyError, TypeError, ValueError) as exc:
        return [f"malformed certificate or export: {type(exc).__name__}: {exc}"]


def _check(cert: dict[str, Any], export_path: str) -> list[str]:
    errors: list[str] = []
    if cert.get("schema_version") != SCHEMA_VERSION:
        raise VerificationError(f"unknown schema_version {cert.get('schema_version')!r}")
    for key in ("certificate_id", "workspace_id", "world_time_T", "knowledge_time_tau", "snapshot_hash",
                "sources", "targets", "trust_policy", "actions", "status", "robustness", "flows", "cost",
                "optimality", "mode"):
        if key not in cert:
            raise VerificationError(f"missing field {key}")
    if cert["mode"] != "simulated":
        errors.append(f"mode must be 'simulated' in this build, got {cert['mode']!r}")

    header, edges, costs = load_export(export_path)
    if header.get("schema_version") != SCHEMA_VERSION:
        raise VerificationError("export schema_version mismatch")
    if snapshot_hash(header, edges, costs) != cert["snapshot_hash"]:
        errors.append("snapshot_hash does not match the recomputed hash of the export")
    for ck, hk in (("workspace_id", "workspace_id"), ("world_time_T", "T"), ("knowledge_time_tau", "tau"),
                   ("trust_policy", "trust_policy")):
        if cert[ck] != header[hk]:
            errors.append(f"{ck} in certificate ({cert[ck]!r}) differs from export ({header[hk]!r})")
    if sorted(cert["sources"]) != sorted(header["sources"]) or sorted(cert["targets"]) != sorted(header["targets"]):
        errors.append("sources/targets differ from export")

    by_id = {e["edge_id"]: e for e in edges}
    cost_table = {c["action_id"]: c for c in costs}
    removed: set[str] = set()
    op_cost = 0
    seen_actions: set[str] = set()
    for a in cert["actions"]:
        aid = a["id"]
        if aid in seen_actions:
            errors.append(f"duplicate action {aid}")
        seen_actions.add(aid)
        if aid != f"{a['type']}:{a['target_id']}":
            errors.append(f"action id {aid} inconsistent with type/target")
        entry = cost_table.get(aid)
        if entry is None:
            errors.append(f"action {aid} is not a candidate in the export")
        elif int(entry["cost"]) != int(a["cost"]):
            errors.append(f"action {aid} cost {a['cost']} != exported cost {entry['cost']}")
        k = kappa(a["type"], a["target_id"], edges)
        if set(a["removes"]) != k:
            errors.append(f"action {aid} removes {sorted(a['removes'])} but kappa gives {sorted(k)}")
        removed |= k
        op_cost += int(a["cost"])

    sources, targets = list(header["sources"]), list(header["targets"])
    d = reopening_distance(edges, removed, sources, targets)
    status = cert["status"]
    residual = cert.get("residual_confirmed_paths", [])
    if status == "contained":
        if d == 0:
            errors.append("certificate claims contained but a CONFIRMED path survives")
        if residual:
            errors.append("contained certificate lists residual confirmed paths")
    elif status == "not_contained":
        if d != 0:
            errors.append("certificate claims not_contained but no confirmed path survives")
        if not residual:
            errors.append("not_contained certificate must list residual paths")
    else:
        errors.append(f"unknown status {status!r}")
    for p in residual:
        try:
            if _check_path(p, by_id, removed, set(sources), set(targets)) != 0:
                errors.append("residual path is not fully confirmed")
        except VerificationError as exc:
            errors.append(f"residual path invalid: {exc}")

    rob = cert["robustness"]
    claimed_d = rob.get("min_reopening_latent_edges")
    if (INF if claimed_d is None else claimed_d) != d:
        errors.append(f"min_reopening_latent_edges {claimed_d} != recomputed {None if d == INF else int(d)}")
    if status == "contained" and not (rob["k_certified"] < d):
        errors.append(f"k_certified {rob['k_certified']} is not < reopening distance")
    for p in rob.get("witness_paths", []):
        try:
            if _check_path(p, by_id, removed, set(sources), set(targets)) != d:
                errors.append("witness path latent count differs from reopening distance")
        except VerificationError as exc:
            errors.append(f"witness path invalid: {exc}")

    hdr_flows = {f["flow_id"]: f for f in header["flows"]}
    state = _flows_state(header["flows"], edges, removed)
    if {f["flow_id"] for f in cert["flows"]} != set(hdr_flows):
        errors.append("certificate flow set differs from export")
    for f in cert["flows"]:
        h = hdr_flows.get(f["flow_id"])
        if h is None:
            continue
        if f["kind"] != h["kind"]:
            errors.append(f"flow {f['flow_id']} kind altered")
        if bool(f["preserved"]) != state[f["flow_id"]]:
            errors.append(f"flow {f['flow_id']} preserved={f['preserved']} but recomputed {state[f['flow_id']]}")
    if status == "contained":
        for fid, h in hdr_flows.items():
            if h["kind"] == "hard" and not state[fid]:
                errors.append(f"hard flow {fid} is broken by the plan")

    penalty = _penalty(header["flows"], state)
    c = cert["cost"]
    if int(c["operational"]) != op_cost:
        errors.append(f"operational cost {c['operational']} != sum of action costs {op_cost}")
    if int(c["soft_flow_penalty"]) != penalty:
        errors.append(f"soft_flow_penalty {c['soft_flow_penalty']} != recomputed {penalty}")
    if int(c["total"]) != op_cost + penalty:
        errors.append(f"total {c['total']} != {op_cost + penalty}")

    opt = cert["optimality"]
    if opt.get("status") not in ("proven_optimal", "bounded", "heuristic"):
        errors.append("unknown optimality status")
    if opt.get("status") == "proven_optimal" and status == "contained":
        if len(costs) <= ENUMERATION_LIMIT:
            best = brute_force_optimum(header, edges, costs, int(rob["k_target"]))
            if best is None:
                errors.append("proven_optimal claimed but enumeration finds no feasible plan")
            elif best != op_cost + penalty:
                errors.append(f"proven_optimal total {op_cost + penalty} != enumerated optimum {best}")
        else:
            errors.append(f"note: optimality not re-checked ({len(costs)} candidates > {ENUMERATION_LIMIT})")
    return [e for e in errors if not e.startswith("note:")]


def brute_force_optimum(header: dict[str, Any], edges: list[dict[str, Any]], costs: list[dict[str, Any]],
                        k_target: int) -> int | None:
    """Exhaustive minimum of J over all candidate subsets with d > k_target and hard flows preserved."""
    cands = [(c["action_id"], c["action_type"], c["target_id"], int(c["cost"])) for c in costs]
    kappas = [kappa(t, tid, edges) for _, t, tid, _ in cands]
    best: int | None = None
    for r in range(len(cands) + 1):
        for combo in itertools.combinations(range(len(cands)), r):
            op = sum(cands[i][3] for i in combo)
            if best is not None and op >= best:
                continue
            removed: set[str] = set()
            for i in combo:
                removed |= kappas[i]
            if not reopening_distance(edges, removed, header["sources"], header["targets"]) > k_target:
                continue
            state = _flows_state(header["flows"], edges, removed)
            if any(f["kind"] == "hard" and not state[f["flow_id"]] for f in header["flows"]):
                continue
            j = op + _penalty(header["flows"], state)
            if best is None or j < best:
                best = j
    return best
