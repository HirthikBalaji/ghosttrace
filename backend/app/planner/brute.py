"""Brute-force subset enumerator. TEST ORACLE ONLY — never used by the production planner."""

from __future__ import annotations

import itertools
from collections.abc import Sequence

from app.model import Flow, SnapEdge
from app.planner.cegar import FlowEvaluator, _removed
from app.reasoning.kappa import Action
from app.reasoning.paths import reopening_distance

BRUTE_FORCE_LIMIT = 20


def brute_force(edges: list[SnapEdge], sources: Sequence[str], targets: Sequence[str], flows: Sequence[Flow],
                candidates: list[Action], k: int) -> tuple[int, list[str]] | None:
    if len(candidates) > BRUTE_FORCE_LIMIT:
        raise ValueError("brute force is limited to small instances")
    fe = FlowEvaluator(edges, flows)
    best: tuple[int, list[str]] | None = None
    for r in range(len(candidates) + 1):
        for combo in itertools.combinations(candidates, r):
            op = sum(a.cost for a in combo)
            if best is not None and op >= best[0]:
                continue
            rem = _removed(combo)
            d, _ = reopening_distance(edges, rem, sources, targets)
            if d <= k or not fe.hard_ok(rem):
                continue
            j = op + fe.penalty(rem)
            if best is None or j < best[0]:
                best = (j, sorted(a.id for a in combo))
    return best
