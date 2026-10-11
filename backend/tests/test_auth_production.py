"""Production features: OIDC/JWT auth + roles + workspace scoping, production fail-closed, approval workflow
(four-eyes, scrutiny acknowledgement, verifier re-check), queue-mode worker, shared rate limiter."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.security import auth
from app.security.auth import AuthConfigError, check_settings
from app.security.ratelimit import RateLimiter

ISS, AUD = "https://idp.example.test/", "ghosttrace-api"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def b64u(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


JWKS = json.dumps(
    {
        "keys": [
            {
                "kty": "RSA",
                "kid": "k1",
                "use": "sig",
                "alg": "RS256",
                "n": b64u(KEY.public_key().public_numbers().n),
                "e": b64u(KEY.public_key().public_numbers().e),
            }
        ]
    }
)


def token(
    sub: str = "alice@example.test",
    roles: Any = ("analyst",),
    workspaces: Any = ("*",),
    key: Any = KEY,
    alg: str = "RS256",
    kid: str = "k1",
    **over: Any,
) -> str:
    now = int(time.time())
    claims = {
        "iss": ISS,
        "aud": AUD,
        "sub": sub,
        "iat": now,
        "exp": now + 300,
        "roles": list(roles),
        "gt_workspaces": list(workspaces),
    } | over
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


@pytest.fixture()
def oidc(monkeypatch) -> Iterator[None]:
    s = get_settings()
    for k, v in {
        "auth_mode": "oidc",
        "oidc_issuer": ISS,
        "oidc_audience": AUD,
        "oidc_jwks_json": JWKS,
        "oidc_jwks_url": None,
        "oidc_algorithms": "RS256",
        "require_four_eyes": True,
    }.items():
        monkeypatch.setattr(s, k, v)
    auth.keys.clear()
    yield
    auth.keys.clear()


def bearer(t: str, ws: str = "demo") -> dict[str, str]:
    return {"Authorization": f"Bearer {t}", "X-GT-Workspace": ws}


def test_valid_token_and_roles(oidc):
    c = TestClient(app)
    r = c.get("/api/v1/whoami", headers=bearer(token(roles=["viewer", "analyst", "not-a-role"])))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["auth_mode"] == "oidc" and d["roles"] == ["analyst", "viewer"] and d["warning"] is None


@pytest.mark.parametrize(
    ("tok", "code"),
    [
        (lambda: token(exp=int(time.time()) - 3600), 401),
        (lambda: token(aud="someone-else"), 401),
        (lambda: token(iss="https://evil.example/"), 401),
        (lambda: token(key=OTHER_KEY), 401),  # signed by an unknown key
        (
            lambda: jwt.encode(
                {"iss": ISS, "aud": AUD, "sub": "x", "iat": 1, "exp": 2**31, "roles": ["admin"], "gt_workspaces": ["*"]},
                None,
                algorithm="none",
            ),
            401,
        ),
        (lambda: token(roles=[]), 403),
        (lambda: token(workspaces=["other-ws"]), 403),
        (lambda: "not.a.jwt", 401),
    ],
)
def test_rejected_tokens(oidc, tok, code):
    r = TestClient(app).get("/api/v1/whoami", headers=bearer(tok()))
    assert r.status_code == code, r.text


def test_hs256_key_confusion_rejected(oidc):
    """Classic RS256->HS256 confusion: HMAC-sign with the public key as secret. Built by hand (PyJWT refuses)."""
    import hashlib
    import hmac as _hmac

    pem = KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=")  # noqa: E731
    now = int(time.time())
    signing_input = (
        enc({"alg": "HS256", "typ": "JWT", "kid": "k1"})
        + b"."
        + enc({"iss": ISS, "aud": AUD, "sub": "x", "iat": now, "exp": now + 60, "roles": ["admin"], "gt_workspaces": ["*"]})
    )
    sig = base64.urlsafe_b64encode(_hmac.new(pem, signing_input, hashlib.sha256).digest()).rstrip(b"=")
    forged = (signing_input + b"." + sig).decode()
    assert TestClient(app).get("/api/v1/whoami", headers=bearer(forged)).status_code == 401


def test_missing_bearer_and_demo_header_ignored_in_oidc(oidc):
    c = TestClient(app)
    assert c.get("/api/v1/whoami").status_code == 401
    assert c.get("/api/v1/whoami", headers={"X-GT-Demo-Token": "test-demo-token"}).status_code == 401


def test_nested_roles_claim(oidc, monkeypatch):
    monkeypatch.setattr(get_settings(), "oidc_roles_claim", "realm_access.roles")
    t = token(roles=[], realm_access={"roles": ["approver"]})
    assert TestClient(app).get("/api/v1/whoami", headers=bearer(t)).json()["data"]["roles"] == ["approver"]


def test_permission_tiers(oidc):
    c = TestClient(app)
    viewer = bearer(token(roles=["viewer"]))
    assert c.post("/api/v1/scenarios/ghost_credential_a/reset", headers=viewer).status_code == 403
    assert c.post("/api/v1/investigations", headers=viewer, json={}).status_code == 403
    analyst = bearer(token(roles=["analyst"]))
    assert c.post("/api/v1/scenarios/ghost_credential_a/reset", headers=analyst).status_code == 403
    assert (
        c.post("/api/v1/investigations/inv_x/plans/plan_x/decision", headers=analyst, json={"decision": "approved"}).status_code
        == 403
    )


def test_production_refuses_demo_auth(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "env", "production")
    monkeypatch.setattr(s, "auth_mode", "demo_header")
    with pytest.raises(AuthConfigError):
        check_settings(s)
    r = TestClient(app).get("/api/v1/whoami", headers={"X-GT-Demo-Token": "test-demo-token"})
    assert r.status_code == 401 and "production requires" in r.json()["error"]["message"]
    monkeypatch.setattr(s, "auth_mode", "oidc")
    monkeypatch.setattr(s, "oidc_issuer", ISS)
    monkeypatch.setattr(s, "oidc_audience", AUD)
    monkeypatch.setattr(s, "oidc_jwks_url", "http://insecure.example/jwks")
    monkeypatch.setattr(s, "oidc_jwks_json", None)
    with pytest.raises(AuthConfigError, match="https"):
        check_settings(s)
    monkeypatch.setattr(s, "oidc_algorithms", "HS256")
    monkeypatch.setattr(s, "oidc_jwks_url", "https://idp.example/jwks")
    with pytest.raises(AuthConfigError, match="asymmetric"):
        check_settings(s)


def test_rate_limiter_shared_across_replicas():
    class FakeRedis:
        def __init__(self) -> None:
            self.store: dict[str, int] = {}

        def pipeline(self) -> Any:
            outer = self

            class P:
                def __init__(self) -> None:
                    self.ops: list[Any] = []

                def incrby(self, k: str, n: int) -> None:
                    self.ops.append((k, n))

                def expire(self, k: str, s: int) -> None:
                    pass

                def execute(self) -> list[int]:
                    k, n = self.ops[0]
                    outer.store[k] = outer.store.get(k, 0) + n
                    return [outer.store[k], True]

            return P()

    shared = FakeRedis()
    a, b = RateLimiter(3, shared), RateLimiter(3, shared)
    a.check("run:ws")
    b.check("run:ws")
    a.check("run:ws")
    with pytest.raises(HTTPException) as e:
        b.check("run:ws")  # the 4th call in this window, on another replica
    assert e.value.status_code == 429

    class Broken:
        def pipeline(self) -> Any:
            raise ConnectionError("down")

    local = RateLimiter(2, Broken())
    local.check("k")
    local.check("k")
    with pytest.raises(HTTPException):
        local.check("k")  # falls back to the in-process bucket


# ------------------------------------------------------------------ approval workflow + worker (FalkorDB)
@pytest.mark.integration
def test_approval_gates(oidc, falkor, ws):
    c = TestClient(app)
    admin = bearer(token(sub="admin@example.test", roles=["admin"]), ws)
    assert c.post("/api/v1/scenarios/ghost_credential_a/reset", headers=admin).status_code == 200
    alice = bearer(token(sub="alice@example.test", roles=["analyst", "approver"]), ws)
    bob = bearer(token(sub="bob@example.test", roles=["approver"]), ws)
    inv = c.post("/api/v1/investigations", headers=alice, json={}).json()["data"]
    assert inv["created_by"] == "alice@example.test"
    assert c.post(f"/api/v1/investigations/{inv['id']}/run?sync=true", headers=alice).status_code in (200, 202)
    plans = {p["k"]: p for p in c.get(f"/api/v1/investigations/{inv['id']}/containment", headers=bob).json()["data"]["plans"]}
    url = f"/api/v1/investigations/{inv['id']}/plans/{{}}/decision"
    # four-eyes: alice created the investigation
    r = c.post(url.format(plans[0]["plan_id"]), headers=alice, json={"decision": "approved"})
    assert r.status_code == 403 and "four-eyes" in r.text
    # k=1 contains a scrutiny-flagged action: acknowledgement is mandatory
    r = c.post(url.format(plans[1]["plan_id"]), headers=bob, json={"decision": "approved"})
    assert r.status_code == 409 and "scrutiny" in r.text
    r = c.post(
        url.format(plans[1]["plan_id"]),
        headers=bob,
        json={"decision": "approved", "acknowledge_scrutiny": True, "note": "checked shared-config logs"},
    )
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["verification"]["accepted"] and d["plan"]["mode"] == "approved" and "no executor" in d["plan"]["execution"]
    assert c.post(url.format(plans[1]["plan_id"]), headers=bob, json={"decision": "rejected"}).status_code == 409
    # a tampered certificate cannot be approved
    from app.graph import queries as Q
    from app.graph.repository import Repository

    repo = Repository(falkor, ws)
    art = repo.get_artifact("Certificate", plans[0]["certificate_id"])
    cert = art["payload"]["certificate"]
    cert["cost"]["total"] += 1
    repo.rw(
        Q.UPDATE_ARTIFACT["Certificate"],
        {
            "id": plans[0]["certificate_id"],
            "props": {"payload": json.dumps({"certificate": cert, "export": art["payload"]["export"]})},
        },
    )
    r = c.post(url.format(plans[0]["plan_id"]), headers=bob, json={"decision": "approved"})
    assert r.status_code == 409 and "verifier rejected" in r.text
    audit = c.get(f"/api/v1/audit/{inv['id']}", headers=bob).json()["data"]
    assert any(a["action"] == "plan.approved" and a["actor"] == "bob@example.test" for a in audit)


@pytest.mark.integration
def test_queue_mode_worker(monkeypatch, falkor, ws):
    from app.graph.repository import Repository
    from app.ingestion.seed import seed
    from app.orchestration.orchestrator import Orchestrator
    from app.worker import Worker

    monkeypatch.setattr(get_settings(), "run_mode", "queue")
    seed(falkor, ws, "ghost_credential_a")
    c = TestClient(app)
    h = {"X-GT-Demo-Token": get_settings().demo_token, "X-GT-Workspace": ws}
    inv = c.post("/api/v1/investigations", headers=h, json={}).json()["data"]
    r = c.post(f"/api/v1/investigations/{inv['id']}/run", headers=h).json()["data"]
    assert r["investigation"]["status"] == "queued"
    repo = Repository(falkor, ws)
    # only one of two competing workers can claim it
    assert Orchestrator(repo, worker_id="w1").claim(inv["id"]) is True
    assert Orchestrator(repo, worker_id="w2").claim(inv["id"]) is False
    repo.rw("MATCH (i:Investigation {id: $id}) WHERE i.workspace_id = $ws SET i.status = 'queued'", {"id": inv["id"]})
    ran = Worker(worker_id="w-test").tick()
    assert inv["id"] in ran
    assert Orchestrator(repo).get(inv["id"])["status"] == "completed"
