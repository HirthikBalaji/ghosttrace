"""Apply pending schema migrations to every workspace graph: `python -m app.migrate` (also run at API startup)."""

from __future__ import annotations

import logging

from app.graph.client import GraphClient, get_client
from app.graph.schema import migrate

log = logging.getLogger("ghosttrace.migrate")


def migrate_all(client: GraphClient | None = None) -> dict[str, list[int]]:
    c = client or get_client()
    applied = {}
    for ws in c.list_workspaces():
        done = migrate(c, ws)
        if done:
            applied[ws] = done
            log.info(f"migrated {ws}: {done}")
    return applied


if __name__ == "__main__":
    from app.audit.logging import configure
    from app.config import get_settings

    configure(get_settings().log_level)
    print(migrate_all())
