"""Planner: scenario properties, CEGAR vs brute force, robustness, Pareto, depth-bound soundness, warm start."""

from __future__ import annotations

import copy
import json

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.ingestion.ledger import Ledger
from app.ingestion.scenario import load, read_scenario, world_from
from app.model import Flow, Node, SourceRecord, TrustPolicy
from app.planner import engine
from app.planner.brute import brute_force
from app.planner.cegar import evaluate_plan, solve
from app.reasoning.paths import INF, classify_path, reachable, reopening_distance
from evals.generator.generator import GenParams, generate
from tests.conftest import write_export
from verifier import check

P = TrustPolicy.CONSERVATIVE


def _now(w):
    return w.meta["now"]


# ---------------------------------------------------------------- scenario A (Ghost Credential)
def test_b0_disabling_alerted_account_leaves_confirmed_path(world_a):
    now = _now(world_a)
    _, _, res = engine.simulate(world_a, now, now, P, ["disable_identity:id:dev-alice"])
    assert res.status == "not_contained" and res.d == 0
    info = classify_path(res.witness)
    assert info.path_class == "CONFIRMED" and "e:ws-alice->ci-token" in info.edge_ids


def test_incomplete_plan_rejected_with_residual_paths(world_a, tmp_path):
    now = _now(world_a)
    edges, cands, res = engine.simulate(world_a, now, now, P, ["disable_identity:id:dev-alice"])
    cert, lines = engine.build_certificate(world_a, now, now, P, edges, cands, res, 0)
    assert cert["status"] == "not_contained" and cert["residual_confirmed_paths"]
    assert check(cert, write_export(tmp_path, lines)) == []  # verifier agrees it is NOT contained
    forged = copy.deepcopy(cert)
    forged["status"], forged["residual_confirmed_paths"] = "contained", []
    assert check(forged, write_export(tmp_path, lines))


def test_price_of_certainty_curve(world_a):
    now = _now(world_a)
    res = engine.pareto(world_a, now, now, P, 2)
    pts = engine.pareto_points(res)
    assert all(p["feasible"] and p["optimality"] == "proven_optimal" for p in pts)
    k0, k1 = res[0], res[1]
    assert {a.id for a in k0.actions} != {a.id for a in k1.actions}
    assert len({p["total_cost"] for p in pts}) >= 2
    assert k0.d == 1 and k1.d == 2  # k0 plan is exactly 0-robust: one unverified edge re-opens access
    assert any(not e.confirmed for e in k0.witness)


def test_both_certificates_verified(world_a, tmp_path):
    now = _now(world_a)
    for k in (0, 1, 2):
        edges, cands, res = engine.plan(world_a, now, now, P, k)
        cert, lines = engine.certify_plan(world_a, now, now, P, edges, cands, res, k)
        assert cert["status"] == "contained"
        assert check(cert, write_export(tmp_path, lines)) == [], k


def test_latent_reopening_witness_and_priority(world_a):
    now = _now(world_a)
    edges, cands, res = engine.plan(world_a, now, now, P, 0)
    cert, _ = engine.build_certificate(world_a, now, now, P, edges, cands, res, 0)
    rob = cert["robustness"]
    assert rob["k_certified"] == 0 and rob["min_reopening_latent_edges"] == 1
    wit = rob["witness_paths"][0]
    by_id = {e.edge_id: e for e in edges}
    assert sum(1 for e in wit if not by_id[e].confirmed) == 1
    assert [p["edge_id"] for p in rob["verification_priority"]] == [e for e in wit if not by_id[e].confirmed]


def test_scenario_b_differs_by_computation(world_a, world_b):
    nb = _now(world_b)
    _, _, rb = engine.plan(world_b, nb, nb, P, 0)
    _, _, ra = engine.plan(world_a, _now(world_a), _now(world_a), P, 0)
    assert rb.status == "contained" and {a.id for a in rb.actions} != {a.id for a in ra.actions}
    assert "remove_access_grant:b:etl->pii" in {a.id for a in rb.actions}
    # the hard nightly-export flow is what rules out the cheapest cut: drop it and the plan changes
    w2 = copy.deepcopy(world_b)
    w2.flows = [f for f in w2.flows if f.flow_id != "flow:nightly-export"]
    _, _, rb2 = engine.plan(w2, nb, nb, P, 0)
    assert "block_communication:b:agent7->etl" in {a.id for a in rb2.actions}
    assert rb2.total < rb.total


