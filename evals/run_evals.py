"""GHOSTTRACE evaluation harness. Generates evals/report.md and evals/results.json from real runs.

Every metric is computed on the ground-truth world W*, which the system never sees. Rates carry
Wilson 95% intervals. Exit code 1 if any certificate-soundness violation occurs (CI gate).

    cd backend && uv run python ../evals/run_evals.py [--n 100] [--falkordb] [--quick]
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import json
import math
import platform
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]

from verifier import check  # noqa: E402

from app.ingestion.scenario import load, world_from  # noqa: E402
from app.model import Flag, SnapEdge, TrustPolicy  # noqa: E402
from app.planner import engine  # noqa: E402
from app.planner.brute import brute_force  # noqa: E402
from app.planner.cegar import FlowEvaluator, evaluate_plan, solve  # noqa: E402
from app.reasoning.kappa import Action, KappaError, generate_candidates, make_action  # noqa: E402
from app.reasoning.paths import INF, reachable  # noqa: E402
from evals.generator.generator import GenParams, Instance, generate  # noqa: E402

P = TrustPolicy.CONSERVATIVE
METHODS = ["B0", "B1", "B2", "B3", "GT_k0", "GT_k1", "GT_k2"]
FAMILIES = {
    "small": GenParams(n_mid=6, n_paths=2, n_hard=1, n_soft=2),
    "default": GenParams(n_mid=10),
    "adversarial": GenParams(n_mid=10, ai_frac=0.2, weak_frac=0.1, decoy=True, churn=True),
}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def rate(k: int, n: int) -> dict[str, Any]:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": (k / n) if n else None, "ci95": [round(lo, 3), round(hi, 3)]}


# ------------------------------------------------------------------ ground-truth evaluation
def truth_edges(inst: Instance, types: dict[str, str], modeled_only: bool) -> list[SnapEdge]:
    out = []
    for t in inst.truth_edges:
        if modeled_only and t.get("unmodeled"):
            continue
        out.append(SnapEdge(t["id"], 1, t["type"], t["src"], t["dst"], types[t["src"]], types[t["dst"]], "OBSERVED", "ACTIVE"))
    return out


def kappa_truth(actions: list[Action], wstar: list[SnapEdge]) -> frozenset[str]:
    """Apply each action's rule to W*. Node actions cut W* edges incident by rule; edge actions cut that edge."""
    removed: set[str] = set()
    for a in actions:
        t = a.target_id
        for e in wstar:
            if (
                a.type == "disable_identity"
                and (e.src == t or (e.dst == t and e.type == "AUTHENTICATES_AS"))
                or a.type in ("revoke_credential", "isolate_workload", "pause_deployment")
                and t in (e.src, e.dst)
                or a.type in ("remove_access_grant", "block_communication")
                and e.edge_id == t
            ):
                removed.add(e.edge_id)
    return frozenset(removed)


def score(inst: Instance, w: engine.World, actions: list[Action], types: dict[str, str]) -> dict[str, Any]:
    ws_all = truth_edges(inst, types, modeled_only=False)
    ws_mod = truth_edges(inst, types, modeled_only=True)
    r_all, r_mod = kappa_truth(actions, ws_all), kappa_truth(actions, ws_mod)
    exp_all = any(reachable(ws_all, r_all, s, t) for s in w.attack_sources for t in w.targets)
    exp_mod = any(reachable(ws_mod, r_mod, s, t) for s in w.attack_sources for t in w.targets)
    fe = FlowEvaluator(ws_all, w.flows)
    st = fe.state(r_all)
    hard_broken = sum(1 for f in w.flows if f.kind == "hard" and not st[f.flow_id])
    j = sum(a.cost for a in actions) + fe.penalty(r_all)
    return {"exposed_all": exp_all, "exposed_modeled": exp_mod, "hard_broken": hard_broken, "J_true": j}


# ------------------------------------------------------------------ baselines
def naive_static_edges(w: engine.World) -> list[SnapEdge]:
    """Time-blind, trust-blind view: latest version of every asserted fact, removal claims believed."""
    latest: dict[str, Any] = {}
    for v in w.versions:
        if v.kind == "latent":
            continue
        if v.edge_id not in latest or v.version > latest[v.edge_id].version:
            latest[v.edge_id] = v
    out = []
    for v in latest.values():
        if v.dispute_source_ids:  # naive: an attacker-written "rotated/revoked" log is believed
            continue
        out.append(
            SnapEdge(
                v.edge_id,
                v.version,
                v.type,
                v.src,
                v.dst,
                v.src_type,
                v.dst_type,
                "OBSERVED",
                "ACTIVE",
                source_ids=v.source_ids,
                cost_remove=v.cost_remove,
            )
        )
    from app.model import TRAVERSAL_EDGE_TYPES

    return [e for e in out if e.type in TRAVERSAL_EDGE_TYPES]


