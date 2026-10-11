"""Path analysis over a snapshot (pure-Python reference implementation, §3.4 / §3.7).

The final soundness verdict always uses these exhaustive searches (BFS / 0-1 BFS), independent of the
depth bound used by Cypher enumeration.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.model import TRAVERSAL_EDGE_TYPES, SnapEdge

INF = float("inf")


@dataclass(frozen=True)
class PathInfo:
    edge_ids: tuple[str, ...]
    nodes: tuple[str, ...]
    path_class: str  # CONFIRMED | CONDITIONAL(k) | TEMPORALLY_UNCERTAIN
    latent_count: int
    uncertain_count: int
    assumptions: tuple[str, ...]  # non-confirmed edge ids


def weight(e: SnapEdge) -> int:
    return 0 if e.confirmed else 1


def classify_path(edges: Sequence[SnapEdge]) -> PathInfo:
    latent = [e.edge_id for e in edges if e.cls == "LATENT"]
    uncertain = [e.edge_id for e in edges if e.temporal == "UNCERTAIN"]
    if uncertain:
        cls = "TEMPORALLY_UNCERTAIN"
    elif latent:
        cls = f"CONDITIONAL({len(latent)})"
    else:
        cls = "CONFIRMED"
    nodes = (edges[0].src, *(e.dst for e in edges)) if edges else ()
    assumptions = tuple(e.edge_id for e in edges if not e.confirmed)
    return PathInfo(tuple(e.edge_id for e in edges), nodes, cls, len(latent), len(uncertain), assumptions)


def _adj(
    edges: Iterable[SnapEdge], removed: frozenset[str] | set[str], confirmed_only: bool = False
) -> dict[str, list[SnapEdge]]:
    adj: dict[str, list[SnapEdge]] = {}
    for e in edges:
        if e.type not in TRAVERSAL_EDGE_TYPES or e.edge_id in removed:
            continue
        if confirmed_only and not e.confirmed:
            continue
        adj.setdefault(e.src, []).append(e)
    for lst in adj.values():
        lst.sort(key=lambda x: x.edge_id)
    return adj


def reopening_distance(
    edges: Iterable[SnapEdge], removed: frozenset[str] | set[str], sources: Iterable[str], targets: Iterable[str]
) -> tuple[float, list[SnapEdge]]:
    """0-1 BFS (weight 0 confirmed, 1 latent/uncertain). Returns (d, witness path edges)."""
    adj = _adj(edges, removed)
    srcs = sorted(set(sources))
    tgts = set(targets)
    dist: dict[str, float] = {s: 0 for s in srcs}
    pred: dict[str, SnapEdge] = {}
    dq: deque[str] = deque(srcs)
    while dq:
        u = dq.popleft()
        for e in adj.get(u, []):
            nd = dist[u] + weight(e)
            if nd < dist.get(e.dst, INF):
                dist[e.dst] = nd
                pred[e.dst] = e
                (dq.appendleft if weight(e) == 0 else dq.append)(e.dst)
    best_t = min((t for t in tgts if t in dist), key=lambda t: (dist[t], t), default=None)
    if best_t is None:
        return INF, []
    path: list[SnapEdge] = []
    cur = best_t
    src_set = set(srcs)
    while cur not in src_set:
        e = pred[cur]
        path.append(e)
        cur = e.src
    path.reverse()
    return dist[best_t], path


def reachable(edges: Iterable[SnapEdge], removed: frozenset[str] | set[str], u: str, v: str, confirmed_only: bool = True) -> bool:
    adj = _adj(edges, removed, confirmed_only)
    seen, stack = {u}, [u]
    while stack:
        x = stack.pop()
        if x == v:
            return True
        for e in adj.get(x, []):
            if e.dst not in seen:
                seen.add(e.dst)
                stack.append(e.dst)
    return False


def forward_set(edges: Iterable[SnapEdge], removed: frozenset[str] | set[str], starts: Iterable[str]) -> set[str]:
    adj = _adj(edges, removed)
    seen = set(starts)
    stack = list(seen)
    while stack:
        x = stack.pop()
        for e in adj.get(x, []):
            if e.dst not in seen:
                seen.add(e.dst)
                stack.append(e.dst)
    return seen


def backward_set(edges: Iterable[SnapEdge], removed: frozenset[str] | set[str], ends: Iterable[str]) -> set[str]:
    radj: dict[str, list[str]] = {}
    for e in edges:
        if e.type in TRAVERSAL_EDGE_TYPES and e.edge_id not in removed:
            radj.setdefault(e.dst, []).append(e.src)
    seen = set(ends)
    stack = list(seen)
    while stack:
        x = stack.pop()
        for y in radj.get(x, []):
            if y not in seen:
                seen.add(y)
                stack.append(y)
    return seen


def enumerate_paths(
    edges: Iterable[SnapEdge],
    removed: frozenset[str] | set[str],
    sources: Iterable[str],
    targets: Iterable[str],
    max_depth: int,
    max_paths: int,
) -> list[PathInfo]:
    """Bounded DFS over simple paths (reference for Cypher enumeration; not used for soundness)."""
    adj = _adj(edges, removed)
    tgts = set(targets)
    out: list[PathInfo] = []

    def dfs(node: str, path: list[SnapEdge], visited: set[str]) -> None:
        if len(out) >= max_paths:
            return
        if node in tgts and path:
            out.append(classify_path(path))
        if len(path) >= max_depth:
            return
        for e in adj.get(node, []):
            if e.dst not in visited:
                visited.add(e.dst)
                path.append(e)
                dfs(e.dst, path, visited)
                path.pop()
                visited.discard(e.dst)

    for s in sorted(set(sources)):
        dfs(s, [], {s})
    return out
