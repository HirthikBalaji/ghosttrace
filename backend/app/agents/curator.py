"""E. Memory curator — turns a completed investigation into scoped, provenance-labelled memory."""

from __future__ import annotations

from typing import Any

from app.agents.schemas import CuratorInput, CuratorOutput, Hypothesis, HypothesisVerdict
from app.memory.service import MemoryDraft, MemoryService


class MemoryCurator:
    agent_type = "memory_curator"

    def run(
        self,
        inp: CuratorInput,
        mem: MemoryService,
        incident: dict[str, Any],
        hyps: list[Hypothesis],
        verdicts: list[HypothesisVerdict],
        planner: dict[str, Any],
        evidence_ids: list[str],
        created_at: int,
    ) -> tuple[CuratorOutput, dict[str, Any]]:
        sources = mem.repo.sources()
        vmap = {v.hypothesis_id: v for v in verdicts}
        written, promotions = [], []
        pareto = planner.get("pareto", [])
        k0 = next((p for p in pareto if p["k"] == 0 and p["feasible"]), None)
        epi = MemoryDraft(
            category="episodic",
            investigation_id=inp.investigation_id,
            content=(
                f"{incident['incident_id']}: {incident['title']}. Alerted-account-only response leaves a confirmed "
                f"path ({planner.get('baseline_b0', {}).get('status')}). Cheapest certified plan (k=0, simulated): "
                f"{k0['actions'] if k0 else 'none'}."
            ),
            source_ids=[s for s in evidence_ids if s in sources and not sources[s].contains_instructions],
            entity_ids=[incident["alerted_identity"], *incident["compromised_set"], *incident["targets"]],
            created_at=created_at,
        )
        written.append(mem.write(epi, sources))
        for h in hyps:
            v = vmap.get(h.id)
            if v is None or h.kind != "attack_path":
                continue
            d = MemoryDraft(
                category="episodic",
                investigation_id=inp.investigation_id,
                content=f"Hypothesis: {h.title}. Verifier: {v.status}.",
                source_ids=h.supporting_evidence_ids,
                entity_ids=[h.pivot_id or "", *h.target_ids],
                disputed=v.status == "disputed",
                false_flag="possible_false_flag" in v.flags,
                created_at=created_at,
            )
            props = mem.write(d, sources)
            written.append(props)
            if v.status == "supported":
                promotions.append(mem.promote(d, props["memory_id"], sources))
            else:
                promotions.append(
                    {
                        "promoted": False,
                        "episodic_id": props["memory_id"],
                        "reason": f"verifier status {v.status}; only supported hypotheses are candidates",
                    }
                )
        # Content with embedded instructions is stored (tainted) for audit, never promoted.
        for sid in evidence_ids:
            s = sources.get(sid)
            if s and s.contains_instructions:
                d = MemoryDraft(
                    category="episodic",
                    investigation_id=inp.investigation_id,
                    content=f"Evidence {sid} ({s.system}) contained embedded instructions; treated as data.",
                    source_ids=[sid],
                    created_at=created_at,
                )
                props = mem.write(d, sources)
                written.append(props)
                promotions.append(mem.promote(d, props["memory_id"], sources))
        proc = MemoryDraft(
            category="procedural",
            investigation_id=inp.investigation_id,
            content="Before disabling an alerted account, enumerate credentials cached on its hosts "
            "that authenticate as other principals; plan against the time-valid graph.",
            source_ids=[s for s in evidence_ids if s in sources and sources[s].integrity != "none"][:3],
            created_at=created_at,
        )
        if proc.source_ids:
            written.append(mem.write(proc, sources))
        return CuratorOutput(written=written, promotions=promotions), {}
