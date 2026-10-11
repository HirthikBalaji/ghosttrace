"""Container-restart recovery: investigation, tasks, handoffs and memory survive a FalkorDB container
restart (persistent volume + AOF), and a fresh orchestrator resumes the pipeline.

Runs only with GT_RUN_DOCKER_TESTS=1 (needs the docker CLI); uses its own container and volume.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid

import pytest

from app.graph.client import GraphClient
from app.graph.repository import Repository
from app.ingestion.seed import seed
from app.memory.service import MemoryService
from app.orchestration.orchestrator import STAGES, Orchestrator

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(
        os.environ.get("GT_RUN_DOCKER_TESTS") != "1" or not shutil.which("docker"),
        reason="set GT_RUN_DOCKER_TESTS=1 to run container-restart tests",
    ),
]
IMAGE = "falkordb/falkordb:v4.22.0"
PORT = 6391


def sh(*args: str) -> str:
    return subprocess.run(list(args), check=True, capture_output=True, text=True).stdout.strip()


def connect(timeout: float = 60) -> GraphClient:
    """The client connects in its constructor, so retry construction until the server accepts queries."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            c = GraphClient(port=PORT, timeout_ms=10000)
            if c.ping():
                c.list_workspaces()
                return c
        except Exception:
            pass
        time.sleep(0.5)
    raise TimeoutError("FalkorDB did not become ready")


@pytest.fixture()
def container():
    name, vol = f"gt-persist-{uuid.uuid4().hex[:6]}", f"gt-persist-vol-{uuid.uuid4().hex[:6]}"
    sh(
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "-p",
        f"127.0.0.1:{PORT}:6379",
        "-v",
        f"{vol}:/var/lib/falkordb/data",
        "-e",
        "REDIS_ARGS=--appendonly yes --appendfsync always",
        IMAGE,
    )
    try:
        yield name
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
        subprocess.run(["docker", "volume", "rm", vol], capture_output=True, check=False)


def test_state_survives_container_restart_and_resumes(container):
    c = connect()
    seed(c, "demo", "ghost_credential_a")
    repo = Repository(c, "demo")
    o1 = Orchestrator(repo, worker_id="before-restart", fail_after_stage="containment_planner")
    inv = o1.create_investigation()
    with pytest.raises(RuntimeError):
        o1.run(inv["id"])
    tasks_before = o1.tasks(inv["id"])
    handoffs_before = o1.handoffs(inv["id"])
    mem_before = {m["memory_id"] for m in MemoryService(repo).entries()}
    assert len(tasks_before) == 3 and len(handoffs_before) == 2

    sh("docker", "restart", container)  # backend state lives only in FalkorDB
    c2 = connect()
    repo2 = Repository(c2, "demo")
    o2 = Orchestrator(repo2, worker_id="after-restart")
    assert [t["task_id"] for t in o2.tasks(inv["id"])] == [t["task_id"] for t in tasks_before]
    assert o2.handoffs(inv["id"]) == handoffs_before
    assert mem_before <= {m["memory_id"] for m in MemoryService(repo2).entries()}
    res = o2.run(inv["id"])
    assert res["status"] == "completed"
    tasks = o2.tasks(inv["id"])
    assert [t["agent_type"] for t in tasks] == STAGES and all(t["attempt_count"] == 1 for t in tasks)
    assert any(m["investigation_id"] == inv["id"] for m in MemoryService(repo2).entries())
