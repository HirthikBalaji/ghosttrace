"""C. Containment planner — drives the deterministic CEGAR solver. The model only explains results."""

from __future__ import annotations

import hashlib
from typing import Any

from app.agents.llm import ContainmentProposals, Explanation, LLMError, Provider
from app.agents.schemas import PlannerInput, PlannerOutput
from app.agents.tools import ToolBox
from app.model import TrustPolicy
from app.planner import engine
from app.security.injection import wrap_untrusted


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
            plan = {
                "plan_id": plan_id,
                "k": r.k,
                "status": r.status,
                "actions": [a.to_dict() | {"mode": "proposed"} for a in r.actions],
                "total": r.total if r.status == "contained" else None,
                "optimality": r.optimality,
                "iterations": r.iterations,
                "constraints": len(r.constraints),
                "nogoods": [sorted(n) for n in r.nogoods],
                "infeasible_reason": r.infeasible_reason,
                "elapsed_ms": round(r.elapsed_ms, 2),
                "policy": inp.policy,
                "T": inp.T,
                "tau": inp.tau,
            }
            if r.status == "contained":
                cert, lines = tb.call("compute_certificate", T=inp.T, tau=inp.tau, policy=inp.policy, k=r.k)
                plan["certificate_id"] = cert["certificate_id"]
                certs.append((cert, lines))
            plans.append(plan)
        b0_cert, b0_lines = tb.call(
            "simulate_intervention", T=inp.T, tau=inp.tau, policy=inp.policy, action_ids=[f"disable_identity:{alerted_identity}"]
        )
        certs.append((b0_cert, b0_lines))
        sens = tb.call("evidence_sensitivity", T=inp.T, tau=inp.tau, K=inp.K)
        k0_total = next((p["total_cost"] for p in pts if p["k"] == 0 and p["feasible"]), None)
        advisor, adv_certs = self._advisor(inp, tb, llm, alerted_identity, k0_total)
        certs.extend(adv_certs)
        expl, usage = llm.complete("plan_explanation", {"pareto": pts}, [], Explanation)
        assert isinstance(expl, Explanation)
        out = PlannerOutput(
            plan_ids=[p["plan_id"] for p in plans],
            certificate_ids=[c["certificate_id"] for c, _ in certs],
            pareto=pts,
            sensitivity=sens,
            baseline_b0={
                "label": "B0: disable the alerted account only",
                "certificate_id": b0_cert["certificate_id"],
                "status": b0_cert["status"],
                "residual_confirmed_paths": b0_cert["residual_confirmed_paths"],
            },
            explanation=expl.summary,
            advisor=advisor,
        )
        return out, {"plans": plans, "certificates": certs, "usage": usage.__dict__, "policy": TrustPolicy(inp.policy).value}

    MAX_PROPOSALS = 5
    MAX_ACTIONS = 12

    def _advisor(
        self, inp: PlannerInput, tb: ToolBox, llm: Provider, alerted_identity: str, k0_total: int | None
    ) -> tuple[dict[str, Any], list[tuple[dict[str, Any], list[dict[str, Any]]]]]:
        """The model proposes containment plans; the deterministic engine simulates and certifies each one.

        A proposal is accepted only if its certificate says `contained` (no CONFIRMED path survives and every
        hard flow is preserved). Unknown action ids are rejected before simulation. Nothing is executed.
        """
        cands = tb.call("containment_candidates", T=inp.T, tau=inp.tau, policy=inp.policy)
        cand_ids = {c["id"] for c in cands}
        snap = tb.call("get_snapshot_edges", T=inp.T, tau=inp.tau, policy=inp.policy)
        implicated = sorted({e.src for e in snap if "possible_false_flag" in e.flags and e.src_type in ("Service", "Host")})
        ctx = tb.call("get_incident_context", incident_id=None)
        structured = {
            "alerted_identity": alerted_identity,
            "candidate_actions": [{k: c[k] for k in ("id", "type", "target_id", "cost", "cost_basis")} for c in cands],
            "alert_implicated_nodes": implicated,
            "hard_flows": ctx["hard_flows"],
            "sources": ctx["meta_incident"]["compromised_set"],
            "targets": ctx["meta_incident"]["targets"],
        }
        untrusted = [wrap_untrusted(e["source_id"], e.get("content", "")) for e in ctx["evidence"]]
        base = {"provider": llm.name, "model": getattr(llm, "model", None), "k0_optimum_cost": k0_total}
        try:
            raw, usage = llm.complete("propose_containment", structured, untrusted, ContainmentProposals)
        except LLMError as exc:  # the advisor is optional; the certified plans stand without it
            return base | {"status": "unavailable", "error": str(exc), "proposals": []}, []
        assert isinstance(raw, ContainmentProposals)
        verdicts, certs = [], []
        for prop in raw.proposals[: self.MAX_PROPOSALS]:
            ids = list(dict.fromkeys(prop.action_ids))[: self.MAX_ACTIONS]
            unknown = [a for a in ids if a not in cand_ids]
            v: dict[str, Any] = {"title": prop.title[:200], "rationale": prop.rationale[:600], "action_ids": ids}
            if unknown or not ids:
                verdicts.append(v | {"verdict": "rejected", "reasons": [f"unknown or empty action ids: {unknown or ids}"]})
                continue
            cert, lines = tb.call("simulate_intervention", T=inp.T, tau=inp.tau, policy=inp.policy, action_ids=ids)
            certs.append((cert, lines))
            broken = [f["flow_id"] for f in cert["flows"] if f["kind"] == "hard" and not f["preserved"]]
            reasons = []
            if cert["residual_confirmed_paths"]:
                reasons.append(f"a CONFIRMED path survives: {cert['residual_confirmed_paths'][0]}")
            if broken:
                reasons.append(f"breaks hard flow(s) {broken}")
            ok = cert["status"] == "contained"
            extra = (cert["cost"]["total"] - k0_total) if (ok and k0_total is not None) else None
            if ok:
                reasons.append(
                    f"contained; k-certified {cert['robustness']['k_certified']}; cost {cert['cost']['total']}"
                    + (f" (+{extra} over the certified optimum)" if extra else " (matches the certified optimum)")
                )
            verdicts.append(
                v
                | {
                    "verdict": "accepted" if ok else "rejected",
                    "reasons": reasons,
                    "certificate_id": cert["certificate_id"],
                    "total_cost": cert["cost"]["total"],
                    "extra_cost_vs_optimum": extra,
                }
            )
        dropped = max(0, len(raw.proposals) - self.MAX_PROPOSALS)
        return base | {"status": "ok", "usage": usage.__dict__, "proposals": verdicts, "dropped_proposals": dropped}, certs
