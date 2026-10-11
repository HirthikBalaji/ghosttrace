"""kappa (cut-set) rules — deterministic, unit-tested per action type."""

from __future__ import annotations

import pytest

from app.model import SnapEdge
from app.reasoning.kappa import KappaError, generate_candidates, kappa


def E(eid, t, a, at, b, bt, cls="OBSERVED"):
    return SnapEdge(eid, 1, t, a, b, at, bt, cls, "ACTIVE")


EDGES = [
    E("u->ws", "CAN_ACCESS", "u", "Identity", "ws", "Host"),
    E("u->usso", "HAS_CREDENTIAL", "u", "Identity", "sso", "Credential"),
    E("sso->u", "AUTHENTICATES_AS", "sso", "Credential", "u", "Identity"),
    E("ws->tok", "HAS_CREDENTIAL", "ws", "Host", "tok", "Credential"),
    E("tok->ci", "AUTHENTICATES_AS", "tok", "Credential", "ci", "Identity"),
    E("ci->role", "CAN_ASSUME", "ci", "Identity", "role", "Identity"),
    E("role->svc", "CAN_ACCESS", "role", "Identity", "svc", "Service"),
    E("svc->db", "CAN_ACCESS", "svc", "Service", "db", "Asset"),
    E("ws->svc2", "CONNECTS_TO", "ws", "Host", "svc2", "Service"),
    E("lat", "CAN_ACCESS", "svc2", "Service", "db", "Asset", cls="LATENT"),
]


def test_disable_identity_does_not_cut_credential_of_other_principal():
    k = kappa("disable_identity", "u", EDGES)
    assert k == {"u->ws", "u->usso", "sso->u"}
    assert "tok->ci" not in k and "ws->tok" not in k  # the ghost credential survives


def test_revoke_credential_cuts_both_sides():
    assert kappa("revoke_credential", "tok", EDGES) == {"ws->tok", "tok->ci"}


def test_isolate_workload_cuts_incident_edges():
    assert kappa("isolate_workload", "ws", EDGES) == {"u->ws", "ws->tok", "ws->svc2"}


def test_grant_and_block_rules():
    assert kappa("remove_access_grant", "role->svc", EDGES) == {"role->svc"}
    assert kappa("block_communication", "ws->svc2", EDGES) == {"ws->svc2"}
    with pytest.raises(KappaError):
        kappa("remove_access_grant", "lat", EDGES)  # cannot remove an unobserved latent grant
    with pytest.raises(KappaError):
        kappa("remove_access_grant", "ws->tok", EDGES)  # HAS_CREDENTIAL is not a grant
    with pytest.raises(KappaError):
        kappa("block_communication", "role->svc", EDGES)


def test_type_checks():
    for at, tgt in [
        ("disable_identity", "ws"),
        ("revoke_credential", "u"),
        ("isolate_workload", "tok"),
        ("pause_deployment", "svc"),
        ("bogus", "u"),
    ]:
        with pytest.raises(KappaError):
            kappa(at, tgt, EDGES)


def test_candidates_cover_relevant_subgraph_only():
    extra = EDGES + [E("x->y", "CAN_ACCESS", "x", "Identity", "y", "Service")]
    c = {a.id for a in generate_candidates(extra, ["u", "ws"], ["db"], {})}
    assert "revoke_credential:tok" in c and "disable_identity:u" in c
    assert not any(a.split(":", 1)[1] == "x" or "x->y" in a for a in c)
