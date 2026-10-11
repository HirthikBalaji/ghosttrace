"""Durable multi-agent orchestration (§7.1).

Task state machine: queued -> running -> completed | failed | blocked | cancelled, persisted as
:AgentTask nodes in the workspace graph. State is written before and after every stage; a HANDOFF_TO
edge is recorded before the next agent starts; tasks are claimed with a lease via an atomic Cypher
compare-and-set and completed only by the lease owner. Stage outputs are persisted as artifacts, so a
restarted orchestrator resumes from the first incomplete stage without re-running completed ones.
"""

from __future__ import annotations

import hashlib
import json
import logging
import traceback
import uuid
from typing import Any

from app.agents.curator import MemoryCurator
from app.agents.evidence_verifier import EvidenceVerifier
from app.agents.investigator import Investigator
from app.agents.llm import LLMError, Provider, get_provider
from app.agents.planner_agent import ContainmentPlanner
from app.agents.red_team import RedTeam
from app.agents.schemas import (
    CuratorInput,
    Hypothesis,
    HypothesisVerdict,
    InvestigatorInput,
    InvestigatorOutput,
    PlannerInput,
    PlannerOutput,
    RedTeamInput,
    RedTeamOutput,
    VerifierInput,
    VerifierOutput,
)
from app.agents.tools import BudgetExceeded, Cancelled, ToolBox, ToolError
from app.graph import queries as Q
from app.graph.repository import Repository, now_ms
from app.memory.service import MemoryService
from app.model import EdgeVersion
from app.temporal.predicate import parse_iso

log = logging.getLogger("ghosttrace.orchestrator")

STAGES = ["investigator", "evidence_verifier", "containment_planner", "red_team", "memory_curator"]
LEASE_MS = 120_000
MAX_ATTEMPTS = 2
BUDGETS = {"investigator": 40, "evidence_verifier": 60, "containment_planner": 20, "red_team": 120,
           "memory_curator": 20}


def _tid(inv: str, key: str) -> str:
    return "task_" + hashlib.sha256(f"{inv}|{key}".encode()).hexdigest()[:16]


class StageFailure(RuntimeError):
    def __init__(self, category: str, msg: str):
        super().__init__(msg)
        self.category = category


