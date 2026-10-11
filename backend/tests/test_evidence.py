"""R1-R5 evidence calculus."""

from __future__ import annotations

from app.ingestion.ledger import Ledger
from app.model import EpistemicClass, Flag, Node, SourceRecord, TrustPolicy
from app.planner import engine
from app.reasoning.evidence import classify_asserted, independent, independent_root_count, meets_r1, trusted_removal
from app.reasoning.snapshot import build_snapshot


def S(sid, integ="none", ai=False, root=None, trust="medium", derived=None):
    return SourceRecord(sid, integ, ai, root or sid, trust, 0, 0, derived_from=derived or [])


SRC = {
    "signed": S("signed", "signed", root="r-signed"),
    "hash": S("hash", "hash_verified", root="r-hash"),
    "weak1": S("weak1", root="r-w1"),
    "weak2": S("weak2", root="r-w2"),
    "dupA": S("dupA", root="feed"),
    "dupB": S("dupB", root="feed", derived=["dupA"]),
    "derived": S("derived", root="r-derived", derived=["weak1"]),
    "ai_signed": S("ai_signed", "signed", ai=True, root="r-ai1"),
    "ai1": S("ai1", ai=True, root="r-ai2"),
    "ai2": S("ai2", ai=True, root="r-ai3"),
}


def test_r1_observation_threshold():
    assert meets_r1(["signed"], SRC)
    assert meets_r1(["hash"], SRC)
    assert meets_r1(["weak1", "weak2"], SRC)
    assert not meets_r1(["weak1"], SRC)
    assert not meets_r1(["ai_signed"], SRC)  # integrity-verified but attacker-influenceable


def test_independence_counts_distinct_roots_not_records():
    assert not independent("dupA", "dupB", SRC)
    assert independent_root_count(["dupA", "dupB"], SRC) == 1
    assert not meets_r1(["dupA", "dupB"], SRC)
    assert not independent("weak1", "derived", SRC)  # provenance DAG ancestry
    assert independent_root_count(["weak1", "derived", "weak2"], SRC) == 2


def test_r3_false_flag_and_weak_support():
    cls, flags = classify_asserted(["ai1", "ai2"], SRC)
    assert cls == EpistemicClass.LATENT and Flag.POSSIBLE_FALSE_FLAG.value in flags
    cls, flags = classify_asserted(["weak1"], SRC)
    assert cls == EpistemicClass.LATENT and Flag.WEAKLY_SUPPORTED.value in flags
    cls, flags = classify_asserted(["signed", "ai1"], SRC)
    assert cls == EpistemicClass.OBSERVED


def test_r2_untrusted_removal_disputes_not_removes():
    assert not trusted_removal(["ai_signed"], SRC)
    assert not trusted_removal(["weak1"], SRC)
    assert trusted_removal(["signed"], SRC)
    led = Ledger("w")
    for n, lab in [("h", "Host"), ("c", "Credential")]:
        led.add_node(Node(n, lab, "w"))
    for s in SRC.values():
        led.add_source(s)
    led.assert_edge(fact_id="e", type="HAS_CREDENTIAL", src="h", dst="c", at=10, source_ids=["signed"], valid_from=0,
                    valid_open_ended=True)
    assert led.remove_edge(fact_id="e", removed_at=50, at=60, source_ids=["ai1"]) == "disputed"
    snap = build_snapshot(led.all_versions(), led.sources, 100, 100, TrustPolicy.CONSERVATIVE)
    assert "e" in snap and Flag.DISPUTED.value in snap["e"].flags and snap["e"].confirmed
    # trust_filtered drops the attacker-influenceable dispute entirely; the edge remains
    snap_f = build_snapshot(led.all_versions(), led.sources, 100, 100, TrustPolicy.TRUST_FILTERED)
    assert "e" in snap_f and Flag.DISPUTED.value not in snap_f["e"].flags
    assert led.remove_edge(fact_id="e", removed_at=70, at=80, source_ids=["signed"]) == "closed"
    snap2 = build_snapshot(led.all_versions(), led.sources, 100, 100, TrustPolicy.CONSERVATIVE)
    assert "e" not in snap2


def test_trust_filtered_excludes_attacker_only_assertions(world_a):
    now = world_a.meta["now"]
    cons = build_snapshot(world_a.versions, world_a.sources, now, now, TrustPolicy.CONSERVATIVE)
    filt = build_snapshot(world_a.versions, world_a.sources, now, now, TrustPolicy.TRUST_FILTERED)
    ff = "e:shared-config->cardholder-db"
    assert cons[ff].cls == "LATENT" and Flag.POSSIBLE_FALSE_FLAG.value in cons[ff].flags
    assert ff not in filt


def test_duplicate_alerts_counted_once(world_a):
    now = world_a.meta["now"]
    snap = build_snapshot(world_a.versions, world_a.sources, now, now, TrustPolicy.CONSERVATIVE)
    e = snap["e:dev-alice->repo"]
    assert sorted(e.source_ids) == ["src:siem-dup-a", "src:siem-dup-b"]
    assert e.cls == "LATENT" and Flag.WEAKLY_SUPPORTED.value in e.flags


def test_r4_sensitivity_flags_false_flag_driven_action(world_a):
    now = world_a.meta["now"]
    sens = engine.evidence_sensitivity(world_a, now, now, K=2)
    k1 = next(s for s in sens if s["k"] == 1)
    assert k1["differs"] and "remove_access_grant:e:ws-alice->shared-config" in k1["only_conservative"]


def test_r3_requires_human_scrutiny_in_certificate(world_a):
    now = world_a.meta["now"]
    edges, cands, res = engine.plan(world_a, now, now, TrustPolicy.CONSERVATIVE, 1)
    cert, _ = engine.build_certificate(world_a, now, now, TrustPolicy.CONSERVATIVE, edges, cands, res, 1)
    scrut = {x["action_id"] for x in cert["requires_human_scrutiny"]}
    assert scrut == {"remove_access_grant:e:ws-alice->shared-config"}
    assert "e:ci-token->ci-runner" in cert["disputed_removals"]


def test_r5_load_bearing_evidence(world_a):
    now = world_a.meta["now"]
    edges, cands, res = engine.plan(world_a, now, now, TrustPolicy.CONSERVATIVE, 0)
    cert, _ = engine.certify_plan(world_a, now, now, TrustPolicy.CONSERVATIVE, edges, cands, res, 0)
    lb = {tuple(x["sources"]): x["invalidates"] for x in cert["load_bearing_detail"]}
    # falsifying the trusted revocation reopens dev-alice -> deploy-role: a confirmed path survives
    assert ("src:iam-revoke-2026-01",) in lb and "CONFIRMED path survives" in lb[("src:iam-revoke-2026-01",)]
    # minimality: no reported set is a superset of another
    sets = [set(s) for s in lb]
    assert not any(a < b for a in sets for b in sets)
    # each reported set really invalidates; a non-reported record does not
    for s, _why in lb.items():
        assert engine._claims_hold(world_a, now, now, TrustPolicy.CONSERVATIVE, res, cert, frozenset(s)) is not None
    assert engine._claims_hold(world_a, now, now, TrustPolicy.CONSERVATIVE, res, cert,
                               frozenset({"src:wiki-owner"})) is None
