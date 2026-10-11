"""Integration tests against a real FalkorDB: schema, ingestion, bitemporal and path differentials,
latent-template differential, depth-bound soundness, tenant isolation, read-only enforcement."""

from __future__ import annotations

import itertools

import pytest

from app.graph import queries as Q
from app.graph.client import GraphClient, WorkspaceError, graph_key
from app.graph.repository import Repository
from app.graph.schema import CURRENT_SCHEMA_VERSION, current_version, migrate
from app.ingestion.ledger import Ledger
from app.ingestion.scenario import ScenarioMeta, load, read_scenario
from app.ingestion.seed import cypher_precondition, seed
from app.model import Flow, Node, SourceRecord, TrustPolicy
from app.planner import engine
from app.reasoning.latent import TEMPLATES, check_preconditions_py
from app.reasoning.paths import enumerate_paths, reopening_distance
from app.reasoning.snapshot import build_snapshot
from app.temporal.predicate import TemporalStatus, parse_iso, temporal_status
from evals.generator.generator import GenParams, generate

pytestmark = pytest.mark.integration


def test_migrations_idempotent(falkor: GraphClient, ws: str):
    repo = Repository(falkor, ws)
    assert repo.init_schema() == [1, 2]
    assert migrate(falkor, ws) == []
    assert current_version(falkor, ws) == CURRENT_SCHEMA_VERSION
    idx = falkor._g(ws).list_indices().result_set
    edge_props = {(r[0], p) for r in idx if r[6] == "RELATIONSHIP" for p in r[1]}
    assert ("CAN_ACCESS", "edge_id") in edge_props and ("CAN_ACCESS", "tx_from") not in edge_props


def test_seed_is_idempotent_and_reproducible(falkor: GraphClient, ws: str):
    s1 = seed(falkor, ws, "ghost_credential_a")
    counts = (falkor.ro(ws, Q.COUNT_ALL)[0][0], falkor.ro(ws, Q.COUNT_EDGES)[0][0])
    s2 = seed(falkor, ws, "ghost_credential_a", reset=False)  # re-ingest on top: no duplicates
    assert (falkor.ro(ws, Q.COUNT_ALL)[0][0], falkor.ro(ws, Q.COUNT_EDGES)[0][0]) == counts
    assert s1["edge_versions"] == s2["edge_versions"]
    seed(falkor, ws, "ghost_credential_a")  # reset reproduces the same graph
    assert (falkor.ro(ws, Q.COUNT_ALL)[0][0], falkor.ro(ws, Q.COUNT_EDGES)[0][0]) == counts


def test_world_roundtrip_matches_ledger(falkor: GraphClient, ws: str, world_a):
    seed(falkor, ws, "ghost_credential_a")
    w = Repository(falkor, ws).world()
    key = lambda v: (v.edge_id, v.version, v.tx_from, v.tx_to, v.valid_from, v.valid_to, v.validity_unknown,  # noqa: E731
                     tuple(v.source_ids), tuple(v.dispute_source_ids), v.kind)
    assert sorted(map(key, w.versions)) == sorted(map(key, world_a.versions))
    now = world_a.meta["now"]
    assert engine.pareto_points(engine.pareto(w, now, now, TrustPolicy.CONSERVATIVE, 2)) == \
        engine.pareto_points(engine.pareto(world_a, now, now, TrustPolicy.CONSERVATIVE, 2))


def test_cypher_temporal_predicate_equals_python(falkor: GraphClient, ws: str, world_a):
    seed(falkor, ws, "ghost_credential_a")
    repo = Repository(falkor, ws)
    points = sorted({v.tx_from for v in world_a.versions} | {v.valid_from or 0 for v in world_a.versions}
                    | {v.valid_to or 0 for v in world_a.versions})
    probes = [p + d for p in points[::2] for d in (-1, 0, 1)]
    checked = 0
    for T, tau in itertools.islice(itertools.product(probes, probes), 0, None, 7):
        cy = {(v.edge_id, v.version, st) for v, st in repo.active_versions(T, tau)}
        py = set()
        for v in world_a.versions:
            st = temporal_status(v, T, tau)
            if st in (TemporalStatus.ACTIVE, TemporalStatus.UNCERTAIN):
                py.add((v.edge_id, v.version, st.value))
        assert cy == py, (T, tau)
        checked += 1
    assert checked > 50


