"""Tests for Graph Copilot and Chat API."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app

TOKEN = os.environ.get("GT_DEMO_TOKEN", "dev-demo-token")
H = {"X-GT-Demo-Token": TOKEN}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_chat_providers(client: TestClient) -> None:
    r = client.get("/api/v1/chat/providers", headers=H)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["default_provider"] == "mock"
    assert len(data["providers"]) >= 3
    ids = [p["id"] for p in data["providers"]]
    assert "mock" in ids
    assert "openai_compatible" in ids
    assert "anthropic" in ids


def test_chat_requires_auth(client: TestClient) -> None:
    r = client.post("/api/v1/chat", json={"message": "hello"})
    assert r.status_code == 401


def test_chat_direct_cypher_read_only(client: TestClient) -> None:
    r = client.post(
        "/api/v1/chat",
        headers=H,
        json={"message": "MATCH (n) RETURN count(n) AS cnt", "provider": "mock"},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert "FalkorDB Cypher Results" in data["reply"]
    assert data["provider_used"] == "falkordb-direct"
    assert "cnt" in data["reply"] or "col_1" in data["reply"]


def test_chat_disallows_destructive_cypher(client: TestClient) -> None:
    r = client.post(
        "/api/v1/chat",
        headers=H,
        json={"message": "MATCH (n) DELETE n", "provider": "mock"},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    # Should not execute delete as direct Cypher
    assert data["provider_used"] != "falkordb-direct"


def test_chat_baseline_reasoning(client: TestClient) -> None:
    r = client.post(
        "/api/v1/chat",
        headers=H,
        json={"message": "Why did disabling Alice fail in baseline B0?", "provider": "mock"},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert "Baseline B0" in data["reply"]
    assert any(e["id"] == "id:ci-runner" for e in data["cited_entities"])
    assert len(data["cypher_queries"]) > 0


def test_chat_company_brain_reasoning(client: TestClient) -> None:
    r = client.post(
        "/api/v1/chat",
        headers=H,
        json={"message": "Who owned svc:payments-api at incident time vs now?", "provider": "mock"},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert "Bitemporal Company Brain" in data["reply"]
    assert "team:payments" in data["reply"]
    assert any(e["id"] == "svc:payments-api" for e in data["cited_entities"])


def test_chat_pareto_reasoning(client: TestClient) -> None:
    r = client.post(
        "/api/v1/chat",
        headers=H,
        json={"message": "Show me the Pareto containment frontier", "provider": "mock"},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert "Pareto" in data["reply"]
    assert "k = 0" in data["reply"]
    assert "k = 1" in data["reply"]
    assert "k = 2" in data["reply"]
    assert "laya_telemetry" in data
    assert data["laya_telemetry"]["domain"] == "pareto_containment"


def test_laya_status(client: TestClient) -> None:
    r = client.get("/api/v1/laya/status", headers=H)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["available"] is True
    assert len(data["capabilities"]) > 0


def test_laya_triage(client: TestClient) -> None:
    r = client.post(
        "/api/v1/laya/triage",
        headers=H,
        json={"title": "Anomalous CI token push", "description": "Compromised laptop with cached CI token"},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert "category" in data
    assert "suggested_k" in data
    assert data["suggested_k"] in (0, 1, 2)


def test_laya_evidence_check(client: TestClient) -> None:
    r = client.post(
        "/api/v1/laya/evidence-check",
        headers=H,
        json={"record_summary": "Workstation audit log", "claim_text": "Token id:ci-runner has been rotated and revoked"},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert "is_tampered_claim" in data
    assert "tampering_probability" in data


def test_laya_scrutiny(client: TestClient) -> None:
    r = client.post(
        "/api/v1/laya/scrutiny",
        headers=H,
        json={"action_id": "isolate_workload:workload:dev-box", "context": "Developer laptop with cached token"},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["scrutiny_level"] in ("safe", "review_required", "high_disruption")

