"""§3.1 bitemporal semantics (pure)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.ingestion.ledger import IngestionError, Ledger
from app.model import Node, SourceRecord, TrustPolicy
from app.reasoning.snapshot import build_snapshot
from app.temporal.predicate import TemporalStatus, parse_iso, temporal_predicate, temporal_status, validity_unknown

H = 3_600_000


def f(**kw):
    base = {"tx_from": 0, "tx_to": None, "valid_from": 100, "valid_to": 200, "validity_unknown": False}
    return base | kw


def test_interval_inclusive_start_exclusive_end():
    assert temporal_status(f(), 100, 10) == TemporalStatus.ACTIVE
    assert temporal_status(f(), 199, 10) == TemporalStatus.ACTIVE
    assert temporal_status(f(), 200, 10) == TemporalStatus.INACTIVE
    assert temporal_status(f(), 99, 10) == TemporalStatus.INACTIVE


def test_transaction_interval_half_open():
    assert temporal_status(f(tx_from=50, tx_to=80), 150, 50) == TemporalStatus.ACTIVE
    assert temporal_status(f(tx_from=50, tx_to=80), 150, 80) == TemporalStatus.INVISIBLE
    assert temporal_status(f(tx_from=50), 150, 49) == TemporalStatus.INVISIBLE


def test_missing_timestamps_are_uncertain_not_valid():
    assert validity_unknown(None, None, False)
    assert validity_unknown(100, None, False)  # open end not asserted
    assert not validity_unknown(100, None, True)
    assert temporal_status(f(valid_from=None, valid_to=None, validity_unknown=True), 150, 10) == TemporalStatus.UNCERTAIN
    # provably inactive even though validity is otherwise unknown
    assert temporal_status(f(valid_from=None, valid_to=120, validity_unknown=True), 150, 10) == TemporalStatus.INACTIVE


def test_timezone_normalisation_and_naive_rejected():
    assert parse_iso("2026-03-02T09:00:00Z") == parse_iso("2026-03-02T14:30:00+05:30")
    assert parse_iso("2026-03-02T09:00:00Z") == 1772442000000
    with pytest.raises(ValueError):
        parse_iso("2026-03-02T09:00:00")


def test_predicate_text_is_constant_and_parameterised():
    p = temporal_predicate("r")
    assert "$T" in p and "$tau" in p and "r.valid_from" in p
    with pytest.raises(ValueError):
        temporal_predicate("r) RETURN 1 //")


def _ledger():
    led = Ledger("w")
    for n, lab in [("a", "Identity"), ("b", "Asset"), ("t1", "Team"), ("t2", "Team"), ("s", "Service")]:
        led.add_node(Node(n, lab, "w"))
    led.add_source(SourceRecord("sig", "signed", False, "r1", "high", 0, 0))
    led.add_source(SourceRecord("sig2", "signed", False, "r2", "high", 0, 0))
    return led


def test_revoked_before_vs_after_incident(world_a):
    T_inc = world_a.meta["T_incident"]
    now = world_a.meta["now"]
    snap = build_snapshot(world_a.versions, world_a.sources, T_inc, now, TrustPolicy.CONSERVATIVE)
    assert "e:dev-alice->deploy-role" not in snap  # revoked 2026-01-10, before the incident
    before = parse_iso("2025-12-01T00:00:00Z")
    snap2 = build_snapshot(world_a.versions, world_a.sources, before, now, TrustPolicy.CONSERVATIVE)
    assert "e:dev-alice->deploy-role" in snap2  # still valid before the revocation


def test_post_incident_grant_not_used_for_earlier_access(world_a):
    T_inc, now = world_a.meta["T_incident"], world_a.meta["now"]
    at_inc = build_snapshot(world_a.versions, world_a.sources, T_inc, now, TrustPolicy.CONSERVATIVE)
    at_now = build_snapshot(world_a.versions, world_a.sources, now, now, TrustPolicy.CONSERVATIVE)
    assert "e:ci-runner->artifact-store" not in at_inc  # CHG-4471 valid from 2026-03-03
    assert "e:ci-runner->artifact-store" in at_now


def test_backfill_as_known_before_ingestion_returns_old_world(world_a):
    T_inc, now = world_a.meta["T_incident"], world_a.meta["now"]
    known_then = build_snapshot(world_a.versions, world_a.sources, T_inc, T_inc, TrustPolicy.CONSERVATIVE)
    known_now = build_snapshot(world_a.versions, world_a.sources, T_inc, now, TrustPolicy.CONSERVATIVE)
    assert "own:payments-api:team-payments" in known_then and "own:payments-api:team-platform" not in known_then
    assert "own:payments-api:team-platform" in known_now and "own:payments-api:team-payments" not in known_now


def test_supersession_preserves_history():
    led = _ledger()
    led.assert_edge(fact_id="o", type="OWNS", src="t1", dst="s", at=1000, source_ids=["sig"], valid_from=0,
                    valid_open_ended=True)
    led.correct_edge(fact_id="o", at=5000, source_ids=["sig2"], valid_to=3000)
    vs = led.versions["o"]
    assert [v.version for v in vs] == [1, 2]
    assert vs[0].tx_to == 5000 and vs[1].tx_from == 5000 and vs[1].supersedes == 1
    assert vs[0].valid_to is None and vs[1].valid_to == 3000


def test_idempotent_reassert_and_corroboration():
    led = _ledger()
    kw = dict(fact_id="e", type="CAN_ACCESS", src="a", dst="b", valid_from=0, valid_open_ended=True)
    assert led.assert_edge(at=10, source_ids=["sig"], **kw) == "created"
    assert led.assert_edge(at=20, source_ids=["sig"], **kw) == "noop"
    assert led.assert_edge(at=30, source_ids=["sig2"], **kw) == "superseded"
    assert led.versions["e"][-1].source_ids == ["sig", "sig2"]


def test_ingestion_validation():
    led = _ledger()
    with pytest.raises(IngestionError):
        led.assert_edge(fact_id="x", type="NOT_A_TYPE", src="a", dst="b", at=1, source_ids=["sig"])
    with pytest.raises(IngestionError):
        led.assert_edge(fact_id="x", type="CAN_ACCESS", src="a", dst="b", at=1, source_ids=["missing"])
    with pytest.raises(IngestionError):
        led.assert_edge(fact_id="x", type="CAN_ACCESS", src="a", dst="b", at=1, source_ids=["sig"], valid_from=5,
                        valid_to=5)
    with pytest.raises(ValueError):
        led.assert_edge(fact_id="x", type="CAN_ACCESS", src="a", dst="b", at="2026-01-01T00:00:00",
                        source_ids=["sig"])


@given(vf=st.one_of(st.none(), st.integers(0, 1000)), vt=st.one_of(st.none(), st.integers(0, 1000)),
       T=st.integers(0, 1000), txf=st.integers(0, 100), txt=st.one_of(st.none(), st.integers(0, 200)),
       tau=st.integers(0, 200), open_=st.booleans())
def test_bitemporal_visibility_invariants(vf, vt, T, txf, txt, tau, open_):
    fact = {"tx_from": txf, "tx_to": txt, "valid_from": vf, "valid_to": vt,
            "validity_unknown": validity_unknown(vf, vt, open_)}
    s = temporal_status(fact, T, tau)
    visible = txf <= tau and (txt is None or tau < txt)
    assert (s != TemporalStatus.INVISIBLE) == visible
    if s == TemporalStatus.ACTIVE:
        assert vf is not None and vf <= T and (vt is None or T < vt)
        assert vt is not None or open_
    if s == TemporalStatus.UNCERTAIN:
        assert fact["validity_unknown"]