def baseline_b0(w: engine.World, edges: list[SnapEdge]) -> list[Action]:
    try:
        return [make_action("disable_identity", "id:src-user", edges, w.node_props)]
    except KappaError:
        return []


def baseline_b1(w: engine.World) -> list[Action]:
    """Greedy by node degree centrality on the static (time-blind) graph; ignores flows."""
    static = naive_static_edges(w)
    cands = generate_candidates(static, w.attack_sources, w.targets, w.node_props)
    node_c = [a for a in cands if a.type in ("disable_identity", "revoke_credential", "isolate_workload")]
    deg = Counter([e.src for e in static] + [e.dst for e in static])
    chosen: list[Action] = []
    for a in sorted(node_c, key=lambda a: (-deg[a.target_id], a.id)):
        rem = frozenset().union(*(c.removes for c in chosen)) if chosen else frozenset()
        if not any(reachable(static, rem, s, t, confirmed_only=False) for s in w.attack_sources for t in w.targets):
            break
        chosen.append(a)
    return chosen


def baseline_b2(w: engine.World) -> list[Action]:
    """Static min-cost cut ignoring time, trust and must-keep flows."""
    static = naive_static_edges(w)
    cands = generate_candidates(static, w.attack_sources, w.targets, w.node_props)
    res = solve(static, w.attack_sources, w.targets, [], cands, 0)
    return res.actions


def baseline_b3(w: engine.World, edges: list[SnapEdge]) -> list[Action]:
    """Mock LLM-only: disable the alerted account and isolate whatever the alerts implicate. No graph checks."""
    acts = baseline_b0(w, edges)
    implicated = {e.src for e in edges if Flag.POSSIBLE_FALSE_FLAG.value in e.flags}
    for n in sorted(implicated):
        if w.node_props.get(n, {}).get("label") in ("Service", "Host"):
            with contextlib.suppress(KappaError):
                acts.append(make_action("isolate_workload", n, edges, w.node_props))
    return acts


def ff_driven(edges: list[SnapEdge], w: engine.World, actions: list[Action], k: int) -> list[str]:
    """Attacker-induced actions: they cut S->T paths only where those paths rely on possible_false_flag
    evidence (no edge they remove lies on any S->T path of the graph without FF edges)."""
    from app.reasoning.paths import backward_set, forward_set

    ff = frozenset(e.edge_id for e in edges if Flag.POSSIBLE_FALSE_FLAG.value in e.flags)
    if not ff:
        return []

    def on_path(removed: frozenset[str]) -> set[str]:
        fwd = forward_set(edges, removed, w.attack_sources)
        bwd = backward_set(edges, removed, w.targets)
        return {e.edge_id for e in edges if e.edge_id not in removed and e.src in fwd and e.dst in bwd}

    with_ff, without_ff = on_path(frozenset()), on_path(ff)
    return [a.id for a in actions if (a.removes & with_ff) and not (a.removes & without_ff)]


