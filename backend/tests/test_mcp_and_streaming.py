"""Read-only MCP server (stdio JSON-RPC) and server-sent progress events."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.graph.client import GraphClient
from app.graph.repository import Repository
from app.ingestion.seed import seed
from app.main import app
from app.mcp_server import GhostTraceMCP
from app.orchestration.orchestrator import Orchestrator

pytestmark = pytest.mark.integration
BACKEND = Path(__file__).resolve().parents[1]


def call(s: GhostTraceMCP, name: str, args: dict) -> dict:
    return s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})["result"]


def test_mcp_tools_are_readonly_and_validated(falkor: GraphClient, ws: str):
    seed(falkor, ws, "ghost_credential_a")
    s = GhostTraceMCP(ws)
    init = s.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})["result"]
    assert init["capabilities"] == {"tools": {"listChanged": False}}
    tools = s.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
    assert {t["name"] for t in tools} >= {"find_attack_paths", "get_service_owners", "get_price_of_certainty"}
    assert all(t["annotations"]["readOnlyHint"] for t in tools)
    before = falkor.ro(ws, "MATCH (n) RETURN count(n)")[0][0]
    r = call(s, "find_attack_paths", {})
    data = json.loads(r["content"][0]["text"])
    assert not r["isError"] and any(p["path_class"] == "CONFIRMED" for p in data["paths"])
    own = json.loads(
        call(
            s,
            "get_service_owners",
            {"service_id": "svc:payments-api", "T": "2026-03-02T09:00:00Z", "tau": "2026-03-02T09:00:00Z"},
        )["content"][0]["text"]
    )
    assert own["primary"][0]["team_id"] == "team:payments"
    pts = json.loads(call(s, "get_price_of_certainty", {"K": 2})["content"][0]["text"])
    assert [p["total_cost"] for p in pts] == [3, 10, 14]
    # validation: no Cypher, no unknown args, no naive timestamps
    assert call(s, "get_service_owners", {"service_id": "x'}) DETACH DELETE n //"})["isError"]
    assert call(s, "find_attack_paths", {"cypher": "MATCH (n) DELETE n"})["isError"]
    assert call(s, "find_attack_paths", {"T": "2026-03-02T09:00:00"})["isError"]
    unknown = s.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "run_cypher", "arguments": {}}})
    assert unknown["error"]["code"] == -32602
    assert falkor.ro(ws, "MATCH (n) RETURN count(n)")[0][0] == before


def test_mcp_stdio_roundtrip(falkor: GraphClient, ws: str):
    seed(falkor, ws, "ghost_credential_a")
    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_price_of_certainty", "arguments": {"K": 1}}},
    ]
    env = os.environ | {"GT_MCP_WORKSPACE": ws, "PYTHONPATH": f"{BACKEND}:{BACKEND.parent}"}
    out = subprocess.run(
        [sys.executable, "-m", "app.mcp_server"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        input="\n".join(json.dumps(r) for r in reqs) + "\nnot json\n",
        timeout=60,
        check=True,
    ).stdout
    resp = [json.loads(x) for x in out.splitlines()]
    assert [r.get("id") for r in resp] == [1, 2, 3, None]  # notification gets no reply; parse error reported
    assert json.loads(resp[2]["result"]["content"][0]["text"])[0]["total_cost"] == 3
    assert resp[3]["error"]["code"] == -32700


def test_progress_events_stream(falkor: GraphClient, ws: str):
    seed(falkor, ws, "ghost_credential_a")
    repo = Repository(falkor, ws)
    o = Orchestrator(repo)
    inv = o.create_investigation()
    o.run(inv["id"])
    with (
        TestClient(app) as c,
        c.stream(
            "GET",
            f"/api/v1/investigations/{inv['id']}/events",
            headers={"X-GT-Demo-Token": "test-demo-token", "X-GT-Workspace": ws},
        ) as r,
    ):
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    assert "event: progress" in body and "event: done" in body and '"completed"' in body