def test_backfill_ownership_as_known_then_vs_now(falkor: GraphClient, ws: str):
    from app.agents.brain import CompanyBrain
    from app.agents.schemas import BrainQuery
    seed(falkor, ws, "ghost_credential_a")
    repo = Repository(falkor, ws)
    T = parse_iso("2026-03-02T09:00:00Z")
    now = repo.meta()["now"]
    then = CompanyBrain(repo).ask(BrainQuery(question="owner", subject_id="svc:payments-api", T=T, tau=T))
    later = CompanyBrain(repo).ask(BrainQuery(question="owner", subject_id="svc:payments-api", T=T, tau=now))
    assert then.primary[0]["team_id"] == "team:payments" and later.primary[0]["team_id"] == "team:platform"
    # conflicting ownership is surfaced with its temporal scope, never silently resolved
    assert any("team:sre" in w for w in then.warnings + later.warnings)
    assert later.contradictions and later.temporal_scope["tau"] == now
    assert any("stale" in w for w in then.warnings)


def _differential(falkor, ws, w, T, tau, depth):
    repo = Repository(falkor, ws)
    edges = engine.snapshot_edges(w, T, tau, TrustPolicy.CONSERVATIVE)
    allowed = [e.edge_id for e in edges]
    cy = {tuple(e) for e, n in repo.find_paths_cypher(w.attack_sources, w.targets, allowed, T, tau, depth, 2000)
          if len(set(n)) == len(n)}
    py = {p.edge_ids for p in enumerate_paths(edges, frozenset(), w.attack_sources, w.targets, depth, 100000)}
    return cy, py


def test_differential_paths_scenario_a(falkor: GraphClient, ws: str, world_a):
    seed(falkor, ws, "ghost_credential_a")
    now = world_a.meta["now"]
    for T in (world_a.meta["T_incident"], now):
        cy, py = _differential(falkor, ws, world_a, T, now, 8)
        assert cy == py and py


def test_differential_paths_generated(falkor: GraphClient):
    from app.ingestion.scenario import world_from
    agree = 0
    for seed_ in range(12):
        inst = generate(seed_, GenParams(n_mid=8))
        wsid = f"t-gen-{seed_}"
        repo = Repository(falkor, wsid)
        repo.reset()
        led, meta = load(inst.scenario, wsid)
        repo.persist_ledger(led, meta)
        w = world_from(led, meta)
        now = meta.now
        cy, py = _differential(falkor, wsid, w, now, now, 6)
        assert cy == py, seed_
        # reachability verdict (exhaustive) on the DB-loaded world equals the in-memory reference
        w_db = repo.world()
        d1, _ = reopening_distance(engine.snapshot_edges(w_db, now, now, TrustPolicy.CONSERVATIVE), frozenset(),
                                   w.attack_sources, w.targets)
        d2, _ = reopening_distance(engine.snapshot_edges(w, now, now, TrustPolicy.CONSERVATIVE), frozenset(),
                                   w.attack_sources, w.targets)
        assert d1 == d2
        falkor.drop_workspace(wsid)
        agree += 1
    assert agree == 12


def test_latent_template_cypher_equals_python(falkor: GraphClient, ws: str):
    seed(falkor, ws, "ghost_credential_a")
    repo = Repository(falkor, ws)
    w = repo.world()
    now = w.meta["now"]
    snap = build_snapshot(w.versions, w.sources, now, now, TrustPolicy.CONSERVATIVE)
    nodes = sorted(w.node_props)
    checked = positives = 0
    for tid, t in TEMPLATES.items():
        for a in nodes:
            if w.node_props[a]["label"] not in t.src_types:
                continue
            for b in nodes:
                if a == b or w.node_props[b]["label"] not in t.dst_types:
                    continue
                cy = cypher_precondition(repo, tid, a, b, now)
                py = check_preconditions_py(tid, a, b, snap, w.node_props)
                assert cy == py, (tid, a, b)
                checked += 1
                positives += int(cy)
    assert checked > 100 and positives >= 3


