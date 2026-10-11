from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

os.environ.setdefault("GT_DEMO_TOKEN", "test-demo-token")
os.environ.setdefault("GT_ENV", "test")

from app.graph.client import GraphClient, set_client  # noqa: E402
from app.ingestion.scenario import load, read_scenario, world_from  # noqa: E402
from app.planner.engine import World  # noqa: E402

FALKOR_HOST = os.environ.get("GT_FALKORDB_HOST", "localhost")
FALKOR_PORT = int(os.environ.get("GT_FALKORDB_PORT", "6379"))


def write_export(tmp: Path, lines: list[dict]) -> str:
    p = tmp / f"edges-{uuid.uuid4().hex[:6]}.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return str(p)


@pytest.fixture(scope="session")
def world_a() -> World:
    led, meta = load(read_scenario("ghost_credential_a"), "unit")
    return world_from(led, meta)


@pytest.fixture(scope="session")
def world_b() -> World:
    led, meta = load(read_scenario("ghost_credential_b"), "unit")
    return world_from(led, meta)


@pytest.fixture(scope="session")
def falkor() -> Iterator[GraphClient]:
    c = GraphClient(host=FALKOR_HOST, port=FALKOR_PORT, timeout_ms=5000)
    if not c.ping():
        pytest.skip("FalkorDB not reachable (integration tests need GT_FALKORDB_HOST/PORT)")
    # Integration tests create and delete many graphs. Never run them against a persistent (AOF) instance that holds
    # real data; set GT_TESTS_ALLOW_PERSISTENT=1 only for a disposable one.
    if os.environ.get("GT_TESTS_ALLOW_PERSISTENT") != "1":
        try:
            aof = c.db.connection.config_get("appendonly").get("appendonly")
        except Exception:
            aof = "unknown"
        if aof == "yes":
            pytest.exit("refusing to run integration tests against a FalkorDB with AOF persistence enabled", returncode=2)
    set_client(c)
    yield c
    set_client(None)


@pytest.fixture()
def ws(falkor: GraphClient) -> Iterator[str]:
    wid = f"t-{uuid.uuid4().hex[:10]}"
    yield wid
    falkor.drop_workspace(wid)