def test_hard_flows_never_broken_by_certified_plans(world_a, world_b):
    for w in (world_a, world_b):
        now = _now(w)
        for r in engine.pareto(w, now, now, P, 2):
            if r.status == "contained":
                assert all(r.flows[f.flow_id] for f in w.flows if f.kind == "hard")


def test_missing_evidence_yields_uncertainty_not_confirmation():
    led = Ledger("w")
    for n, lab in [("s", "Identity"), ("h", "Host"), ("t", "Asset")]:
        led.add_node(Node(n, lab, "w"))
    led.add_source(SourceRecord("sig", "signed", False, "r", "high", 0, 0))
    led.assert_edge(fact_id="a", type="CAN_ACCESS", src="s", dst="h", at=0, source_ids=["sig"], valid_from=0,
                    valid_open_ended=True)
    led.assert_edge(fact_id="b", type="CAN_ACCESS", src="h", dst="t", at=0, source_ids=["sig"])  # no validity
    w = engine.World("w", led.all_versions(), led.sources, {}, [], ["s"], ["t"])
    edges = engine.snapshot_edges(w, 10, 10, P)
    d, wit = reopening_distance(edges, frozenset(), ["s"], ["t"])
    assert d == 1 and classify_path(wit).path_class == "TEMPORALLY_UNCERTAIN"
    res = evaluate_plan(edges, ["s"], ["t"], [], [])
    assert res.status == "contained" and res.d == 1  # no CONFIRMED path; uncertainty reported via d


# ---------------------------------------------------------------- solver vs brute force (generated)
def _gen_world(seed: int, n_mid: int = 6):
    inst = generate(seed, GenParams(n_mid=n_mid, n_paths=2, n_hard=1, n_soft=2))
    led, meta = load(inst.scenario, "gen")
    return world_from(led, meta)


def test_solver_matches_brute_force_on_small_instances():
    compared = 0
    for seed in range(40):
        w = _gen_world(seed)
        now = _now(w)
        for k in (0, 1):
            edges, cands, res = engine.plan(w, now, now, P, k)
            if len(cands) > 14:
                continue
            bf = brute_force(edges, w.attack_sources, w.targets, w.flows, cands, k)
            if res.optimality == "proven_optimal":
                assert (bf[0] if bf else None) == (res.total if res.status == "contained" else None), (seed, k)
                compared += 1
    assert compared >= 30


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(seed=st.integers(0, 10_000))
def test_planner_output_verified_on_generated_instances(seed, tmp_path_factory):
    w = _gen_world(seed, n_mid=8)
    now = _now(w)
    for k in (0, 1):
        edges, cands, res = engine.plan(w, now, now, P, k)
        if res.status != "contained":
            continue
        cert, lines = engine.build_certificate(w, now, now, P, edges, cands, res, k)
        assert check(cert, write_export(tmp_path_factory.mktemp("v"), lines)) == []


@settings(max_examples=30, deadline=None)
@given(seed=st.integers(0, 10_000), data=st.data())
def test_monotonicity_adding_an_action_never_increases_reachability(seed, data):
    w = _gen_world(seed)
    now = _now(w)
    edges = engine.snapshot_edges(w, now, now, P)
    cands = engine.candidates_for(w, edges)
    if not cands:
        return
    idx = data.draw(st.lists(st.integers(0, len(cands) - 1), max_size=4, unique=True))
    extra = data.draw(st.integers(0, len(cands) - 1))
    base = frozenset().union(*(cands[i].removes for i in idx)) if idx else frozenset()
    more = base | cands[extra].removes
    d0, _ = reopening_distance(edges, base, w.attack_sources, w.targets)
    d1, _ = reopening_distance(edges, more, w.attack_sources, w.targets)
    assert d1 >= d0
    for u in w.attack_sources:
        for t in w.targets:
            assert not (reachable(edges, more, u, t) and not reachable(edges, base, u, t))