# ------------------------------------------------------------------ main loop
def run_family(name: str, params: GenParams, seeds: range, mutation_sample: int) -> dict[str, Any]:
    agg: dict[str, Counter[str]] = defaultdict(Counter)
    j_lists: dict[str, list[int]] = defaultdict(list)
    regret: dict[str, list[int]] = defaultdict(list)
    calib: dict[str, Counter[str]] = defaultdict(Counter)
    failures: list[dict[str, Any]] = []
    soundness = {"certificates": 0, "violations": 0}
    verifier_stats = Counter()
    temporal = Counter()
    citations = Counter()
    solver_ms: list[float] = []
    mutation = Counter()
    from verifier.tests.test_verifier import MUTATIONS, _m

    for seed in seeds:
        inst = generate(seed, params)
        led, meta = load(inst.scenario, "eval")
        w = world_from(led, meta)
        now = meta.now
        types = {n: p["label"] for n, p in w.node_props.items()}
        edges = engine.snapshot_edges(w, now, now, P)
        by_id = {e.edge_id: e for e in edges}
        confirmed_ids = {e.edge_id for e in edges if e.confirmed}
        # temporal / R2 correctness on churned facts
        for v in led.all_versions():
            if v.tx_to is None and v.valid_to_source_ids:  # trusted revocation before planning time
                temporal["checked"] += 1
                temporal["ok"] += int(v.edge_id not in by_id)
            if v.tx_to is None and v.dispute_source_ids:  # attacker-written removal claim (R2)
                temporal["checked"] += 1
                temporal["ok"] += int(v.edge_id in by_id and Flag.DISPUTED.value in by_id[v.edge_id].flags)
        plans: dict[str, list[Action]] = {
            "B0": baseline_b0(w, edges),
            "B1": baseline_b1(w),
            "B2": baseline_b2(w),
            "B3": baseline_b3(w, edges),
        }
        certs: dict[str, dict[str, Any]] = {}
        for k in (0, 1, 2):
            t0 = time.perf_counter()
            e2, cands, res = engine.plan(w, now, now, P, k)
            solver_ms.append((time.perf_counter() - t0) * 1000)
            m = f"GT_k{k}"
            if res.status != "contained":
                agg[m]["infeasible"] += 1
                plans[m] = []
                continue
            plans[m] = res.actions
            cert, lines = engine.build_certificate(w, now, now, P, e2, cands, res, k)
            certs[m] = cert
            with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as fh:
                fh.write("\n".join(json.dumps(x) for x in lines))
                path = fh.name
            errs = check(cert, path)
            verifier_stats["checked"] += 1
            verifier_stats["accepted"] += int(not errs)
            if errs:
                failures.append({"seed": seed, "method": m, "kind": "verifier_rejected", "errors": errs[:3]})
            if seed - seeds.start < mutation_sample and k == 0:
                for fn in MUTATIONS.values():
                    try:
                        mutated = _m(fn)(cert, lines)
                    except (StopIteration, IndexError, KeyError):
                        mutation["not_applicable"] += 1
                        continue
                    if mutated == cert:
                        mutation["equivalent_identical"] += 1
                        continue
                    mutation["applied"] += 1
                    mutation["killed"] += int(bool(check(mutated, path)))
            # Soundness on W*: confirmed-only paths after kappa must not exist
            wstar_conf = [x for x in truth_edges(inst, types, True) if x.edge_id in confirmed_ids]
            rem = kappa_truth(res.actions, wstar_conf)
            soundness["certificates"] += 1
            if any(reachable(wstar_conf, rem, s, t) for s in w.attack_sources for t in w.targets):
                soundness["violations"] += 1
                failures.append({"seed": seed, "method": m, "kind": "SOUNDNESS_VIOLATION"})
            # robustness calibration (synthetic prior)
            sc = score(inst, w, res.actions, types)
            bucket = "inf" if res.d == INF else str(int(res.d))
            calib[bucket]["n"] += 1
            calib[bucket]["reopened"] += int(sc["exposed_modeled"])
            sup = {s for a in res.actions for s in a.supporting_evidence_ids}
            citations["total"] += len(sup)
            citations["resolved"] += len([s for s in sup if s in w.sources])
        has_decoy = bool(inst.decoy_edge_ids) and any(x in by_id for x in inst.decoy_edge_ids)
        for m, acts in plans.items():
            if m.startswith("GT") and m not in certs:
                continue
            sc = score(inst, w, acts, types)
            agg[m]["n"] += 1
            agg[m]["exposed_all"] += int(sc["exposed_all"])
            agg[m]["exposed_modeled"] += int(sc["exposed_modeled"])
            agg[m]["hard_broken_any"] += int(sc["hard_broken"] > 0)
            j_lists[m].append(sc["J_true"])
            if has_decoy:
                k = int(m[-1]) if m.startswith("GT") else 0
                driven = ff_driven(edges, w, acts, k)
                flagged = {x["action_id"] for x in certs[m]["requires_human_scrutiny"]} if m in certs else set()
                agg[m]["decoy_instances"] += 1
                agg[m]["evidence_attack_success"] += int(bool(set(driven) - flagged))
        if name == "small":
            cands = engine.candidates_for(w, edges)
            if len(cands) <= 14:
                bf = brute_force(edges, w.attack_sources, w.targets, w.flows, cands, 0)
                if bf:
                    for m, acts in plans.items():
                        ev = evaluate_plan(edges, w.attack_sources, w.targets, w.flows, acts)
                        if ev.status == "contained":
                            regret[m].append(ev.total - bf[0])
                    if (
                        "GT_k0" in certs
                        and certs["GT_k0"]["optimality"]["status"] == "proven_optimal"
                        and certs["GT_k0"]["cost"]["total"] != bf[0]
                    ):
                        failures.append({"seed": seed, "method": "GT_k0", "kind": "solver_vs_bruteforce_mismatch"})
    out = {
        "family": name,
        "params": params.__dict__,
        "seeds": [seeds.start, seeds.stop - 1],
        "instances": len(seeds),
        "methods": {
            m: {
                "plans_evaluated": agg[m]["n"],
                "infeasible": agg[m]["infeasible"],
                "residual_exposure_modeled": rate(agg[m]["exposed_modeled"], agg[m]["n"]),
                "residual_exposure_incl_unmodeled": rate(agg[m]["exposed_all"], agg[m]["n"]),
                "hard_flow_broken": rate(agg[m]["hard_broken_any"], agg[m]["n"]),
                "mean_J_true": round(statistics.mean(j_lists[m]), 2) if j_lists[m] else None,
                "evidence_attack_success": rate(agg[m]["evidence_attack_success"], agg[m]["decoy_instances"]),
                "disruption_regret": (
                    {"n": len(regret[m]), "mean": round(statistics.mean(regret[m]), 3), "max": max(regret[m])}
                    if regret[m]
                    else None
                ),
            }
            for m in METHODS
        },
        "soundness": soundness,
        "verifier": dict(verifier_stats),
        "robustness_calibration": {b: rate(c["reopened"], c["n"]) for b, c in sorted(calib.items())},
        "temporal_r2_correctness": rate(temporal["ok"], temporal["checked"]),
        "citation_resolution": rate(citations["resolved"], citations["total"]),
        "mutation": dict(mutation),
        "solver_ms": {
            "median": round(statistics.median(solver_ms), 2),
            "p95": round(sorted(solver_ms)[int(0.95 * (len(solver_ms) - 1))], 2),
            "samples": len(solver_ms),
        },
        "failures": failures,
    }
    return out


