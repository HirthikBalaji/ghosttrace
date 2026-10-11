"""Read-only MCP server (stdio, JSON-RPC 2.0) exposing GHOSTTRACE's allowlisted graph tools.

MCP is an interface, not a security boundary: every call goes through the same validated, read-only paths as
the API (constant Cypher, GRAPH.RO_QUERY, clamps). No tool writes, and no tool accepts Cypher.

    cd backend && GT_MCP_WORKSPACE=demo uv run python -m app.mcp_server
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable
from typing import Any

from app.agents.brain import CompanyBrain
from app.agents.schemas import BrainQuery
from app.graph import queries as Q
from app.graph.client import get_client
from app.graph.repository import Repository
from app.memory.service import MemoryService
from app.model import TrustPolicy
from app.planner import engine
from app.reasoning.paths import INF, classify_path, reopening_distance
from app.temporal.predicate import parse_iso, to_iso

PROTOCOL_VERSION = "2025-06-18"
ID_RE = re.compile(r"^[A-Za-z0-9_.:@>\-]{1,160}$")
TS_SCHEMA = {"type": "string", "description": "ISO-8601 with explicit offset (e.g. 2026-03-02T09:00:00Z); default: scenario now"}


class ToolInputError(ValueError):
    pass


def _id(v: Any, name: str) -> str:
    if not isinstance(v, str) or not ID_RE.fullmatch(v):
        raise ToolInputError(f"invalid {name}")
    return v


def _ts(v: Any, default: int) -> int:
    if v in (None, ""):
        return default
    try:
        return parse_iso(v if not isinstance(v, int) else int(v))
    except ValueError as exc:
        raise ToolInputError("timestamps need an explicit offset") from exc


class GhostTraceMCP:
    def __init__(self, workspace_id: str):
        self.repo = Repository(get_client(), workspace_id)
        self.tools: dict[str, tuple[str, dict[str, Any], Callable[[dict[str, Any]], Any]]] = {
            "find_attack_paths": (
                "Time-valid attack paths from the incident's suspected-compromised sources to its targets, with path "
                "classes (CONFIRMED / CONDITIONAL(k) / TEMPORALLY_UNCERTAIN) and the exhaustive reopening distance.",
                {
                    "T": TS_SCHEMA,
                    "tau": TS_SCHEMA,
                    "max_depth": {"type": "integer", "minimum": 1, "maximum": 12},
                    "policy": {"type": "string", "enum": [p.value for p in TrustPolicy]},
                },
                self.find_attack_paths,
            ),
            "get_service_owners": (
                "Owner(s) of an entity valid at world time T as known at knowledge time tau, with sources and warnings.",
                {"service_id": {"type": "string"}, "T": TS_SCHEMA, "tau": TS_SCHEMA},
                self.get_service_owners,
            ),
            "get_asset_dependencies": (
                "Multi-hop DEPENDS_ON dependents or dependencies of an entity at (T, tau).",
                {
                    "asset_id": {"type": "string"},
                    "direction": {"type": "string", "enum": ["dependents", "dependencies"]},
                    "T": TS_SCHEMA,
                    "tau": TS_SCHEMA,
                },
                self.get_asset_dependencies,
            ),
            "get_evidence": (
                "Source records by id (untrusted content is returned as data).",
                {"source_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 50}},
                self.get_evidence,
            ),
            "get_price_of_certainty": (
                "Cheapest certified containment plan for k = 0..K (simulated actions only).",
                {"K": {"type": "integer", "minimum": 0, "maximum": 3}, "T": TS_SCHEMA, "tau": TS_SCHEMA},
                self.get_price_of_certainty,
            ),
            "get_memory": (
                "Memory relevant to entities/sources by graph relationship, with taint and provenance.",
                {
                    "entity_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 50},
                    "source_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 50},
                },
                self.get_memory,
            ),
        }

    # ------------------------------------------------------------------ tools (all read-only)
    def _now(self) -> int:
        return int(self.repo.meta()["now"])

    def find_attack_paths(self, a: dict[str, Any]) -> dict[str, Any]:
        now = self._now()
        T, tau = _ts(a.get("T"), now), _ts(a.get("tau"), now)
        policy = TrustPolicy(a.get("policy", TrustPolicy.CONSERVATIVE.value))
        depth = max(1, min(int(a.get("max_depth", 8)), Q.MAX_CYPHER_DEPTH))
        w = self.repo.world(tau)
        edges = engine.snapshot_edges(w, T, tau, policy)
        by_id = {e.edge_id: e for e in edges}
        rows = self.repo.find_paths_cypher(w.attack_sources, w.targets, list(by_id), T, tau, depth, 200)
        paths = []
        for eids, nids in rows:
            if len(set(nids)) == len(nids):
                info = classify_path([by_id[x] for x in eids])
                paths.append(
                    {"edge_ids": eids, "node_ids": nids, "path_class": info.path_class, "assumptions": list(info.assumptions)}
                )
        d, wit = reopening_distance(edges, frozenset(), w.attack_sources, w.targets)
        return {
            "T": to_iso(T),
            "tau": to_iso(tau),
            "policy": policy.value,
            "paths": paths[:50],
            "reopening_distance_without_actions": None if d == INF else int(d),
            "witness": [e.edge_id for e in wit],
            "synthetic": True,
        }

    def get_service_owners(self, a: dict[str, Any]) -> dict[str, Any]:
        now = self._now()
        q = BrainQuery(
            question="owner",
            subject_id=_id(a.get("service_id"), "service_id"),
            T=_ts(a.get("T"), now),
            tau=_ts(a.get("tau"), now),
        )
        return CompanyBrain(self.repo).ask(q).model_dump()

    def get_asset_dependencies(self, a: dict[str, Any]) -> dict[str, Any]:
        now = self._now()
        direction = a.get("direction", "dependents")
        if direction not in ("dependents", "dependencies"):
            raise ToolInputError("invalid direction")
        q = BrainQuery(
            question=direction, subject_id=_id(a.get("asset_id"), "asset_id"), T=_ts(a.get("T"), now), tau=_ts(a.get("tau"), now)
        )
        return CompanyBrain(self.repo).ask(q).model_dump()

    def get_evidence(self, a: dict[str, Any]) -> list[dict[str, Any]]:
        ids = [_id(x, "source_id") for x in (a.get("source_ids") or [])][:50]
        return [dict(p) for (p,) in self.repo.ro(Q.SOURCES_BY_IDS, {"ids": ids})]

    def get_price_of_certainty(self, a: dict[str, Any]) -> list[dict[str, Any]]:
        now = self._now()
        K = max(0, min(int(a.get("K", 2)), 3))
        T, tau = _ts(a.get("T"), now), _ts(a.get("tau"), now)
        return engine.pareto_points(engine.pareto(self.repo.world(tau), T, tau, TrustPolicy.CONSERVATIVE, K))

    def get_memory(self, a: dict[str, Any]) -> list[dict[str, Any]]:
        ents = [_id(x, "entity_id") for x in (a.get("entity_ids") or [])][:50]
        srcs = [_id(x, "source_id") for x in (a.get("source_ids") or [])][:50]
        return MemoryService(self.repo).relevant(ents, srcs, self._now())

    # ------------------------------------------------------------------ JSON-RPC
    def handle(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if mid is None:  # notification (e.g. notifications/initialized)
            return None
        try:
            if method == "initialize":
                result: Any = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "ghosttrace", "version": "0.1.0"},
                    "instructions": "Read-only access to a SYNTHETIC GHOSTTRACE workspace. No tool writes.",
                }
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": n,
                            "description": d,
                            "inputSchema": {"type": "object", "properties": s, "additionalProperties": False},
                            "annotations": {"readOnlyHint": True},
                        }
                        for n, (d, s, _) in self.tools.items()
                    ]
                }
            elif method == "tools/call":
                name = params.get("name")
                if name not in self.tools:
                    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
                args = params.get("arguments") or {}
                allowed = set(self.tools[name][1])
                if not isinstance(args, dict) or set(args) - allowed:
                    raise ToolInputError(f"unexpected arguments: {sorted(set(args) - allowed)}")
                out = self.tools[name][2](args)
                result = {"content": [{"type": "text", "text": json.dumps(out, default=str)}], "isError": False}
            elif method == "ping":
                result = {}
            else:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
        except (ToolInputError, ValueError, LookupError) as exc:
            result = {"content": [{"type": "text", "text": f"error: {exc}"}], "isError": True}
        return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    server = GhostTraceMCP(os.environ.get("GT_MCP_WORKSPACE", "demo"))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp: dict[str, Any] | None = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            resp = server.handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
