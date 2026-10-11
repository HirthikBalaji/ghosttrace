"""REST API v1 (OpenAPI at /docs). No endpoint accepts Cypher; all inputs are validated and clamped."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.agents.brain import CompanyBrain
from app.agents.schemas import BrainQuery
from app.audit.logging import request_id_var
from app.config import get_settings
from app.graph import queries as Q
from app.graph.client import get_client
from app.graph.repository import Repository
from app.ingestion.scenario import list_scenarios, read_scenario
from app.ingestion.seed import seed
from app.memory.service import MemoryService
from app.model import ALL_FACT_EDGE_TYPES, TRAVERSAL_EDGE_TYPES, TrustPolicy
from app.orchestration.approval import ApprovalError, decide
from app.orchestration.orchestrator import Orchestrator
from app.planner import engine
from app.reasoning.kappa import KappaError
from app.reasoning.snapshot import build_snapshot
from app.security.auth import Principal, authenticate, require
from app.security.injection import safe_text
from app.security.ratelimit import RateLimiter
from app.security.verifier_runner import run_verifier
from app.temporal.predicate import TemporalStatus, parse_iso, temporal_status, to_iso

router = APIRouter()
REPO_ROOT = Path(__file__).resolve().parents[3]
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="gt-orch")
_running: set[str] = set()
_running_lock = threading.Lock()
_limiter: RateLimiter | None = None

APPROVAL_FIELDS = ("approval_status", "approved_by", "rejected_by", "decided_at", "decision_note", "execution")
ACTION_ID_RE = r"^[a-z_]{3,32}:[A-Za-z0-9_.:@>\-]{1,160}$"


def limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        try:
            redis = get_client().db.connection
        except Exception:
            redis = None
        _limiter = RateLimiter(get_settings().rate_limit_per_minute, redis)
    return _limiter


def ok(data: Any, **meta: Any) -> dict[str, Any]:
    return {"data": data, "meta": {"request_id": request_id_var.get(), "synthetic": True, **meta}}


def repo_for(p: Annotated[Principal, Depends(require("read"))]) -> Repository:
    return Repository(get_client(), p.workspace_id)


Repo = Annotated[Repository, Depends(repo_for)]
Auth = Annotated[Principal, Depends(authenticate)]
Operator = Annotated[Principal, Depends(require("operate"))]
Approver = Annotated[Principal, Depends(require("approve"))]
Admin = Annotated[Principal, Depends(require("admin"))]


def ts(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return parse_iso(int(value) if value.lstrip("-").isdigit() else value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="timestamps must be ISO-8601 with an explicit offset, or epoch ms") from exc


def _meta(repo: Repository) -> dict[str, Any]:
    try:
        return repo.meta()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="no scenario loaded in this workspace; POST /scenarios/{id}/reset") from exc


def _inv(repo: Repository, inv_id: str) -> dict[str, Any]:
    if len(inv_id) > 40:
        raise HTTPException(status_code=422, detail="invalid investigation id")
    try:
        return Orchestrator(repo).get(inv_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="investigation not found in this workspace") from exc


def _outputs(repo: Repository, inv_id: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for a in repo.list_artifacts("AgentOutput", inv_id):
        out[a["agent_type"] + ("#replan" if a["agent_type"] in out else "")] = a["payload"]
    return out


# ------------------------------------------------------------------ scenarios
@router.get("/scenarios")
def scenarios(p: Auth) -> dict[str, Any]:
    out = []
    loaded = None
    try:
        loaded = Repository(get_client(), p.workspace_id).meta()["scenario_id"]
    except Exception:
        loaded = None
    for sid in list_scenarios():
        d = read_scenario(sid)
        out.append(
            {
                "scenario_id": sid,
                "title": d["title"],
                "description": d["description"],
                "synthetic": True,
                "incident": {k: d["incident"][k] for k in ("incident_id", "title", "severity", "T_incident")},
                "loaded": sid == loaded,
            }
        )
    return ok(out, workspace_id=p.workspace_id)


@router.post("/scenarios/{scenario_id}/reset")
def reset_scenario(scenario_id: str, p: Admin) -> dict[str, Any]:
    if scenario_id not in list_scenarios():
        raise HTTPException(status_code=404, detail="unknown scenario")
    limiter().check(f"reset:{p.workspace_id}", 1)
    stats = seed(get_client(), p.workspace_id, scenario_id)
    return ok(stats)


# ------------------------------------------------------------------ investigations
class NewInvestigation(BaseModel):
    incident_id: str | None = Field(None, max_length=64)
    K: int = Field(2, ge=0, le=3)
    policy: Literal["conservative_defense", "trust_filtered"] = "conservative_defense"


@router.get("/investigations")
def list_investigations(repo: Repo, limit: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    return ok([dict(p) for (p,) in repo.ro(Q.LIST_INVESTIGATIONS, {"limit": limit})])


@router.post("/investigations", status_code=201)
def create_investigation(body: NewInvestigation, repo: Repo, op: Operator) -> dict[str, Any]:
    _meta(repo)
    try:
        inv = Orchestrator(repo).create_investigation(body.incident_id, body.K, body.policy, created_by=op.subject)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ok(inv)


@router.get("/investigations/{inv_id}")
def get_investigation(inv_id: str, repo: Repo) -> dict[str, Any]:
    inv = _inv(repo, inv_id)
    o = Orchestrator(repo)
    with _running_lock:
        active = inv_id in _running
    return ok({"investigation": inv, "tasks": o.tasks(inv_id), "handoffs": o.handoffs(inv_id), "in_process": active})


def _run_bg(ws: str, inv_id: str) -> None:
    try:
        Orchestrator(Repository(get_client(), ws)).run(inv_id)
    finally:
        with _running_lock:
            _running.discard(inv_id)


@router.post("/investigations/{inv_id}/run", status_code=202)
def run_investigation(inv_id: str, repo: Repo, p: Operator, sync: bool = False) -> dict[str, Any]:
    inv = _inv(repo, inv_id)
    limiter().check(f"run:{p.workspace_id}", 1)
    if inv["status"] in ("completed", "cancelled"):
        return ok({"investigation": inv, "note": f"already {inv['status']}"})
    if get_settings().run_mode == "queue":  # a separate worker process picks it up
        return ok({"investigation": Orchestrator(repo).enqueue(inv_id), "note": "queued for a worker"})
    if sync:
        return ok({"investigation": Orchestrator(repo).run(inv_id)})
    with _running_lock:
        if inv_id in _running:
            return ok({"investigation": inv, "note": "already running"})
        _running.add(inv_id)
    _executor.submit(_run_bg, p.workspace_id, inv_id)
    return ok({"investigation": inv, "note": "started"})


@router.get("/investigations/{inv_id}/events")
def investigation_events(inv_id: str, repo: Repo, max_seconds: int = Query(120, ge=1, le=600)) -> StreamingResponse:
    """Server-sent events: one `progress` event whenever task state changes, `done` at a terminal status."""
    import time as _time

    _inv(repo, inv_id)
    o = Orchestrator(repo)

    def gen() -> Any:
        last = None
        deadline = _time.monotonic() + max_seconds
        while _time.monotonic() < deadline:
            inv = o.get(inv_id)
            tasks = [
                {k: t.get(k) for k in ("agent_type", "status", "attempt_count", "tool_calls", "error_category")}
                for t in o.tasks(inv_id)
            ]
            snap = json.dumps({"status": inv["status"], "tasks": tasks}, default=str)
            if snap != last:
                yield f"event: progress\ndata: {snap}\n\n"
                last = snap
            if inv["status"] in ("completed", "failed", "cancelled"):
                yield f"event: done\ndata: {json.dumps({'status': inv['status']})}\n\n"
                return
            _time.sleep(0.4)
        yield "event: timeout\ndata: {}\n\n"

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )


@router.post("/investigations/{inv_id}/cancel")
def cancel_investigation(inv_id: str, repo: Repo, op: Operator) -> dict[str, Any]:
    _inv(repo, inv_id)
    n = Orchestrator(repo).cancel(inv_id)
    return ok({"cancelled_tasks": n, "investigation": _inv(repo, inv_id)})


@router.get("/investigations/{inv_id}/graph")
def graph_view(
    inv_id: str,
    repo: Repo,
    T: str | None = None,
    tau: str | None = None,
    policy: TrustPolicy = TrustPolicy.CONSERVATIVE,
    include_knowledge: bool = False,
    include_inactive: bool = True,
) -> dict[str, Any]:
    inv = _inv(repo, inv_id)
    T_ms, tau_ms = ts(T, inv["T_analysis"]), ts(tau, inv["tau_analysis"])
    w = repo.world(tau_ms)
    snap = build_snapshot(w.versions, w.sources, T_ms, tau_ms, policy)
    vmap = {(v.edge_id, v.version): v for v in w.versions}
    types = set(TRAVERSAL_EDGE_TYPES) | (set(ALL_FACT_EDGE_TYPES) if include_knowledge else set())
    edges = []
    for e in snap.values():
        if e.type not in types:
            continue
        v = vmap.get((e.edge_id, e.version))
        edges.append(
            {
                "edge_id": e.edge_id,
                "version": e.version,
                "type": e.type,
                "src": e.src,
                "dst": e.dst,
                "cls": e.cls,
                "temporal": e.temporal,
                "flags": e.flags,
                "template_id": e.template_id,
                "verify_cost": e.verify_cost,
                "source_ids": e.source_ids,
                "dispute_source_ids": e.dispute_source_ids,
                "confirmed": e.confirmed,
                "kind": v.kind if v else None,
                "rule_id": v.rule_id if v else None,
                "parent_ids": v.parent_ids if v else [],
                "note": safe_text(v.note) if v else "",
                "valid_from": to_iso(v.valid_from) if v else None,
                "valid_to": to_iso(v.valid_to) if v else None,
                "valid_open_ended": v.valid_open_ended if v else None,
                "tx_from": to_iso(v.tx_from) if v else None,
                "tx_to": to_iso(v.tx_to) if v else None,
            }
        )
    inactive = []
    if include_inactive:
        for v in w.versions:
            if v.type in types and v.edge_id not in snap and temporal_status(v, T_ms, tau_ms) == TemporalStatus.INACTIVE:
                inactive.append(
                    {
                        "edge_id": v.edge_id,
                        "version": v.version,
                        "type": v.type,
                        "src": v.src,
                        "dst": v.dst,
                        "temporal": "INACTIVE",
                        "valid_from": to_iso(v.valid_from),
                        "valid_to": to_iso(v.valid_to),
                        "tx_from": to_iso(v.tx_from),
                        "valid_to_source_ids": v.valid_to_source_ids,
                    }
                )
    ids = {e["src"] for e in edges + inactive} | {e["dst"] for e in edges + inactive} | set(w.attack_sources) | set(w.targets)
    nodes = [
        {
            "id": n,
            "label": w.node_props.get(n, {}).get("label", "?"),
            "name": safe_text(w.node_props.get(n, {}).get("name", n)),
            "is_source": n in w.attack_sources,
            "is_target": n in w.targets,
            "segment": w.node_props.get(n, {}).get("segment"),
        }
        for n in sorted(ids)
    ]
    return ok(
        {
            "nodes": nodes,
            "edges": edges,
            "inactive_edges": inactive,
            "T": to_iso(T_ms),
            "tau": to_iso(tau_ms),
            "T_ms": T_ms,
            "tau_ms": tau_ms,
            "policy": policy.value,
            "bounds": {"T_incident": inv["T_incident"], "now": inv["T_analysis"]},
        }
    )


@router.get("/investigations/{inv_id}/edges/{edge_id:path}/history")
def edge_history(inv_id: str, edge_id: str, repo: Repo) -> dict[str, Any]:
    _inv(repo, inv_id)
    if len(edge_id) > 200:
        raise HTTPException(status_code=422, detail="invalid edge id")
    hist = repo.fact_history(edge_id)
    for h in hist:
        for k in ("valid_from", "valid_to", "tx_from", "tx_to", "prior_valid_to"):
            h[k + "_iso"] = to_iso(h.get(k))
    return ok(hist)


@router.get("/investigations/{inv_id}/evidence")
def evidence(inv_id: str, repo: Repo) -> dict[str, Any]:
    inv = _inv(repo, inv_id)
    srcs = repo.sources()
    inc_ev = {p["source_id"] for (p,) in repo.ro(Q.INCIDENT_EVIDENCE, {"iid": inv["incident_id"]})}
    out = []
    for s in sorted(srcs.values(), key=lambda s: s.observed_at):
        out.append(
            s.to_dict()
            | {
                "content": safe_text(s.content),
                "observed_at_iso": to_iso(s.observed_at),
                "ingested_at_iso": to_iso(s.ingested_at),
                "incident_evidence": s.source_id in inc_ev,
            }
        )
    return ok(out)


@router.get("/investigations/{inv_id}/hypotheses")
def hypotheses(inv_id: str, repo: Repo) -> dict[str, Any]:
    _inv(repo, inv_id)
    outs = _outputs(repo, inv_id)
    iv = outs.get("investigator", {}).get("output")
    vo = outs.get("evidence_verifier", {}).get("output")
    return ok({"investigator": iv, "verifier": vo, "complete": bool(iv and vo)})


@router.get("/investigations/{inv_id}/containment")
def containment(inv_id: str, repo: Repo) -> dict[str, Any]:
    _inv(repo, inv_id)
    outs = _outputs(repo, inv_id)
    key = "containment_planner#replan" if "containment_planner#replan" in outs else "containment_planner"
    po = outs.get(key)
    plans = repo.list_artifacts("Plan", inv_id)
    certs = [
        {
            "certificate_id": c["id"],
            "status": c["status"],
            "k_certified": c.get("k_certified"),
            "statement": c["payload"]["certificate"]["statement"],
        }
        for c in repo.list_artifacts("Certificate", inv_id)
    ]
    return ok(
        {
            "planner": po["output"] if po else None,
            "plans": [
                p["payload"]
                | {k: p.get(k) for k in APPROVAL_FIELDS if p.get(k) is not None}
                | ({"mode": p["mode"]} if p.get("mode") else {})
                for p in plans
            ],
            "certificates": certs,
            "red_team": (outs.get("red_team") or {}).get("output"),
        }
    )


class SimulateBody(BaseModel):
    action_ids: list[Annotated[str, Field(pattern=ACTION_ID_RE)]] = Field(..., min_length=0, max_length=20)
    T: str | None = None
    tau: str | None = None
    policy: TrustPolicy = TrustPolicy.CONSERVATIVE


@router.post("/investigations/{inv_id}/containment/simulate")
def simulate(inv_id: str, body: SimulateBody, repo: Repo, p: Operator) -> dict[str, Any]:
    inv = _inv(repo, inv_id)
    limiter().check(f"sim:{p.workspace_id}", 1)
    T_ms, tau_ms = ts(body.T, inv["T_analysis"]), ts(body.tau, inv["tau_analysis"])
    w = repo.world(tau_ms)
    try:
        edges, cands, res = engine.simulate(w, T_ms, tau_ms, body.policy, body.action_ids)
    except (KappaError, KeyError, StopIteration) as exc:
        raise HTTPException(status_code=422, detail=f"invalid action: {exc}") from exc
    cert, lines = engine.certify_plan(
        w, T_ms, tau_ms, body.policy, edges, cands, res, max(res.k, 0), with_load_bearing=res.status == "contained"
    )
    repo.save_artifact(
        "Certificate",
        inv_id,
        cert["certificate_id"],
        {"certificate": cert, "export": lines},
        status=cert["status"],
        k_certified=cert["robustness"]["k_certified"],
        simulated_by=p.subject,
    )
    repo.audit(
        inv_id,
        p.subject,
        "containment.simulated",
        {"actions": body.action_ids, "status": cert["status"], "certificate_id": cert["certificate_id"]},
    )
    return ok({"certificate": cert, "candidates": [a.to_dict() for a in cands]})


@router.get("/investigations/{inv_id}/containment/candidates")
def candidates(
    inv_id: str, repo: Repo, T: str | None = None, tau: str | None = None, policy: TrustPolicy = TrustPolicy.CONSERVATIVE
) -> dict[str, Any]:
    inv = _inv(repo, inv_id)
    T_ms, tau_ms = ts(T, inv["T_analysis"]), ts(tau, inv["tau_analysis"])
    w = repo.world(tau_ms)
    edges = engine.snapshot_edges(w, T_ms, tau_ms, policy)
    return ok([a.to_dict() for a in engine.candidates_for(w, edges)])


@router.get("/investigations/{inv_id}/containment/pareto")
def pareto(
    inv_id: str,
    repo: Repo,
    p: Auth,
    T: str | None = None,
    tau: str | None = None,
    policy: TrustPolicy = TrustPolicy.CONSERVATIVE,
    K: int = Query(2, ge=0, le=3),
) -> dict[str, Any]:
    inv = _inv(repo, inv_id)
    limiter().check(f"pareto:{p.workspace_id}", 1)
    T_ms, tau_ms = ts(T, inv["T_analysis"]), ts(tau, inv["tau_analysis"])
    res = engine.pareto(repo.world(tau_ms), T_ms, tau_ms, policy, K)
    return ok(
        {
            "points": engine.pareto_points(res),
            "T": to_iso(T_ms),
            "tau": to_iso(tau_ms),
            "policy": policy.value,
            "plans": [
                {
                    "k": r.k,
                    "status": r.status,
                    "actions": [a.to_dict() for a in r.actions],
                    "witness": [e.edge_id for e in r.witness],
                    "flows": r.flows,
                    "iterations": r.iterations,
                    "elapsed_ms": round(r.elapsed_ms, 2),
                }
                for r in res
            ],
        }
    )


def _cert(repo: Repository, inv_id: str, cid: str) -> dict[str, Any]:
    if len(cid) > 40:
        raise HTTPException(status_code=422, detail="invalid certificate id")
    art = repo.get_artifact("Certificate", cid)
    if not art or art.get("investigation_id") != inv_id:
        raise HTTPException(status_code=404, detail="certificate not found")
    return art


@router.get("/investigations/{inv_id}/certificate/{cid}")
def get_certificate(inv_id: str, cid: str, repo: Repo) -> dict[str, Any]:
    _inv(repo, inv_id)
    art = _cert(repo, inv_id, cid)
    return ok(
        {
            "certificate": art["payload"]["certificate"],
            "export_lines": len(art["payload"]["export"]),
            "last_verification": art.get("last_verification"),
        }
    )


@router.get("/investigations/{inv_id}/certificate/{cid}/export", response_class=PlainTextResponse)
def export_certificate(inv_id: str, cid: str, repo: Repo) -> str:
    _inv(repo, inv_id)
    art = _cert(repo, inv_id, cid)
    return "\n".join(json.dumps(x, sort_keys=True) for x in art["payload"]["export"]) + "\n"


@router.post("/investigations/{inv_id}/certificate/{cid}/verify")
def verify_certificate(inv_id: str, cid: str, repo: Repo, p: Operator) -> dict[str, Any]:
    _inv(repo, inv_id)
    art = _cert(repo, inv_id, cid)
    limiter().check(f"verify:{p.workspace_id}", 1)
    result = run_verifier(art["payload"]["certificate"], art["payload"]["export"], cid)
    repo.audit(
        inv_id,
        p.subject,
        "certificate.verified",
        {"certificate_id": cid, "accepted": result["accepted"], "output": result["output"][:500]},
    )
    return ok(result)


class Decision(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str = Field("", max_length=1000)
    acknowledge_scrutiny: bool = False


@router.post("/investigations/{inv_id}/plans/{plan_id}/decision")
def decide_plan(inv_id: str, plan_id: str, body: Decision, repo: Repo, p: Approver) -> dict[str, Any]:
    """Record a human approval/rejection of a certified plan. Nothing is executed (this build has no executor)."""
    inv = _inv(repo, inv_id)
    if len(plan_id) > 40:
        raise HTTPException(status_code=422, detail="invalid plan id")
    limiter().check(f"decide:{p.workspace_id}", 1)
    try:
        return ok(decide(repo, inv, plan_id, p, body.decision, body.note, body.acknowledge_scrutiny))
    except ApprovalError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc) + (f": {exc.details}" if exc.details else "")) from exc


@router.get("/investigations/{inv_id}/evidence/load-bearing")
def load_bearing(inv_id: str, repo: Repo) -> dict[str, Any]:
    _inv(repo, inv_id)
    out = []
    for c in repo.list_artifacts("Certificate", inv_id):
        cert = c["payload"]["certificate"]
        if cert["status"] == "contained":
            out.append(
                {
                    "certificate_id": c["id"],
                    "k_certified": cert["robustness"]["k_certified"],
                    "load_bearing": cert.get("load_bearing_detail", []),
                }
            )
    return ok(out)


@router.get("/investigations/{inv_id}/evidence-sensitivity")
def sensitivity(inv_id: str, repo: Repo) -> dict[str, Any]:
    _inv(repo, inv_id)
    po = _outputs(repo, inv_id).get("containment_planner")
    return ok(po["output"]["sensitivity"] if po else None)


@router.get("/investigations/{inv_id}/report")
def report(inv_id: str, repo: Repo, fmt: Literal["json", "md"] = Query("json", alias="format")) -> Any:
    inv = _inv(repo, inv_id)
    outs = _outputs(repo, inv_id)
    certs = [c["payload"]["certificate"] for c in repo.list_artifacts("Certificate", inv_id)]
    data = {
        "investigation": inv,
        "outputs": outs,
        "certificates": certs,
        "audit": repo.get_audit(inv_id),
        "disclaimer": "SYNTHETIC demo data. All actions are simulations; nothing was executed.",
    }
    if fmt == "json":
        return ok(data)
    lines = [
        f"# GHOSTTRACE report — {inv['title']}",
        "",
        "> SYNTHETIC demo data. All actions are simulations.",
        "",
        f"- Investigation: `{inv['id']}` status **{inv['status']}**",
        f"- Analysis clock: T={to_iso(inv['T_analysis'])}, tau={to_iso(inv['tau_analysis'])} ({inv.get('clock')})",
        "",
    ]
    iv = (outs.get("investigator") or {}).get("output")
    if iv:
        lines += ["## Hypotheses", ""] + [f"- {h['title']}" for h in iv["hypotheses"]] + ["", iv["reasoning_summary"], ""]
    vo = (outs.get("evidence_verifier") or {}).get("output")
    if vo:
        lines += (
            ["## Verification", ""]
            + [f"- `{v['hypothesis_id']}`: **{v['status']}** — {'; '.join(v['reasons'])}" for v in vo["verdicts"]]
            + [""]
        )
    lines += ["## Certificates", ""]
    for c in certs:
        lines += [
            f"### {c['certificate_id']} — {c['status']}",
            "",
            c["statement"],
            "",
            f"- actions: {[a['id'] for a in c['actions']]}",
            f"- cost: {c['cost']}",
            f"- optimality: {c['optimality']['status']}",
            f"- requires human scrutiny: {c['requires_human_scrutiny']}",
            f"- load-bearing evidence: {c['load_bearing_evidence']}",
            "",
        ]
    return PlainTextResponse("\n".join(lines), media_type="text/markdown")


# ------------------------------------------------------------------ company brain
def _brain(repo: Repository, q: str, subject: str, T: str | None, tau: str | None) -> dict[str, Any]:
    m = _meta(repo)
    if len(subject) > 120:
        raise HTTPException(status_code=422, detail="subject too long")
    T_ms, tau_ms = ts(T, m["now"]), ts(tau, m["now"])
    ans = CompanyBrain(repo).ask(BrainQuery(question=q, subject_id=subject, T=T_ms, tau=tau_ms))
    return ok(ans.model_dump())


@router.get("/company/owners")
def owners(
    repo: Repo, service_id: str = Query(..., max_length=120), asof_T: str | None = None, known_tau: str | None = None
) -> dict[str, Any]:
    return _brain(repo, "owner", service_id, asof_T, known_tau)


@router.get("/company/dependencies/{asset_id:path}")
def dependencies(
    asset_id: str,
    repo: Repo,
    direction: Literal["dependents", "dependencies"] = "dependents",
    asof_T: str | None = None,
    known_tau: str | None = None,
) -> dict[str, Any]:
    return _brain(repo, direction, asset_id, asof_T, known_tau)


@router.get("/company/ask")
def ask(
    repo: Repo,
    question: Literal["owner", "experts", "dependencies", "dependents", "runbooks", "decisions"],
    subject_id: str = Query(..., max_length=120),
    asof_T: str | None = None,
    known_tau: str | None = None,
) -> dict[str, Any]:
    return _brain(repo, question, subject_id, asof_T, known_tau)


@router.get("/company/search")
def search(repo: Repo, q: str = Query(..., min_length=1, max_length=60)) -> dict[str, Any]:
    rows = repo.ro(Q.SEARCH_NODES, {"q": q.lower()})
    return ok([{"id": i, "label": [x for x in lab if x != "Entity"][0], "name": safe_text(n)} for i, lab, n in rows])


# ------------------------------------------------------------------ memory & audit
@router.get("/memory")
def memory(repo: Repo, limit: int = Query(200, ge=1, le=500)) -> dict[str, Any]:
    return ok([m | {"content": safe_text(m.get("content", ""))} for m in MemoryService(repo).entries(limit)])


@router.get("/audit/{inv_id}")
def audit(inv_id: str, repo: Repo) -> dict[str, Any]:
    _inv(repo, inv_id)
    return ok(repo.get_audit(inv_id))


@router.get("/whoami")
def whoami(p: Auth, request: Request) -> dict[str, Any]:
    return ok(
        {
            "subject": p.subject,
            "workspace_id": p.workspace_id,
            "auth_mode": p.mode,
            "roles": sorted(p.roles),
            "warning": None if p.mode == "oidc" else "demo-only authentication; not production auth",
        }
    )
