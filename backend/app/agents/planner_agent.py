"""C. Containment planner — drives the deterministic CEGAR solver. The model only explains results."""

from __future__ import annotations

import hashlib
from typing import Any

from app.agents.llm import Explanation, Provider
from app.agents.schemas import PlannerInput, PlannerOutput
from app.agents.tools import ToolBox
from app.model import TrustPolicy
from app.planner import engine


def artifact_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}_" + hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:14]


class ContainmentPlanner:
    agent_type = "containment_planner"

    def run(self, inp: PlannerInput, tb: ToolBox, llm: Provider, alerted_identity: str) -> tuple[PlannerOutput, dict[str, Any]]:
        results = tb.call("compute_pareto", T=inp.T, tau=inp.tau, K=inp.K, policy=inp.policy)
        pts = engine.pareto_points(results)
        plans: list[dict[str, Any]] = []
        certs: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        for r in results:
            plan_id = artifact_id("plan", inp.investigation_id, inp.T, inp.tau, inp.policy, r.k)
            plan = {"plan_id": plan_id, "k": r.k, "status": r.status, "actions": [a.to_dict() | {"mode": "proposed"}
                                                                               for a in r.actions],
                    "total": r.total if r.status == "contained" else None, "optimality": r.optimality,
                    "iterations": r.iterations, "constraints": len(r.constraints), "nogoods": [sorted(n) for n in r.nogoods],
                    "infeasible_reason": r.infeasible_reason, "elapsed_ms": round(r.elapsed_ms, 2),
                    "policy": inp.policy, "T": inp.T, "tau": inp.tau}
            if r.status == "contained":
                cert, lines = tb.call("compute_certificate", T=inp.T, tau=inp.tau, policy=inp.policy, k=r.k)
                plan["certificate_id"] = cert["certificate_id"]
                certs.append((cert, lines))
            plans.append(plan)
        b0_cert, b0_lines = tb.call("simulate_intervention", T=inp.T, tau=inp.tau, policy=inp.policy,
                                    action_ids=[f"disable_identity:{alerted_identity}"])
        certs.append((b0_cert, b0_lines))
        sens = tb.call("evidence_sensitivity", T=inp.T, tau=inp.tau, K=inp.K)
        expl, usage = llm.complete("plan_explanation", {"pareto": pts}, [], Explanation)
        assert isinstance(expl, Explanation)
        out = PlannerOutput(
            plan_ids=[p["plan_id"] for p in plans], certificate_ids=[c["certificate_id"] for c, _ in certs],
            pareto=pts, sensitivity=sens,
            baseline_b0={"label": "B0: disable the alerted account only", "certificate_id": b0_cert["certificate_id"],
                         "status": b0_cert["status"], "residual_confirmed_paths": b0_cert["residual_confirmed_paths"]},
            explanation=expl.summary,
        )
        return out, {"plans": plans, "certificates": certs, "usage": usage.__dict__,
                     "policy": TrustPolicy(inp.policy).value}
