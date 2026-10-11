"""B. Evidence verifier — tries to falsify each hypothesis from independently re-fetched evidence.

It cannot rewrite evidence and never confirms a hypothesis because another agent said so: it re-derives
path classes from its own snapshot query and re-fetches every cited record.
"""

from __future__ import annotations

from typing import Any

from app.agents.schemas import Hypothesis, HypothesisVerdict, VerifierInput, VerifierOutput
from app.agents.tools import ToolBox
from app.model import Flag, SourceRecord
from app.reasoning.evidence import independent_root_count
from app.reasoning.paths import classify_path
from app.temporal.predicate import to_iso


class EvidenceVerifier:
    agent_type = "evidence_verifier"

    def run(self, inp: VerifierInput, hyps: list[Hypothesis], tb: ToolBox, T_now: int,
            alerted_identity: str, incident_evidence_ids: list[str] | None = None) -> tuple[VerifierOutput, dict[str, Any]]:
        snap_now = {e.edge_id: e for e in tb.call("get_snapshot_edges", T=T_now, tau=inp.tau)}
        snap_inc = {e.edge_id: e for e in tb.call("get_snapshot_edges", T=inp.T_incident, tau=inp.tau)}
        snap_known_then = {e.edge_id: e for e in tb.call("get_snapshot_edges", T=inp.T_incident, tau=inp.T_incident)}
        cited = sorted({s for h in hyps for s in h.supporting_evidence_ids + h.contradicting_evidence_ids})
        fetched = {r["source_id"]: r for r in tb.call("get_evidence", source_ids=cited)}
        recs = {sid: SourceRecord(**{k: r.get(k) for k in SourceRecord.__dataclass_fields__}
                                  | {"derived_from": list(r.get("derived_from") or [])}) for sid, r in fetched.items()}
        verdicts = []
        for h in hyps:
            ids = h.supporting_evidence_ids
            resolved = [s for s in ids + h.contradicting_evidence_ids if s in fetched]
            roots = independent_root_count([s for s in ids if s in recs], recs)
            reasons: list[str] = []
            flags: list[str] = []
            if h.kind == "benign_prior_pattern":
                status = "disputed" if h.contradicting_evidence_ids else "insufficient_evidence"
                reasons.append("prior-incident similarity is context, not evidence about this incident")
                if h.contradicting_evidence_ids:
                    reasons.append("independent confirmed exposure path exists regardless of the sign-in's cause")
                reasons.append("absence of evidence of exfiltration is not evidence of absence")
                verdicts.append(HypothesisVerdict(hypothesis_id=h.id, status=status, reasons=reasons,
                                                  citations_resolved=len(resolved),
                                                  citations_total=len(ids + h.contradicting_evidence_ids),
                                                  independent_roots=roots, temporal_check="n/a", flags=flags))
                continue
            # Re-derive the best path's class from this agent's own snapshot (not the investigator's label).
            best = h.paths[0] if h.paths else None
            if best is None or any(e not in snap_now for e in best.edge_ids):
                verdicts.append(HypothesisVerdict(hypothesis_id=h.id, status="insufficient_evidence",
                                                  reasons=["path not reproducible from the current snapshot"],
                                                  citations_resolved=len(resolved), citations_total=len(ids),
                                                  independent_roots=roots, temporal_check="failed"))
                continue
            info = classify_path([snap_now[e] for e in best.edge_ids])
            if info.path_class != h.path_class:
                reasons.append(f"investigator label {h.path_class} != re-derived {info.path_class}; using re-derived")
            at_inc = all(e in snap_inc for e in best.edge_ids)
            known_then = all(e in snap_known_then for e in best.edge_ids)
            temporal = (f"all edges valid at incident T={to_iso(inp.T_incident)}" if at_inc
                        else "some edges were not valid at incident time (post-incident change)")
            if at_inc and not known_then:
                late = [e for e in best.edge_ids if e not in snap_known_then]
                temporal += f"; not knowable at incident time — learned later: {late}"
            ff = [e for e in best.edge_ids if Flag.POSSIBLE_FALSE_FLAG.value in snap_now[e].flags]
            disputed = [e for e in best.edge_ids if Flag.DISPUTED.value in snap_now[e].flags]
            if ff:
                flags.append("possible_false_flag")
                reasons.append(f"path relies on attacker-influenceable-only evidence {ff} (R3)")
            if disputed:
                flags.append("disputed_removal_ignored")
                reasons.append(f"edges {disputed} have untrusted removal claims; per R2 they still count")
            if len(resolved) < len(ids):
                reasons.append("some citations do not resolve to stored records")
            if info.path_class == "CONFIRMED" and len(resolved) == len(ids + h.contradicting_evidence_ids):
                status = "supported"
                reasons.append(f"every edge OBSERVED/DERIVED and active; {roots} independent root(s)")
            elif ff:
                status = "disputed"
            elif info.latent_count or info.uncertain_count:
                status = "partially_supported"
                reasons.append(f"depends on {info.latent_count} latent and {info.uncertain_count} validity-uncertain edge(s)")
            else:
                status = "insufficient_evidence"
            verdicts.append(HypothesisVerdict(hypothesis_id=h.id, status=status, reasons=reasons,
                                              citations_resolved=len(resolved),
                                              citations_total=len(ids + h.contradicting_evidence_ids),
                                              independent_roots=roots, temporal_check=temporal, flags=flags))

        # Stale runbooks: guidance that predates credential facts on confirmed paths.
        rbs = tb.call("get_runbooks", ids=[alerted_identity], T=T_now, tau=inp.tau)
        cred_starts = [e for h in hyps if h.path_class == "CONFIRMED" for p in h.paths[:1] for e in p.edge_ids
                       if snap_now[e].type in ("AUTHENTICATES_AS", "HAS_CREDENTIAL")]
        hist = {e: tb.call("get_fact_history", edge_id=e) for e in sorted(set(cred_starts))[:6]}
        stale = []
        for rb in rbs:
            vf = rb.get("valid_from")
            from app.temporal.predicate import parse_iso
            rb_from = parse_iso(vf) if isinstance(vf, str) else vf
            newer = [e for e, versions in hist.items() if versions and (versions[0].get("valid_from") or 0) > (rb_from or 0)]
            if newer:
                stale.append({"runbook_id": rb["id"], "name": rb["name"], "recommendation": rb["text"],
                              "reason": f"written {vf}, before credential facts {newer} existed; its "
                                        "recommendation does not account for them"})
        disputed_removals = [{"edge_id": e.edge_id, "dispute_source_ids": e.dispute_source_ids,
                              "rule": "R2: untrusted removal claim does not remove the edge"}
                             for e in snap_now.values() if Flag.DISPUTED.value in e.flags]
        all_ev = tb.call("get_evidence", source_ids=sorted({s for e in snap_now.values() for s in e.source_ids}
                                                           | set(cited) | set(incident_evidence_ids or [])))
        inj = [{"source_id": r["source_id"], "note": "embedded instructions detected; treated as data, no tool call made"}
               for r in all_ev if r.get("contains_instructions")]
        recs_all = {r["source_id"]: SourceRecord(**{k: r.get(k) for k in SourceRecord.__dataclass_fields__}
                                                 | {"derived_from": list(r.get("derived_from") or [])}) for r in all_ev}
        dup = []
        for e in snap_now.values():
            if len(e.source_ids) > 1 and all(s in recs_all for s in e.source_ids):
                n = independent_root_count(e.source_ids, recs_all)
                if n < len(e.source_ids):
                    dup.append({"edge_id": e.edge_id, "records": len(e.source_ids), "independent_roots": n,
                                "class": e.cls, "flags": e.flags})
        out = VerifierOutput(verdicts=verdicts, stale_runbooks=stale, disputed_removals=disputed_removals,
                             injection_flags=inj, duplicate_evidence=dup,
                             notes=["Verifier re-derived path classes from its own snapshot query.",
                                    "Duplicate records from one upstream root are counted once."])
        return out, {}
