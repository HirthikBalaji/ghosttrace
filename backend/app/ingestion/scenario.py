"""Scenario loader: replays a synthetic, timestamped ingestion log into a Ledger.

Seeded `at` timestamps are the synthetic transaction times of the replayed log (simulated clock), so
bitemporal behaviour such as backfill is reproducible. Live API ingestion uses the wall clock.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.ingestion.ledger import IngestionError, Ledger
from app.model import Flow, Node, SourceRecord, TrustPolicy
from app.planner.engine import World
from app.reasoning.latent import TemplateRejected, check_preconditions_py, check_types
from app.reasoning.snapshot import build_snapshot
from app.security.injection import contains_instructions
from app.temporal.predicate import parse_iso

SCENARIO_DIR = Path(__file__).resolve().parents[3] / "data" / "scenarios"
NodeKeys = ("id", "label", "name")

# checker(template_id, src, dst, at_ms, ledger) -> bool  (graph-query backed in production)
PreconditionChecker = Callable[[str, str, str, int, Ledger], bool]


@dataclass
class ScenarioMeta:
    scenario_id: str
    title: str
    description: str
    incident: dict[str, Any]
    now: int
    flows: list[Flow]
    incident_evidence: list[str]
    memory_seed: list[dict[str, Any]]
    contradictions: list[list[str]]
    nominations: list[dict[str, Any]] = field(default_factory=list)


def list_scenarios() -> list[str]:
    return sorted(p.stem for p in SCENARIO_DIR.glob("*.json"))


def read_scenario(scenario_id: str) -> dict[str, Any]:
    if scenario_id not in list_scenarios():
        raise IngestionError(f"unknown scenario {scenario_id}")
    data: dict[str, Any] = json.loads((SCENARIO_DIR / f"{scenario_id}.json").read_text())
    return data


def python_checker(template_id: str, src: str, dst: str, at: int, ledger: Ledger) -> bool:
    snap = build_snapshot(ledger.all_versions(), ledger.sources, at, at, TrustPolicy.CONSERVATIVE)
    props = {n.id: n.props for n in ledger.nodes.values()}
    return check_preconditions_py(template_id, src, dst, snap, props)


def load(data: dict[str, Any], workspace_id: str, checker: PreconditionChecker = python_checker) -> tuple[Ledger, ScenarioMeta]:
    if not data.get("synthetic"):
        raise IngestionError("only synthetic scenarios may be loaded in this build")
    led = Ledger(workspace_id)
    compromised = set(data["incident"]["compromised_set"])
    for n in data["nodes"]:
        props = {k: v for k, v in n.items() if k not in NodeKeys}
        led.add_node(Node(id=n["id"], label=n["label"], workspace_id=workspace_id, name=n.get("name", ""),
                          props=props))
    for s in data["sources"]:
        written_on = s.get("written_on")
        led.add_source(SourceRecord(
            source_id=s["source_id"], integrity=s["integrity"],
            # Threat model: records written on hosts in the suspected-compromised set are attacker-influenceable.
            attacker_influenceable=bool(written_on in compromised) or bool(s.get("attacker_influenceable", False)),
            root_id=s["root_id"], trust_class=s["trust_class"], observed_at=parse_iso(s["observed_at"]),
            ingested_at=parse_iso(s["ingested_at"]), derived_from=list(s.get("derived_from", [])),
            system=s.get("system", ""), content=s.get("content", ""),
            contains_instructions=contains_instructions(s.get("content", "")),
        ))
    nominations: list[dict[str, Any]] = []
    for ev in sorted(data["events"], key=lambda e: parse_iso(e["at"])):
        op = ev["op"]
        if op == "assert":
            led.assert_edge(fact_id=ev["fact_id"], type=ev["type"], src=ev["src"], dst=ev["dst"], at=ev["at"],
                            source_ids=ev["sources"], valid_from=ev.get("valid_from"), valid_to=ev.get("valid_to"),
                            valid_open_ended=ev.get("valid_open_ended", False), stale=ev.get("stale", False),
                            cost_remove=ev.get("cost_remove"), note=ev.get("note", ""))
        elif op == "remove":
            led.remove_edge(fact_id=ev["fact_id"], removed_at=ev["removed_at"], at=ev["at"], source_ids=ev["sources"])
        elif op == "correct":
            changes = {k: ev[k] for k in ("valid_from", "valid_to", "valid_open_ended") if k in ev}
            led.correct_edge(fact_id=ev["fact_id"], at=ev["at"], source_ids=ev["sources"], **changes)
        elif op == "latent" and data.get("generated"):
            # Benchmark generator only: latent edges inserted directly (preconditions bypassed, documented).
            led.add_latent(template_id=ev["template_id"], type=ev["type"], src=ev["src"], dst=ev["dst"],
                           at=ev["at"], verify_cost=int(ev["verify_cost"]), created_by="generator")
        elif op == "nominate_latent":
            nominations.append(nominate(led, ev["template_id"], ev["src"], ev["dst"], parse_iso(ev["at"]),
                                        ev.get("nominated_by", "unknown"), checker))
        else:
            raise IngestionError(f"unknown event op {op}")
    led.derive()
    inc = dict(data["incident"])
    meta = ScenarioMeta(
        scenario_id=data["scenario_id"], title=data["title"], description=data.get("description", ""),
        incident=inc, now=parse_iso(data["clock"]["now"]),
        flows=[Flow(f["flow_id"], f["u"], f["v"], int(f["weight"]), f["kind"], f.get("description", ""))
               for f in data["flows"]],
        incident_evidence=list(data.get("incident_evidence", [])), memory_seed=list(data.get("memory_seed", [])),
        contradictions=list(data.get("contradictions", [])), nominations=nominations,
    )
    return led, meta


def nominate(led: Ledger, template_id: str, src: str, dst: str, at: int, nominated_by: str,
             checker: PreconditionChecker) -> dict[str, Any]:
    """Accept a latent-edge nomination only if the template is allowlisted and its preconditions hold."""
    rec = {"template_id": template_id, "src": src, "dst": dst, "nominated_by": nominated_by, "at": at}
    try:
        t = check_types(template_id, led.nodes[src].label if src in led.nodes else None,
                        led.nodes[dst].label if dst in led.nodes else None)
    except TemplateRejected as exc:
        return rec | {"accepted": False, "reason": str(exc)}
    if not checker(template_id, src, dst, at, led):
        return rec | {"accepted": False, "reason": "preconditions not satisfied by the graph"}
    led.add_latent(template_id=template_id, type=t.edge_type, src=src, dst=dst, at=at, verify_cost=t.verify_cost,
                   created_by=f"template_engine (nominated by {nominated_by})", note=t.explanation)
    return rec | {"accepted": True, "reason": t.explanation}


def world_from(led: Ledger, meta: ScenarioMeta) -> World:
    props = {n.id: {"label": n.label, "name": n.name, **n.props} for n in led.nodes.values()}
    return World(workspace_id=led.workspace_id, versions=led.all_versions(), sources=dict(led.sources),
                 node_props=props, flows=list(meta.flows), attack_sources=list(meta.incident["compromised_set"]),
                 targets=list(meta.incident["targets"]),
                 meta={"scenario_id": meta.scenario_id, "now": meta.now,
                       "T_incident": parse_iso(meta.incident["T_incident"])})