def scaling(sizes: list[int], seeds_per: int, use_falkor: bool) -> list[dict[str, Any]]:
    rows = []
    client = None
    if use_falkor:
        from app.graph.client import GraphClient

        client = GraphClient(timeout_ms=30000)
        if not client.ping():
            client = None
    for n in sizes:
        solve_ms, warm_ms, cold_ms, q_ms, path_ms, edges_n = [], [], [], [], [], []
        for seed in range(seeds_per):
            inst = generate(10_000 + seed, GenParams(n_mid=n, n_paths=max(2, n // 10), branching=1.3, n_hard=3, n_soft=3))
            led, meta = load(inst.scenario, "scale")
            w = world_from(led, meta)
            now = meta.now
            t0 = time.perf_counter()
            _, _, r1 = engine.plan(w, now, now, P, 1)
            solve_ms.append((time.perf_counter() - t0) * 1000)
            # incremental: new evidence (one extra signed edge) then replan warm vs cold
            data = copy.deepcopy(inst.scenario)
            data["sources"].append(
                {
                    "source_id": "s:new",
                    "system": "gen",
                    "integrity": "signed",
                    "root_id": "root:new",
                    "trust_class": "high",
                    "observed_at": data["clock"]["now"],
                    "ingested_at": data["clock"]["now"],
                    "content": "new",
                }
            )
            data["events"].append(
                {
                    "op": "assert",
                    "at": data["clock"]["now"],
                    "fact_id": "g:new",
                    "type": "CAN_ACCESS",
                    "src": "id:src-user",
                    "dst": "asset:t0",
                    "valid_from": data["clock"]["now"],
                    "valid_open_ended": True,
                    "sources": ["s:new"],
                    "cost_remove": 3,
                }
            )
            led2, meta2 = load(data, "scale")
            w2 = world_from(led2, meta2)
            t0 = time.perf_counter()
            _, _, cold = engine.plan(w2, now, now, P, 1)
            cold_ms.append((time.perf_counter() - t0) * 1000)
            t0 = time.perf_counter()
            _, _, warm = engine.plan(w2, now, now, P, 1, warm=r1)
            warm_ms.append((time.perf_counter() - t0) * 1000)
            assert warm.status == cold.status and warm.total == cold.total
            edges_n.append(len([v for v in w.versions]))
            if client is not None:
                from app.graph.repository import Repository

                wsid = f"scale-{n}-{seed}"
                repo = Repository(client, wsid)
                repo.reset()
                led_db, meta_db = load(inst.scenario, wsid)
                repo.persist_ledger(led_db, meta_db)
                for _ in range(3):
                    t0 = time.perf_counter()
                    repo.active_versions(now, now)
                    q_ms.append((time.perf_counter() - t0) * 1000)
                    allowed = [e.edge_id for e in engine.snapshot_edges(w, now, now, P)]
                    t0 = time.perf_counter()
                    repo.find_paths_cypher(w.attack_sources, w.targets, allowed, now, now, 6, 500)
                    path_ms.append((time.perf_counter() - t0) * 1000)
                client.drop_workspace(wsid)

        def stat(xs: list[float]) -> dict[str, Any] | None:
            if not xs:
                return None
            s = sorted(xs)
            return {"median": round(statistics.median(s), 2), "p95": round(s[int(0.95 * (len(s) - 1))], 2), "samples": len(s)}

        rows.append(
            {
                "n_mid": n,
                "mean_edge_versions": round(statistics.mean(edges_n), 1),
                "plan_k1_ms": stat(solve_ms),
                "replan_cold_ms": stat(cold_ms),
                "replan_warm_ms": stat(warm_ms),
                "speedup_median": round(statistics.median(cold_ms) / max(statistics.median(warm_ms), 1e-6), 2),
                "falkordb_active_snapshot_ms": stat(q_ms),
                "falkordb_path_enum_depth6_ms": stat(path_ms),
            }
        )
    return rows


def fmt_rate(r: dict[str, Any]) -> str:
    if not r["n"]:
        return "n/a"
    return f"{r['rate']:.3f} [{r['ci95'][0]:.2f}, {r['ci95'][1]:.2f}] (n={r['n']})"


def write_report(res: dict[str, Any], path: Path) -> None:
    L = [
        "# GHOSTTRACE evaluation report",
        "",
        "> Generated by `evals/run_evals.py` from real runs. Synthetic graphs, synthetic priors, **no real-world validation**.",
        "> Rates show Wilson 95% intervals. All metrics are computed on the hidden ground-truth world W*.",
        "",
        "## Environment",
        "",
    ]
    for k, v in res["environment"].items():
        L.append(f"- {k}: `{v}`")
    total_v = sum(f["soundness"]["violations"] for f in res["families"])
    total_c = sum(f["soundness"]["certificates"] for f in res["families"])
    L += [
        "",
        "## Headline",
        "",
        f"- **Certificate soundness violations: {total_v} / {total_c} certificates** (gate: must be 0).",
        f"- Verifier acceptance of GHOSTTRACE certificates: "
        f"{sum(f['verifier'].get('accepted', 0) for f in res['families'])} / {sum(f['verifier'].get('checked', 0) for f in res['families'])}.",
        "",
    ]
    for fam in res["families"]:
        L += [
            f"## Family `{fam['family']}` — {fam['instances']} instances, seeds {fam['seeds'][0]}–{fam['seeds'][1]}",
            "",
            f"Parameters: `{json.dumps(fam['params'])}`",
            "",
            "| Method | Residual exposure (modeled W*) | Residual exposure (incl. unmodeled) | Hard flow broken | Mean true J | Evidence-attack success | Regret vs optimum |",
            "|---|---|---|---|---|---|---|",
        ]
        for m in METHODS:
            r = fam["methods"][m]
            reg = r["disruption_regret"]
            reg_s = "n/a" if not reg else f"mean {reg['mean']} max {reg['max']} (n={reg['n']})"
            L.append(
                f"| {m} | {fmt_rate(r['residual_exposure_modeled'])} | {fmt_rate(r['residual_exposure_incl_unmodeled'])} | "
                f"{fmt_rate(r['hard_flow_broken'])} | {r['mean_J_true']} | {fmt_rate(r['evidence_attack_success'])} | "
                f"{reg_s} |"
            )
        L += [
            "",
            f"- GHOSTTRACE infeasible plans: k0={fam['methods']['GT_k0']['infeasible']}, "
            f"k1={fam['methods']['GT_k1']['infeasible']}, k2={fam['methods']['GT_k2']['infeasible']}",
            f"- Soundness: {fam['soundness']['violations']} violations over {fam['soundness']['certificates']} certificates",
            f"- Verifier: {fam['verifier']}",
            f"- Verifier mutation testing: {fam['mutation']}",
            f"- Temporal/R2 correctness on churned facts: {fmt_rate(fam['temporal_r2_correctness'])}",
            f"- Citation resolution (action evidence ids resolve to stored records): {fmt_rate(fam['citation_resolution'])}",
            f"- Solver time per plan (ms): {fam['solver_ms']}",
            "",
            "Robustness calibration (fraction of GHOSTTRACE plans reopened in modeled W*, by reopening distance d; "
            "valid only under the generator's synthetic prior p_latent_true):",
            "",
        ]
        for b, r in fam["robustness_calibration"].items():
            L.append(f"- d={b}: {fmt_rate(r)}")
        L += ["", f"Failures listed ({len(fam['failures'])}):", ""]
        L += [f"- `{json.dumps(x)}`" for x in fam["failures"]] or ["- none"]
        L.append("")
    L += [
        "## Scaling (measured)",
        "",
        "| n_mid | mean edge versions | plan k=1 ms (median/p95) | replan cold | replan warm | speedup | FalkorDB snapshot query ms | FalkorDB path enum (depth 6) ms |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in res["scaling"]:
        s = lambda x: "not measured" if not x else f"{x['median']} / {x['p95']} (n={x['samples']})"  # noqa: E731
        L.append(
            f"| {r['n_mid']} | {r['mean_edge_versions']} | {s(r['plan_k1_ms'])} | {s(r['replan_cold_ms'])} | "
            f"{s(r['replan_warm_ms'])} | {r['speedup_median']}× | {s(r['falkordb_active_snapshot_ms'])} | {s(r['falkordb_path_enum_depth6_ms'])} |"
        )
    L += [
        "",
        "## How to read this / limitations",
        "",
        "- B0 = disable alerted account only; B1 = greedy by degree centrality on a time- and trust-blind static graph;"
        " B2 = static min-cost cut ignoring time, trust and must-keep flows; B3 = mock LLM-only recommender (no graph verification).",
        "- 'Residual exposure (incl. unmodeled)' counts hidden edges no system could see; certificates explicitly exclude them by assumption, so this rate is expected to be non-zero for every method.",
        "- Residual exposure in *modeled* W* for GHOSTTRACE comes from hidden-true latent edges; it falls as k rises, which is the measured Price-of-Certainty trade-off.",
        "- 'Regret vs optimum' is measured against the brute-force k=0 optimum (small family only). For GT_k0 it is true "
        "suboptimality; for GT_k1/GT_k2 it is the extra cost paid for robustness (the Price of Certainty), not an error.",
        "- Incremental replanning reuses re-validated constraints/nogoods; measured speedups are modest (see scaling table).",
        "- Costs are seeded integers, not business impact. Generated latent edges bypass template preconditions (documented).",
        "- Soundness here means: no path made only of edges the system classified CONFIRMED survives in W* after the plan.",
        "",
    ]
    path.write_text("\n".join(L))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--falkordb", action="store_true")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    n = 20 if a.quick else a.n
    t0 = time.time()
    fams = []
    start = 0
    for name, params in FAMILIES.items():
        fams.append(run_family(name, params, range(start, start + n), mutation_sample=5 if a.quick else 15))
        start += 1000
    scale = scaling([10, 20, 40] if a.quick else [10, 20, 40, 80, 160], 3 if a.quick else 5, a.falkordb)
    import falkordb

    res = {
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "n/a",
            "falkordb_client": getattr(falkordb, "__version__", "1.7.1 (pinned)"),
            "falkordb_server": "falkordb/falkordb:v4.22.0" if a.falkordb else "not used for metrics",
            "provider": "mock (deterministic)",
            "wall_s": None,
            "instances_per_family": n,
        },
        "families": fams,
        "scaling": scale,
    }
    res["environment"]["wall_s"] = round(time.time() - t0, 1)
    out = ROOT / "evals"
    (out / "results.json").write_text(json.dumps(res, indent=1, default=str))
    write_report(res, out / "report.md")
    v = sum(f["soundness"]["violations"] for f in fams)
    print(f"wrote evals/report.md; soundness violations = {v}; wall {res['environment']['wall_s']}s")
    return 1 if v else 0


if __name__ == "__main__":
    sys.exit(main())