def test_depth_bound_soundness_in_falkordb(falkor: GraphClient, ws: str):
    repo = Repository(falkor, ws)
    repo.init_schema()
    led = Ledger(ws)
    n = Q.MAX_CYPHER_DEPTH + 3
    for i in range(n + 1):
        led.add_node(Node(f"n{i}", "Identity" if i < n else "Asset", ws))
    led.add_source(SourceRecord("sig", "signed", False, "r", "high", 0, 0))
    for i in range(n):
        led.assert_edge(fact_id=f"e{i}", type="CAN_ASSUME" if i < n - 1 else "CAN_ACCESS", src=f"n{i}",
                        dst=f"n{i + 1}", at=0, source_ids=["sig"], valid_from=0, valid_open_ended=True)
    meta = ScenarioMeta("chain", "chain", "", {"incident_id": "INC-CHAIN", "title": "chain", "severity": "low",
                                               "compromised_set": ["n0"], "targets": [f"n{n}"], "T_incident":
                                               "2026-01-01T00:00:00Z"}, 10, [Flow("f", "n0", "n1", 1, "soft")], [], [], [])
    repo.persist_ledger(led, meta)
    w = repo.world()
    edges = engine.snapshot_edges(w, 5, 5, TrustPolicy.CONSERVATIVE)
    rows = repo.find_paths_cypher(["n0"], [f"n{n}"], [e.edge_id for e in edges], 5, 5, 99, 100)
    assert rows == []  # beyond the clamped Cypher depth
    d, wit = reopening_distance(edges, frozenset(), ["n0"], [f"n{n}"])
    assert d == 0 and len(wit) == n  # the exhaustive verdict still finds it
    _, _, res = engine.simulate(w, 5, 5, TrustPolicy.CONSERVATIVE, [])
    assert res.status == "not_contained"


def test_tenant_isolation_graph_and_properties(falkor: GraphClient):
    a, b = "t-iso-a", "t-iso-b"
    try:
        seed(falkor, a, "ghost_credential_a")
        seed(falkor, b, "ghost_credential_b")
        ra, rb = Repository(falkor, a), Repository(falkor, b)
        ids_a = set(ra.nodes())
        ids_b = set(rb.nodes())
        assert "id:dev-alice" in ids_a and "id:dev-alice" not in ids_b
        assert ra.meta()["scenario_id"] != rb.meta()["scenario_id"]
        # defense in depth: even inside graph A, a query scoped to workspace B returns nothing
        assert falkor.ro(a, Q.ALL_NODES, {"ws": b}) == []
        with pytest.raises(WorkspaceError):
            graph_key("../ws:a")
        with pytest.raises(WorkspaceError):
            Repository(falkor, "A B")
    finally:
        falkor.drop_workspace(a)
        falkor.drop_workspace(b)


def test_read_only_path_rejects_writes(falkor: GraphClient, ws: str):
    seed(falkor, ws, "ghost_credential_a")
    with pytest.raises(Exception, match="read-only"):
        falkor.ro(ws, "CREATE (:Evil {x: 1})")
    with pytest.raises(Exception):
        Repository(falkor, ws).ro("MATCH (n) DETACH DELETE n", {})
    assert falkor.ro(ws, Q.COUNT_ALL)[0][0] > 0


def test_injection_strings_are_inert_parameters(falkor: GraphClient, ws: str):
    seed(falkor, ws, "ghost_credential_a")
    repo = Repository(falkor, ws)
    before = falkor.ro(ws, Q.COUNT_ALL)[0][0]
    evil = "x'}) MATCH (n) DETACH DELETE n //"
    assert repo.ro(Q.OWNERS, {"sid": evil, "T": 0, "tau": 0}) == []
    assert repo.ro(Q.SEARCH_NODES, {"q": evil}) == []
    assert falkor.ro(ws, Q.COUNT_ALL)[0][0] == before


def test_query_timeout_enforced(falkor: GraphClient, ws: str):
    Repository(falkor, ws).init_schema()
    with pytest.raises(Exception, match="(?i)timed out"):
        falkor.ro(ws, "UNWIND range(1, 50000000) AS x RETURN count(x)", timeout_ms=5)