class Orchestrator:
    def __init__(self, repo: Repository, provider: Provider | None = None, worker_id: str | None = None,
                 fail_after_stage: str | None = None):
        self.repo = repo
        self.llm = provider or get_provider()
        self.worker = worker_id or f"worker_{uuid.uuid4().hex[:8]}"
        self.fail_after_stage = fail_after_stage  # test hook: simulate a crash after this stage completes

    # ------------------------------------------------------------------ investigations
    def create_investigation(self, incident_id: str | None = None, K: int = 2,
                             policy: str = "conservative_defense") -> dict[str, Any]:
        meta = self.repo.meta()
        inc = meta["incident"]
        if incident_id and incident_id != inc["incident_id"]:
            raise LookupError("unknown incident")
        inv_id = f"inv_{uuid.uuid4().hex[:10]}"
        props = {"id": inv_id, "workspace_id": self.repo.ws, "incident_id": inc["incident_id"],
                 "scenario_id": meta["scenario_id"], "title": inc["title"], "status": "created",
                 "created_at": now_ms(), "T_incident": parse_iso(inc["T_incident"]), "T_analysis": meta["now"],
                 "tau_analysis": meta["now"], "K": K, "policy": policy, "clock": "simulated scenario clock"}
        self.repo.rw(Q.CREATE_INVESTIGATION, {"id": inv_id, "props": props})
        self.repo.audit(inv_id, "api", "investigation.created", props)
        return props

    def get(self, inv_id: str) -> dict[str, Any]:
        rows = self.repo.ro(Q.GET_INVESTIGATION, {"id": inv_id})
        if not rows:
            raise LookupError("investigation not found")
        return dict(rows[0][0])

    def _set(self, inv_id: str, **props: Any) -> None:
        self.repo.rw(Q.UPDATE_INVESTIGATION, {"id": inv_id, "props": props})

    def cancel(self, inv_id: str) -> int:
        self.get(inv_id)
        self._set(inv_id, status="cancelled", cancelled_at=now_ms())
        n = self.repo.rw(Q.CANCEL_TASKS, {"inv": inv_id, "now": now_ms()})
        self.repo.audit(inv_id, "api", "investigation.cancelled", {})
        return int(n[0][0]) if n else 0

    def tasks(self, inv_id: str) -> list[dict[str, Any]]:
        return [dict(p) for (p,) in self.repo.ro(Q.GET_TASKS, {"inv": inv_id})]

    def handoffs(self, inv_id: str) -> list[dict[str, Any]]:
        keys = ("from_task", "from_agent", "to_task", "to_agent", "at", "refs", "note")
        return [dict(zip(keys, r, strict=True)) for r in self.repo.ro(Q.GET_HANDOFFS, {"inv": inv_id})]

    # ------------------------------------------------------------------ task primitives
    def _ensure_task(self, inv_id: str, seq: int, agent_type: str, key: str, inputs: list[str],
                     parent: str | None) -> dict[str, Any]:
        tid = _tid(inv_id, key)
        props = {"task_id": tid, "workspace_id": self.repo.ws, "investigation_id": inv_id, "agent_type": agent_type,
                 "seq": seq, "status": "queued", "attempt_count": 0, "idempotency_key": f"{inv_id}:{key}",
                 "input_ref_ids": inputs, "output_ref_ids": [], "created_at": now_ms(), "parent_task_id": parent or "",
                 "lease_owner": "", "lease_expires_at": 0}
        rows = self.repo.rw(Q.UPSERT_TASK, {"inv": inv_id, "key": f"{inv_id}:{key}", "props": props})
        return dict(rows[0][0])

    def _claim(self, task: dict[str, Any]) -> dict[str, Any] | None:
        now = now_ms()
        rows = self.repo.rw(Q.CLAIM_TASK, {"tid": task["task_id"], "owner": self.worker, "now": now,
                                           "exp": now + LEASE_MS})
        return dict(rows[0][0]) if rows else None

    def _complete(self, task: dict[str, Any], **props: Any) -> bool:
        rows = self.repo.rw(Q.COMPLETE_TASK, {"tid": task["task_id"], "owner": self.worker,
                                              "props": props | {"finished_at": now_ms(), "lease_expires_at": 0}})
        return bool(rows)

    def _handoff(self, a: str, b: str, refs: list[str], note: str) -> None:
        self.repo.rw(Q.HANDOFF, {"a": a, "b": b, "refs": refs, "note": note, "now": now_ms()})

    def _output(self, task: dict[str, Any]) -> dict[str, Any] | None:
        refs = task.get("output_ref_ids") or []
        return self.repo.get_artifact("AgentOutput", refs[0]) if refs else None

    # ------------------------------------------------------------------ run / resume
    def run(self, inv_id: str) -> dict[str, Any]:
        inv = self.get(inv_id)
        if inv["status"] in ("cancelled", "completed"):
            return inv
        self._set(inv_id, status="running", worker=self.worker, updated_at=now_ms())
        outputs: dict[str, dict[str, Any]] = {}
        prev: dict[str, Any] | None = None
        stages = list(STAGES)
        i = 0
        while i < len(stages):
            stage_key = stages[i]
            agent_type = stage_key.split("#")[0]
            task = self._ensure_task(inv_id, i, agent_type, stage_key, [prev["task_id"]] if prev else [],
                                     prev["task_id"] if prev else None)
            if task["status"] == "completed":
                out = self._output(task)
                outputs[stage_key] = out["payload"] if out else {}
            elif task["status"] == "cancelled" or self.get(inv_id)["status"] == "cancelled":
                return self.get(inv_id)
            else:
                if task["status"] == "failed" and task.get("attempt_count", 0) >= MAX_ATTEMPTS:
                    self._set(inv_id, status="failed", error=task.get("error_category"))
                    return self.get(inv_id)
                if task["status"] == "failed":
                    self.repo.rw(Q.REQUEUE_TASK, {"tid": task["task_id"]})
                claimed = self._claim(task)
                if claimed is None:
                    self.repo.audit(inv_id, self.worker, "task.claim_conflict", {"task_id": task["task_id"]})
                    self._set(inv_id, status="running")
                    return self.get(inv_id) | {"note": "another worker holds the lease"}
                if prev:
                    self._handoff(prev["task_id"], claimed["task_id"], prev.get("output_ref_ids") or [],
                                  f"{prev['agent_type']} -> {agent_type}")
                self.repo.audit(inv_id, agent_type, "task.started", {"task_id": claimed["task_id"],
                                                                     "attempt": claimed["attempt_count"]})
                try:
                    payload, tool_calls = self._run_stage(agent_type, inv, outputs)
                except (Cancelled,) as exc:
                    self._complete(claimed, status="cancelled", error_category="cancelled")
                    self.repo.audit(inv_id, agent_type, "task.cancelled", {"error": str(exc)})
                    return self.get(inv_id)
                except Exception as exc:  # surface failures; never fabricate completion
                    cat = ("budget" if isinstance(exc, BudgetExceeded) else "tool" if isinstance(exc, ToolError)
                           else "model" if isinstance(exc, LLMError) else "internal")
                    self._complete(claimed, status="failed", error_category=cat, error=str(exc)[:500])
                    self.repo.audit(inv_id, agent_type, "task.failed", {"category": cat, "error": str(exc)[:500],
                                                                        "trace": traceback.format_exc()[-1500:]})
                    if claimed["attempt_count"] >= MAX_ATTEMPTS:
                        self._set(inv_id, status="failed", error=cat, partial_stages=list(outputs))
                        return self.get(inv_id)
                    continue  # retry this stage
                out_id = f"out_{claimed['task_id'][5:]}"
                self.repo.save_artifact("AgentOutput", inv_id, out_id, payload, agent_type=agent_type,
                                        task_id=claimed["task_id"])
                if not self._complete(claimed, status="completed", output_ref_ids=[out_id],
                                      tool_calls=len(tool_calls)):
                    self.repo.audit(inv_id, agent_type, "task.lost_lease", {"task_id": claimed["task_id"]})
                    return self.get(inv_id) | {"note": "lease lost; result not written"}
                self.repo.audit(inv_id, agent_type, "task.completed", {"task_id": claimed["task_id"],
                                                                       "tool_calls": tool_calls[:80]})
                outputs[stage_key] = payload
                task = claimed | {"output_ref_ids": [out_id], "status": "completed"}
                if self.fail_after_stage == stage_key:
                    raise RuntimeError(f"simulated crash after {stage_key}")
            # Red-team defeat => replan once (persisted as its own stages).
            if agent_type == "red_team" and outputs[stage_key].get("output", {}).get("replan_required") \
                    and "containment_planner#replan" not in stages:
                stages[i + 1:i + 1] = ["containment_planner#replan", "red_team#replan"]
            prev = task
            i += 1
        self._set(inv_id, status="completed", completed_at=now_ms())
        self.repo.audit(inv_id, self.worker, "investigation.completed", {"stages": stages})
        return self.get(inv_id)

    # ------------------------------------------------------------------ stages
    def _toolbox(self, agent_type: str, inv: dict[str, Any]) -> ToolBox:
        inv_id = inv["id"]

        def cancelled() -> bool:
            return bool(self.get(inv_id)["status"] == "cancelled")

        return ToolBox(self.repo, agent_type, inv_id, max_calls=BUDGETS[agent_type], timeout_s=120,
                       cancel_check=cancelled)

    def _run_stage(self, agent_type: str, inv: dict[str, Any],
                   outputs: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        meta = self.repo.meta()
        inc = meta["incident"]
        T_inc, T_now, tau = int(inv["T_incident"]), int(inv["T_analysis"]), int(inv["tau_analysis"])
        tb = self._toolbox(agent_type, inv)
        if agent_type == "investigator":
            out, extra = Investigator().run(InvestigatorInput(investigation_id=inv["id"], incident_id=inc["incident_id"],
                                                              T_incident=T_inc, T_now=T_now, tau=tau), tb, self.llm)
            for h in out.hypotheses:
                self.repo.save_artifact("Hypothesis", inv["id"], h.id, h.model_dump(), title=h.title,
                                        path_class=h.path_class or "")
            return {"output": out.model_dump(), "extra": _jsonable(extra)}, tb.calls
        if agent_type == "evidence_verifier":
            iv = InvestigatorOutput.model_validate(outputs["investigator"]["output"])
            out, _ = EvidenceVerifier().run(VerifierInput(investigation_id=inv["id"],
                                                          hypothesis_ids=[h.id for h in iv.hypotheses],
                                                          T_incident=T_inc, tau=tau), iv.hypotheses, tb, T_now,
                                            inc["alerted_identity"],
                                            [p["source_id"] for (p,) in self.repo.ro(Q.INCIDENT_EVIDENCE,
                                                                                     {"iid": inc["incident_id"]})])
            return {"output": out.model_dump()}, tb.calls
        if agent_type == "containment_planner":
            rt_tau = self._latest_tau(outputs, tau)
            out, extra = ContainmentPlanner().run(PlannerInput(investigation_id=inv["id"], T=T_now, tau=rt_tau,
                                                               K=int(inv.get("K", 2)), policy=inv.get("policy",
                                                                                                      "conservative_defense")),
                                                  tb, self.llm, inc["alerted_identity"])
            for p in extra["plans"]:
                self.repo.save_artifact("Plan", inv["id"], p["plan_id"], p, k=p["k"], status=p["status"])
            for cert, lines in extra["certificates"]:
                self.repo.save_artifact("Certificate", inv["id"], cert["certificate_id"],
                                        {"certificate": cert, "export": lines}, status=cert["status"],
                                        k_certified=cert["robustness"]["k_certified"])
            return {"output": out.model_dump(), "plans": extra["plans"]}, tb.calls
        if agent_type == "red_team":
            planner_key = "containment_planner#replan" if "containment_planner#replan" in outputs else "containment_planner"
            po = PlannerOutput.model_validate(outputs[planner_key]["output"])
            rt_tau = self._latest_tau(outputs, tau)
            out, extra = RedTeam().run(RedTeamInput(investigation_id=inv["id"], certificate_ids=po.certificate_ids,
                                                    tau=rt_tau), tb, self.llm, T_now)
            self._write_latent(out, extra["accepted_latent"], inv["id"])
            return {"output": out.model_dump(), "extra": _jsonable(extra)}, tb.calls
        if agent_type == "memory_curator":
            iv = InvestigatorOutput.model_validate(outputs["investigator"]["output"])
            vo = VerifierOutput.model_validate(outputs["evidence_verifier"]["output"])
            planner_key = "containment_planner#replan" if "containment_planner#replan" in outputs else "containment_planner"
            ctx = self.repo.ro(Q.INCIDENT_EVIDENCE, {"iid": inc["incident_id"]})
            ev_ids = sorted(p["source_id"] for (p,) in ctx)
            out, _ = MemoryCurator().run(CuratorInput(investigation_id=inv["id"]), MemoryService(self.repo), inc,
                                         [Hypothesis.model_validate(h) for h in iv.model_dump()["hypotheses"]],
                                         [HypothesisVerdict.model_validate(v) for v in vo.model_dump()["verdicts"]],
                                         outputs[planner_key]["output"], ev_ids, created_at=tau)
            return {"output": out.model_dump()}, []
        raise StageFailure("internal", f"unknown stage {agent_type}")

    @staticmethod
    def _latest_tau(outputs: dict[str, dict[str, Any]], tau: int) -> int:
        rt = outputs.get("red_team")
        if rt and rt.get("output", {}).get("replan_required"):
            return int(rt["output"]["tau_after"])
        return tau

    def _write_latent(self, out: RedTeamOutput, accepted: list[dict[str, Any]], inv_id: str) -> None:
        """Accepted nominations become LATENT facts, learned at the red team's (simulated) knowledge time."""
        existing = {v.edge_id for v in self.repo.all_versions()}
        versions = []
        for e in accepted:
            if e["edge_id"] in existing:
                continue
            versions.append(EdgeVersion(edge_id=e["edge_id"], version=1, type=e["type"], src=e["src"], dst=e["dst"],
                                        src_type=e["src_type"], dst_type=e["dst_type"], workspace_id=self.repo.ws,
                                        tx_from=out.tau_after, kind="latent", template_id=e["template_id"],
                                        verify_cost=int(e["verify_cost"]), valid_open_ended=True,
                                        created_by=f"red_team ({inv_id}) via template engine"))
        if versions:
            self.repo.write_versions(versions)
            self.repo.audit(inv_id, "red_team", "latent.accepted", {"edge_ids": [v.edge_id for v in versions]})


def _jsonable(x: Any) -> Any:
    return json.loads(json.dumps(x, default=str))


def resume_stale(repo: Repository) -> list[str]:
    """On startup: resume investigations left 'running' whose task leases have expired."""
    resumed = []
    for (p,) in repo.ro(Q.LIST_INVESTIGATIONS, {"limit": 50}):
        if p.get("status") == "running":
            tasks = Orchestrator(repo).tasks(p["id"])
            if all(t["status"] != "running" or t.get("lease_expires_at", 0) < now_ms() for t in tasks):
                Orchestrator(repo).run(p["id"])
                resumed.append(p["id"])
    return resumed

