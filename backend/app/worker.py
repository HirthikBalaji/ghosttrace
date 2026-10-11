"""Investigation worker (GT_RUN_MODE=queue). Run any number of replicas: `python -m app.worker`.

Claims queued investigations with an atomic compare-and-set on the Investigation node, runs the durable
orchestrator (whose per-stage leases already prevent two workers from overwriting a result), and periodically
resumes investigations whose worker died mid-run. Stops cleanly on SIGTERM/SIGINT between stages.
"""

from __future__ import annotations

import logging
import signal
import threading
import uuid

from app.audit.logging import configure
from app.config import get_settings
from app.graph import queries as Q
from app.graph.client import get_client
from app.graph.repository import Repository
from app.orchestration.orchestrator import Orchestrator, resume_stale

log = logging.getLogger("ghosttrace.worker")


class Worker:
    def __init__(self, poll_s: float = 1.0, worker_id: str | None = None):
        self.poll_s = poll_s
        self.id = worker_id or f"worker_{uuid.uuid4().hex[:8]}"
        self.stop = threading.Event()

    def tick(self) -> list[str]:
        """One scheduling pass over every workspace; returns the investigations this worker ran."""
        ran: list[str] = []
        c = get_client()
        for ws in c.list_workspaces():
            repo = Repository(c, ws)
            for (inv_id,) in repo.ro(Q.QUEUED_INVESTIGATIONS, {"limit": 10}):
                if self.stop.is_set():
                    return ran
                o = Orchestrator(repo, worker_id=self.id)
                if o.claim(inv_id):
                    log.info(f"claimed {ws}/{inv_id}")
                    o.run(inv_id)
                    ran.append(inv_id)
        return ran

    def loop(self) -> None:
        n = 0
        while not self.stop.is_set():
            try:
                self.tick()
                n += 1
                if n % 30 == 0:
                    c = get_client()
                    for ws in c.list_workspaces():
                        resume_stale(Repository(c, ws))
            except Exception as exc:  # keep the worker alive; failures are persisted on the tasks themselves
                log.error(f"worker pass failed: {type(exc).__name__}")
            self.stop.wait(self.poll_s)


def main() -> None:
    configure(get_settings().log_level)
    w = Worker()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: w.stop.set())
    log.info(f"{w.id} started")
    w.loop()
    log.info(f"{w.id} stopped")


if __name__ == "__main__":
    main()
