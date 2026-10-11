"""Counterexample-guided containment synthesis (§3.8).

Master: exact branch-and-bound over a hitting-set formulation — choose A minimising
    J(A) = sum c_op(a) + sum_{soft f broken by A} w_f
subject to "hit every known counterexample path" constraints and learned nogoods. J is monotone in A
(more removals never repair a flow), so J of a partial assignment is a valid lower bound.

Subproblem: apply kappa(A) as an overlay (removed edge-id set; the graph is never mutated) and run the
exhaustive 0-1 BFS. A surviving path with <= k non-confirmed edges becomes a new constraint. A broken
hard flow yields a nogood minimised by deletion (flow breakage is monotone in A).

`proven_optimal` is reported only when the master was solved exactly over the declared candidate set
and the subproblem exhaustively found no surviving path of the required class.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.model import Flow, SnapEdge
from app.reasoning.kappa import Action
from app.reasoning.paths import INF, reachable, reopening_distance


@dataclass
class Budgets:
    max_iterations: int = 200
    timeout_s: float = 20.0
    max_master_nodes: int = 200_000


@dataclass
class Constraint:
    path: tuple[str, ...]  # edge ids of a counterexample path
    has_false_flag: bool = False


@dataclass
class PlanResult:
    k: int
    status: str  # contained | infeasible | budget_exhausted
    actions: list[Action]
    removed: frozenset[str]
    d: float
    witness: list[SnapEdge]
    cost_operational: int
    soft_penalty: int
    flows: dict[str, bool]
    optimality: str  # proven_optimal | bounded | heuristic
    lower_bound: int | None
    gap: int | None
    iterations: int
    constraints: list[Constraint] = field(default_factory=list)
    nogoods: list[frozenset[str]] = field(default_factory=list)
    search_space: str = ""
    infeasible_reason: str | None = None
    elapsed_ms: float = 0.0

    @property
    def total(self) -> int:
        return self.cost_operational + self.soft_penalty

    def summary(self) -> dict[str, Any]:
        return {
            "k": self.k, "status": self.status, "actions": [a.id for a in self.actions],
            "total": self.total if self.status == "contained" else None, "d": None if self.d == INF else self.d,
            "optimality": self.optimality, "iterations": self.iterations,
        }


class FlowEvaluator:
    """Caches flow reachability per removed-edge set."""

    def __init__(self, edges: list[SnapEdge], flows: Sequence[Flow]):
        self.edges = edges
        self.flows = list(flows)
        self._cache: dict[frozenset[str], dict[str, bool]] = {}

    def state(self, removed: frozenset[str]) -> dict[str, bool]:
        if removed not in self._cache:
            self._cache[removed] = {f.flow_id: reachable(self.edges, removed, f.u, f.v) for f in self.flows}
        return self._cache[removed]

    def penalty(self, removed: frozenset[str]) -> int:
        st = self.state(removed)
        return sum(f.weight for f in self.flows if f.kind == "soft" and not st[f.flow_id])

    def hard_ok(self, removed: frozenset[str]) -> bool:
        st = self.state(removed)
        return all(st[f.flow_id] for f in self.flows if f.kind == "hard")


def _removed(actions: Sequence[Action]) -> frozenset[str]:
    out: set[str] = set()
    for a in actions:
        out |= a.removes
    return frozenset(out)


class _Master:
    def __init__(self, cands: list[Action], fe: FlowEvaluator, budgets: Budgets, deadline: float):
        self.cands = cands
        self.fe = fe
        self.budgets = budgets
        self.deadline = deadline
        self.nodes = 0
        self.truncated = False

    def J(self, idx: frozenset[int]) -> int:
        acts = [self.cands[i] for i in idx]
        return sum(a.cost for a in acts) + self.fe.penalty(_removed(acts))

    def solve(self, cutsets: list[frozenset[int]], nogoods: list[frozenset[int]]) -> frozenset[int] | None:
        best: list[Any] = [None, None]  # (J, set)

        def rec(chosen: frozenset[int], excluded: frozenset[int]) -> None:
            self.nodes += 1
            if self.nodes > self.budgets.max_master_nodes or time.monotonic() > self.deadline:
                self.truncated = True
                return
            if any(ng <= chosen for ng in nogoods):
                return
            j = self.J(chosen)
            if best[0] is not None and j >= best[0]:
                return
            open_ = [c - excluded for c in cutsets if not (c & chosen)]
            if not open_:
                best[0], best[1] = j, chosen
                return
            branch = min(open_, key=lambda c: (len(c), sorted(c)))
            tried: set[int] = set()
            for i in sorted(branch, key=lambda i: (self.cands[i].cost, self.cands[i].id)):
                rec(chosen | {i}, excluded | frozenset(tried))
                tried.add(i)

        rec(frozenset(), frozenset())
        return best[1]


def solve(edges: list[SnapEdge], sources: Sequence[str], targets: Sequence[str], flows: Sequence[Flow],
          candidates: list[Action], k: int, budgets: Budgets | None = None,
          warm_constraints: Sequence[Constraint] = (), warm_nogoods: Sequence[frozenset[str]] = (),
          false_flag_edges: frozenset[str] = frozenset()) -> PlanResult:
    budgets = budgets or Budgets()
    t0 = time.monotonic()
    deadline = t0 + budgets.timeout_s
    fe = FlowEvaluator(edges, flows)
    cand_index = {a.id: i for i, a in enumerate(candidates)}
    edge_ids = {e.edge_id for e in edges}
    master = _Master(candidates, fe, budgets, deadline)
    space = f"all subsets of {len(candidates)} deterministic candidate actions on the relevant subgraph"

    constraints: list[Constraint] = []
    cutsets: list[frozenset[int]] = []

    def add_constraint(path: tuple[str, ...]) -> frozenset[int]:
        cut = frozenset(i for i, a in enumerate(candidates) if a.removes & set(path))
        constraints.append(Constraint(path, bool(false_flag_edges & set(path))))
        cutsets.append(cut)
        return cut

    # Warm start: re-validate prior constraints and nogoods against the new snapshot.
    for c in warm_constraints:
        if set(c.path) <= edge_ids:
            add_constraint(c.path)
    nogoods: list[frozenset[int]] = []
    for ng in warm_nogoods:
        if ng <= set(cand_index):
            idx = frozenset(cand_index[a] for a in ng)
            if not fe.hard_ok(_removed([candidates[i] for i in idx])):
                nogoods.append(idx)

    def result(status: str, chosen: frozenset[int] | None, optimality: str, it: int, lb: int | None,
               reason: str | None = None) -> PlanResult:
        acts = sorted((candidates[i] for i in (chosen or frozenset())), key=lambda a: a.id)
        rem = _removed(acts)
        d, wit = reopening_distance(edges, rem, sources, targets)
        op = sum(a.cost for a in acts)
        pen = fe.penalty(rem)
        gap = (op + pen - lb) if (lb is not None and status == "contained") else None
        return PlanResult(
            k=k, status=status, actions=acts, removed=rem, d=d, witness=wit, cost_operational=op,
            soft_penalty=pen, flows=fe.state(rem), optimality=optimality, lower_bound=lb, gap=gap,
            iterations=it, constraints=constraints, nogoods=[frozenset(candidates[i].id for i in ng) for ng in nogoods],
            search_space=space, infeasible_reason=reason, elapsed_ms=(time.monotonic() - t0) * 1000,
        )

    lb: int | None = None
    for it in range(1, budgets.max_iterations + 1):
        chosen = master.solve(cutsets, nogoods)
        if master.truncated:
            return _fallback(edges, sources, targets, fe, candidates, k, constraints, nogoods, lb, it, space, t0)
        if chosen is None:
            return result("infeasible", None, "proven_optimal", it, lb,
                          "no subset of the candidate actions satisfies all constraints and hard flows")
        lb = master.J(chosen)
        acts = [candidates[i] for i in chosen]
        rem = _removed(acts)
        if not fe.hard_ok(rem):
            nogoods.append(_minimise_nogood(chosen, candidates, fe))
            continue
        d, wit = reopening_distance(edges, rem, sources, targets)
        if d <= k:
            cut = add_constraint(tuple(e.edge_id for e in wit))
            if not cut:
                return result("infeasible", None, "proven_optimal", it, lb,
                              f"surviving path {[e.edge_id for e in wit]} has no candidate cutter")
            continue
        return result("contained", chosen, "proven_optimal", it, lb)
    return _fallback(edges, sources, targets, fe, candidates, k, constraints, nogoods, lb,
                     budgets.max_iterations, space, t0)


def _minimise_nogood(chosen: frozenset[int], candidates: list[Action], fe: FlowEvaluator) -> frozenset[int]:
    core = set(chosen)
    for i in sorted(chosen):
        trial = core - {i}
        if not fe.hard_ok(_removed([candidates[j] for j in trial])):
            core = trial
    return frozenset(core)


def _fallback(edges: list[SnapEdge], sources: Sequence[str], targets: Sequence[str], fe: FlowEvaluator,
              candidates: list[Action], k: int, constraints: list[Constraint], nogoods: list[frozenset[int]],
              lb: int | None, it: int, space: str, t0: float) -> PlanResult:
    """Budget exhausted: greedy anytime repair. Reported as bounded (with gap) or heuristic, never optimal."""
    chosen: list[Action] = []
    for _ in range(len(candidates)):
        rem = _removed(chosen)
        d, wit = reopening_distance(edges, rem, sources, targets)
        if d > k:
            break
        path = {e.edge_id for e in wit}
        opts = [a for a in candidates if a not in chosen and a.removes & path
                and fe.hard_ok(_removed([*chosen, a]))]
        if not opts:
            chosen = []
            break
        chosen.append(min(opts, key=lambda a: (a.cost + fe.penalty(_removed([*chosen, a])), a.id)))
    rem = _removed(chosen)
    d, wit = reopening_distance(edges, rem, sources, targets)
    ok = bool(chosen) and d > k and fe.hard_ok(rem)
    op = sum(a.cost for a in chosen)
    pen = fe.penalty(rem)
    status = "contained" if ok else "budget_exhausted"
    opt = "bounded" if (ok and lb is not None) else "heuristic"
    return PlanResult(
        k=k, status=status, actions=sorted(chosen, key=lambda a: a.id) if ok else [], removed=rem if ok else frozenset(),
        d=d, witness=wit, cost_operational=op if ok else 0, soft_penalty=pen if ok else 0, flows=fe.state(rem),
        optimality=opt, lower_bound=lb, gap=(op + pen - lb) if (ok and lb is not None) else None, iterations=it,
        constraints=constraints, nogoods=[frozenset(candidates[i].id for i in ng) for ng in nogoods],
        search_space=space, infeasible_reason=None if ok else "budget exhausted without a feasible plan",
        elapsed_ms=(time.monotonic() - t0) * 1000,
    )


def evaluate_plan(edges: list[SnapEdge], sources: Sequence[str], targets: Sequence[str], flows: Sequence[Flow],
                  actions: list[Action]) -> PlanResult:
    """Evaluate a given (e.g. user-selected or baseline) action set without optimising."""
    fe = FlowEvaluator(edges, flows)
    rem = _removed(actions)
    d, wit = reopening_distance(edges, rem, sources, targets)
    status = "contained" if d > 0 and fe.hard_ok(rem) else "not_contained"
    return PlanResult(
        k=max(int(d) - 1, 0) if d != INF else 0, status=status, actions=sorted(actions, key=lambda a: a.id),
        removed=rem, d=d, witness=wit, cost_operational=sum(a.cost for a in actions), soft_penalty=fe.penalty(rem),
        flows=fe.state(rem), optimality="heuristic", lower_bound=None, gap=None, iterations=0,
        search_space="user/baseline-selected action set; no optimality claim",
    )
