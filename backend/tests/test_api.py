"""API: health/ready, auth (fail closed), envelopes, validation, isolation, docs parity, end-to-end demo."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

TOKEN = os.environ["GT_DEMO_TOKEN"]  # set by conftest, or by CI
H = {"X-GT-Demo-Token": TOKEN}
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_health_has_no_graph_dependency(client, monkeypatch):
    import app.main as m

    class Down:
        def ping(self):
            return False

        def list_workspaces(self):
            raise RuntimeError("down")

    monkeypatch.setattr(m, "get_client", lambda: Down())
    assert client.get("/health").json()["status"] == "ok"
    r = client.get("/ready")
    assert r.status_code == 503 and r.json()["status"] == "not_ready"
    assert "password" not in r.text.lower() and "6379" not in r.text


def test_auth_fails_closed(client, monkeypatch):
    assert client.get("/api/v1/scenarios").status_code == 401
    assert client.get("/api/v1/scenarios", headers={"X-GT-Demo-Token": "wrong"}).status_code == 401
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "demo_token", None)
    r = client.get("/api/v1/scenarios", headers=H)
    assert r.status_code == 401 and "failing closed" in r.json()["error"]["message"]


def test_security_headers_and_errors(client):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and "frame-ancestors" in r.headers["Content-Security-Policy"]
    r = client.get("/api/v1/scenarios", headers=H | {"X-GT-Workspace": "../../etc"})
    assert r.status_code == 400
    r = client.post(
        "/api/v1/investigations",
        headers=H,
        content=b"x" * (300 * 1024),
    )
    assert r.status_code == 413


def test_openapi_matches_docs(client):
    spec = client.get("/openapi.json").json()
    paths = set(spec["paths"])
    doc = (ROOT / "docs" / "api.md").read_text()
    documented = set(re.findall(r"`(?:GET|POST) (/[^`?\s]*)", doc))
    norm = lambda p: re.sub(r"\{[^}]+\}", "{}", p)  # noqa: E731
    assert {norm(p) for p in documented} == {norm(p) for p in paths}
    assert not any("cypher" in p.lower() or "query" in p.lower() for p in paths)


@pytest.mark.integration
def test_end_to_end_demo_flow(client, falkor, ws):
    h = H | {"X-GT-Workspace": ws}
    assert client.post("/api/v1/scenarios/ghost_credential_a/reset", headers=h).status_code == 200
    inv = client.post("/api/v1/investigations", headers=h, json={}).json()["data"]["id"]
    r = client.post(f"/api/v1/investigations/{inv}/run?sync=true", headers=h).json()
    assert r["data"]["investigation"]["status"] == "completed"
    g = client.get(f"/api/v1/investigations/{inv}/graph", headers=h).json()["data"]
    assert g["edges"] and all(e["cls"] in ("OBSERVED", "DERIVED", "LATENT") for e in g["edges"])
    g_then = client.get(
        f"/api/v1/investigations/{inv}/graph", headers=h, params={"T": "2026-03-02T09:00:00Z", "tau": "2026-03-02T09:00:00Z"}
    ).json()["data"]
    assert len(g_then["edges"]) < len(g["edges"])  # history changes with (T, tau)
    c = client.get(f"/api/v1/investigations/{inv}/containment", headers=h).json()["data"]
    cid = next(x["certificate_id"] for x in c["certificates"] if x["status"] == "contained")
    v = client.post(f"/api/v1/investigations/{inv}/certificate/{cid}/verify", headers=h).json()["data"]
    assert v["accepted"] and v["exit_code"] == 0 and "ACCEPTED" in v["output"]
    sim = client.post(
        f"/api/v1/investigations/{inv}/containment/simulate", headers=h, json={"action_ids": ["disable_identity:id:dev-alice"]}
    ).json()["data"]["certificate"]
    assert sim["status"] == "not_contained" and sim["mode"] == "simulated"
    bad = client.post(
        f"/api/v1/investigations/{inv}/containment/simulate", headers=h, json={"action_ids": ["MATCH (n) DELETE n"]}
    )
    assert bad.status_code == 422
    sens = client.get(f"/api/v1/investigations/{inv}/evidence-sensitivity", headers=h).json()["data"]
    assert any(s["differs"] for s in sens)
    lb = client.get(f"/api/v1/investigations/{inv}/evidence/load-bearing", headers=h).json()["data"]
    assert lb and lb[0]["load_bearing"]
    md = client.get(f"/api/v1/investigations/{inv}/report", headers=h, params={"format": "md"})
    assert md.status_code == 200 and "SYNTHETIC" in md.text
    o = client.get(
        "/api/v1/company/owners",
        headers=h,
        params={"service_id": "svc:payments-api", "asof_T": "2026-03-02T09:00:00Z", "known_tau": "2026-03-02T09:00:00Z"},
    ).json()["data"]
    assert o["primary"][0]["team_id"] == "team:payments" and o["source_ids"]
    assert (
        client.get(
            "/api/v1/company/owners", headers=h, params={"service_id": "svc:payments-api", "asof_T": "2026-03-02T09:00:00"}
        ).status_code
        == 422
    )
    assert client.get(f"/api/v1/audit/{inv}", headers=h).json()["data"]
    assert client.get("/api/v1/memory", headers=h).json()["data"]


@pytest.mark.integration
def test_cross_workspace_api_isolation(client, falkor):
    a, b = "t-api-a", "t-api-b"
    try:
        ha, hb = H | {"X-GT-Workspace": a}, H | {"X-GT-Workspace": b}
        client.post("/api/v1/scenarios/ghost_credential_a/reset", headers=ha)
        client.post("/api/v1/scenarios/ghost_credential_b/reset", headers=hb)
        inv = client.post("/api/v1/investigations", headers=ha, json={}).json()["data"]["id"]
        assert client.get(f"/api/v1/investigations/{inv}", headers=hb).status_code == 404
        assert client.get(f"/api/v1/audit/{inv}", headers=hb).status_code == 404
        assert client.get(f"/api/v1/investigations/{inv}", headers=ha).status_code == 200
    finally:
        falkor.drop_workspace(a)
        falkor.drop_workspace(b)
