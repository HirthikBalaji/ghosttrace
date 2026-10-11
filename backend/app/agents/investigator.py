"""A. Investigator — hypotheses and candidate paths from time-valid graph traversal."""

from __future__ import annotations

from typing import Any

from app.agents.llm import Explanation, Provider, validate_cited_ids
from app.agents.schemas import Hypothesis, InvestigatorInput, InvestigatorOutput, PathOut
from app.agents.tools import ToolBox
from app.model import Flag
from app.security.injection import wrap_untrusted
from app.temporal.predicate import to_iso

CLASS_RANK = {"CONFIRMED": 0, "TEMPORALLY_UNCERTAIN": 2}


def _rank(c: str) -> tuple[int, int]:
    if c.startswith("CONDITIONAL"):
        return (1, int(c[12:-1]))
    return (CLASS_RANK.get(c, 3), 0)


class Investigator:
    agent_type = "investigator"

    def run(self, inp: InvestigatorInput, tb: ToolBox, llm: Provider) -> tuple[InvestigatorOutput, dict[str, Any]]:
        ctx = tb.call("get_incident_context", incident_id=inp.incident_id)
        evidence = ctx["evidence"]
        evidence_ids = [e["source_id"] for e in evidence]
        res_now = tb.call("find_attack_paths", T=inp.T_now, tau=inp.tau, max_depth=inp.max_depth)
        res_then = tb.call("find_attack_paths", T=inp.T_incident, tau=inp.tau, max_depth=inp.max_depth)
        # what was knowable at incident time (tau = T_incident)
        res_known_then = tb.call("find_attack_paths", T=inp.T_incident, tau=inp.T_incident, max_depth=inp.max_depth)
        edges = res_now["edges"]
        sources = set(res_now["sources"])
        known_then_edges = set(res_known_then["edges"])

        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for p in res_now["paths"]:
            pivot = next((n for n in p["node_ids"] if n not in sources), p["node_ids"][-1])
            groups.setdefault((pivot, p["node_ids"][-1]), []).append(p)

        hyps: list[Hypothesis] = []
        for i, ((pivot, target), ps) in enumerate(sorted(groups.items())):
            ps.sort(key=lambda p: (_rank(p["path_class"]), len(p["edge_ids"])))
            best = ps[0]
            sup = sorted({s for p in ps[:5] for e in p["edge_ids"] for s in edges[e].source_ids})
            con = sorted({s for p in ps[:5] for e in p["edge_ids"] for s in edges[e].dispute_source_ids})
            ff = sorted({e for p in ps for e in p["edge_ids"] if Flag.POSSIBLE_FALSE_FLAG.value in edges[e].flags})
            unknowns = []
            for e in best["assumptions"]:
                why = ",".join(edges[e].flags) or f"template {edges[e].template_id}"
                unknowns.append(f"edge {e} is {edges[e].cls}/{edges[e].temporal} ({why})")
            if ff:
                unknowns.append(f"relies on possible_false_flag evidence: {ff}")
            hyps.append(
                Hypothesis(
                    id=f"hyp:{inp.investigation_id}:{i}",
                    kind="attack_path",
                    title=f"Attacker can reach {target} via {pivot} ({best['path_class']})",
                    target_ids=[target],
                    pivot_id=pivot,
                    path_class=best["path_class"],
                    paths=[PathOut(**p) for p in ps[:5]],
                    supporting_evidence_ids=sup,
                    contradicting_evidence_ids=con,
                    assumptions=list(best["assumptions"]),
                    unknowns=unknowns,
                    known_at_incident_time=all(e in known_then_edges for e in best["edge_ids"]),
                )
            )

        # Prior-incident memory informs (as a competing hypothesis) but does not dictate.
        priors = tb.call("get_related_prior_incidents", current=inp.incident_id)
        mem = tb.call(
            "get_memory",
            entity_ids=[
                ctx["meta_incident"]["alerted_identity"],
                *res_now["sources"],
                *res_now["targets"],
                *(p["id"] for p in priors),
            ],
            source_ids=evidence_ids,
            now=inp.T_now,
        )
        memory_consulted = [
            {
                "memory_id": m["memory_id"],
                "category": m["category"],
                "taint": m.get("taint"),
                "content": m["content"],
                "relevance": m["relevance"],
            }
            for m in mem
        ]
        confirmed_support = sorted({s for h in hyps if h.path_class == "CONFIRMED" for s in h.supporting_evidence_ids})
        for m in mem:
            if m["category"] == "episodic" and "benign" in m["content"].lower():
                hyps.append(
                    Hypothesis(
                        id=f"hyp:{inp.investigation_id}:prior:{m['memory_id']}",
                        kind="benign_prior_pattern",
                        title=f"Benign, like a prior incident ({m['memory_id']})",
                        target_ids=[],
                        path_class=None,
                        supporting_evidence_ids=list(m["source_ids"]),
                        contradicting_evidence_ids=confirmed_support,
                        assumptions=["the current alert has the same root cause as the prior incident"],
                        unknowns=["no evidence links the prior root cause (VPN egress change) to this alert"],
                    )
                )
        all_paths = [PathOut(**p) for p in res_now["paths"]]
        unknowns = sorted({u for h in hyps for u in h.unknowns})
        lost = [p["edge_ids"] for p in res_then["paths"] if p["path_class"] == "CONFIRMED"]
        structured = {
            "hypotheses": [h.model_dump(include={"id", "title", "path_class"}) for h in hyps],
            "path_count": len(all_paths),
            "T": to_iso(inp.T_now),
            "tau": to_iso(inp.tau),
            "memory_used": bool(mem),
        }
        untrusted = [wrap_untrusted(e["source_id"], e.get("content", "")) for e in evidence]
        expl, usage = llm.complete("investigation_summary", structured, untrusted, Explanation)
        assert isinstance(expl, Explanation)
        bad = validate_cited_ids(expl.cited_ids, {h.id for h in hyps})
        out = InvestigatorOutput(
            hypotheses=hyps,
            paths=all_paths,
            supporting_evidence_ids=sorted({s for h in hyps for s in h.supporting_evidence_ids}),
            contradicting_evidence_ids=sorted({s for h in hyps for s in h.contradicting_evidence_ids}),
            assumptions=sorted({a for h in hyps for a in h.assumptions}),
            unknowns=unknowns,
            recommended_next_queries=[f"verify {e}" for e in res_now["witness"] if not edges[e].confirmed]
            + [f"get_service_owners({t})" for t in res_now["targets"]],
            reasoning_summary=expl.summary + (f" Paths confirmed at incident time T: {len(lost)}." if lost else ""),
            memory_consulted=memory_consulted,
            status="completed" if not res_now["cypher_truncated"] else "partial",
        )
        return out, {"usage": usage.__dict__, "rejected_model_ids": bad, "prior_incidents": priors}
