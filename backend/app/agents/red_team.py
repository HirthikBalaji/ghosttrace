"""F. Red Team — tries to defeat each certificate.

It searches for surviving paths (including LATENT edges), nominates latent-template instantiations
(accepted only if the deterministic Cypher precondition holds) and proposes evidence-tampering
scenarios from the load-bearing evidence. A witness that reopens a certified plan downgrades it.
"""

from __future__ import annotations

from typing import Any

from app.agents.llm import Nominations, Provider
from app.agents.schemas import RedTeamInput, RedTeamOutput
from app.agents.tools import ToolBox
from app.model import SnapEdge
from app.reasoning.latent import TEMPLATES
from app.reasoning.paths import INF, reopening_distance


class RedTeam:
    agent_type = "red_team"

    def run(self, inp: RedTeamInput, tb: ToolBox, llm: Provider, T: int,
            max_nominations: int = 12) -> tuple[RedTeamOutput, dict[str, Any]]:
        tau_after = inp.tau + 60_000  # simulated clock tick: red-team knowledge is learned after planning
        cand = tb.call("latent_candidates", T=T, tau=inp.tau, limit=200)
        noms_raw, usage = llm.complete("red_team_nominations", {"candidates": cand, "limit": max_nominations}, [],
                                       Nominations)
        assert isinstance(noms_raw, Nominations)
        known = {(c["template_id"], c["src"], c["dst"]) for c in cand}
        nominations = []
        new_latent: list[SnapEdge] = []
        snap = {e.edge_id: e for e in tb.call("get_snapshot_edges", T=T, tau=inp.tau)}
        types = {e.src: e.src_type for e in snap.values()} | {e.dst: e.dst_type for e in snap.values()}
        for n in noms_raw.nominations:
            key = (n.get("template_id", ""), n.get("src", ""), n.get("dst", ""))
            if key not in known:
                nominations.append({**n, "accepted": False, "reason": "nomination references ids the graph did not return"})
                continue
            ok = tb.call("check_latent_nomination", template_id=key[0], src=key[1], dst=key[2], at=inp.tau)
            nominations.append({**n, "accepted": ok, "reason": "Cypher precondition satisfied" if ok
                                else "Cypher precondition not satisfied"})
            if ok:
                t = TEMPLATES[key[0]]
                new_latent.append(SnapEdge(edge_id=f"lat:{key[0]}:{key[1]}->{key[2]}", version=1, type=t.edge_type,
                                           src=key[1], dst=key[2], src_type=types.get(key[1], ""),
                                           dst_type=types.get(key[2], ""), cls="LATENT", temporal="ACTIVE",
                                           template_id=key[0], verify_cost=t.verify_cost))
        findings, downgraded, tampering = [], [], []
        base_edges = list(snap.values())
        for cid in inp.certificate_ids:
            art = tb.call("get_certificate", cert_id=cid)
            if not art:
                continue
            cert = art["payload"]["certificate"]
            if cert["status"] != "contained":
                continue
            removed = frozenset(e for a in cert["actions"] for e in a["removes"])
            d_before, _ = reopening_distance(base_edges, removed, cert["sources"], cert["targets"])
            d_after, wit = reopening_distance(base_edges + new_latent, removed, cert["sources"], cert["targets"])
            k = cert["robustness"]["k_certified"]
            f = {"certificate_id": cid, "k_certified": k, "d_before": None if d_before == INF else int(d_before),
                 "d_with_red_team_latents": None if d_after == INF else int(d_after),
                 "witness": [e.edge_id for e in wit]}
            if d_after <= k:
                f["result"] = "DEFEATED: an accepted latent nomination reopens the plan within k_certified"
                downgraded.append(cid)
            else:
                f["result"] = "held: no accepted nomination reopens the plan within its certified k"
            findings.append(f)
            for lb in cert.get("load_bearing_detail", [])[:6]:
                tampering.append({"certificate_id": cid, "forge_or_suppress": lb["sources"],
                                  "effect": lb["invalidates"],
                                  "mitigation": "independently re-verify these records before relying on the plan"})
        return RedTeamOutput(findings=findings, nominations=nominations, downgraded_certificate_ids=downgraded,
                             tampering_scenarios=tampering, replan_required=bool(downgraded), tau_after=tau_after), {
            "usage": usage.__dict__, "accepted_latent": [e.export() for e in new_latent]}