def test_snapshot_hash_deterministic(world_a):
    now = _now(world_a)
    e1, c1, r1 = engine.plan(world_a, now, now, P, 0)
    l1 = engine.export_lines(world_a, now, now, P, e1, c1)
    l2 = engine.export_lines(world_a, now, now, P, list(reversed(e1)), list(reversed(c1)))
    assert engine.snapshot_hash(l1) == engine.snapshot_hash(l2)
    assert engine.snapshot_hash(l1) != engine.snapshot_hash(engine.export_lines(world_a, now - 1, now, P, e1, c1))


# ---------------------------------------------------------------- depth-bound soundness (pure part)
def test_exhaustive_check_independent_of_depth_bound():
    led = Ledger("w")
    n = 20
    for i in range(n + 1):
        led.add_node(Node(f"n{i}", "Identity" if i < n else "Asset", "w"))
    led.add_source(SourceRecord("sig", "signed", False, "r", "high", 0, 0))
    for i in range(n):
        led.assert_edge(fact_id=f"e{i}", type="CAN_ASSUME" if i < n - 1 else "CAN_ACCESS", src=f"n{i}", dst=f"n{i+1}",
                        at=0, source_ids=["sig"], valid_from=0, valid_open_ended=True)
    w = engine.World("w", led.all_versions(), led.sources, {}, [], ["n0"], [f"n{n}"])
    edges = engine.snapshot_edges(w, 1, 1, P)
    from app.reasoning.paths import enumerate_paths
    assert enumerate_paths(edges, frozenset(), ["n0"], [f"n{n}"], max_depth=12, max_paths=10) == []
    d, wit = reopening_distance(edges, frozenset(), ["n0"], [f"n{n}"])
    assert d == 0 and len(wit) == n
    assert evaluate_plan(edges, ["n0"], [f"n{n}"], [], []).status == "not_contained"


# ---------------------------------------------------------------- incremental == from scratch
def test_warm_start_equals_cold_after_new_evidence():
    data = read_scenario("ghost_credential_a")
    led, meta = load(data, "w")
    w = world_from(led, meta)
    now = _now(w)
    _, _, warm_src = engine.plan(w, now, now, P, 1)
    # new evidence: a signed record shows dev-alice can directly assume ci-runner
    data2 = json.loads(json.dumps(data))
    data2["sources"].append({"source_id": "src:new-edr", "system": "edr", "integrity": "signed", "root_id": "edr2",
                             "trust_class": "high", "observed_at": "2026-03-09T00:00:00Z",
                             "ingested_at": "2026-03-09T00:00:00Z", "content": "new"})
    data2["events"].append({"op": "assert", "at": "2026-03-09T00:00:00Z", "fact_id": "e:dev-alice->ci-runner",
                            "type": "CAN_ASSUME", "src": "id:dev-alice", "dst": "id:ci-runner",
                            "valid_from": "2026-03-08T00:00:00Z", "valid_open_ended": True, "sources": ["src:new-edr"],
                            "cost_remove": 2})
    led2, meta2 = load(data2, "w")
    w2 = world_from(led2, meta2)
    for k in (0, 1, 2):
        e_c, c_c, cold = engine.plan(w2, now, now, P, k)
        _, _, warm = engine.plan(w2, now, now, P, k, warm=warm_src)
        assert cold.status == warm.status and cold.total == warm.total and cold.optimality == warm.optimality, k
        assert cold.d == warm.d


def test_budget_exhaustion_never_claims_optimal(world_a):
    from app.planner.cegar import Budgets
    now = _now(world_a)
    edges = engine.snapshot_edges(world_a, now, now, P)
    cands = engine.candidates_for(world_a, edges)
    res = solve(edges, world_a.attack_sources, world_a.targets, world_a.flows, cands, 1,
                Budgets(max_iterations=1))
    assert res.optimality != "proven_optimal"


def test_flows_only_count_confirmed_edges():
    from app.model import SnapEdge
    es = [SnapEdge("a", 1, "CAN_ACCESS", "u", "v", "Service", "Service", "LATENT", "ACTIVE")]
    fl = [Flow("f", "u", "v", 100, "hard")]
    assert not reachable(es, frozenset(), "u", "v")
    assert evaluate_plan(es, ["x"], ["y"], fl, []).status == "not_contained"
    assert INF > 0
