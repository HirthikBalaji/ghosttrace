"""Human approval of a certified plan.

Approval records a human decision that a simulated, certified plan may be carried out. This build contains no
executor: nothing is changed in any real system, and the plan's mode becomes `approved`, never `executed`.

Gates, all enforced server-side:
  1. the principal holds the `approve` permission (route dependency);
  2. four-eyes: in OIDC mode an approver may not approve an investigation they created (GT_REQUIRE_FOUR_EYES);
  3. the plan is `contained` and its certificate is re-checked by the independent verifier at approval time;
  4. actions flagged `requires_human_scrutiny` must be acknowledged explicitly.
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.graph import queries as Q
from app.graph.repository import Repository, now_ms
from app.security.auth import Principal
from app.security.verifier_runner import run_verifier


class ApprovalError(Exception):
    def __init__(self, status: int, message: str, details: Any = None):
        super().__init__(message)
        self.status = status
        self.details = details


def decide(
    repo: Repository, inv: dict[str, Any], plan_id: str, p: Principal, decision: str, note: str, acknowledge_scrutiny: bool
) -> dict[str, Any]:
    if decision not in ("approved", "rejected"):
        raise ApprovalError(422, "decision must be 'approved' or 'rejected'")
    plan = repo.get_artifact("Plan", plan_id)
    if not plan or plan.get("investigation_id") != inv["id"]:
        raise ApprovalError(404, "plan not found in this investigation")
    if plan.get("approval_status") in ("approved", "rejected"):
        raise ApprovalError(409, f"plan already {plan['approval_status']}")
    if get_settings().require_four_eyes and p.mode == "oidc" and inv.get("created_by") == p.subject:
        raise ApprovalError(403, "four-eyes rule: the creator of an investigation cannot approve its plans")
    body = plan["payload"]
    verification: dict[str, Any] | None = None
    if decision == "approved":
        cid = body.get("certificate_id")
        if body.get("status") != "contained" or not cid:
            raise ApprovalError(409, "only contained plans with a certificate can be approved")
        art = repo.get_artifact("Certificate", cid)
        if not art:
            raise ApprovalError(409, "certificate missing")
        cert = art["payload"]["certificate"]
        verification = run_verifier(cert, art["payload"]["export"], cid)
        if not verification["accepted"]:
            raise ApprovalError(409, "independent verifier rejected the certificate", verification["output"])
        flagged = [s["action_id"] for s in cert.get("requires_human_scrutiny", [])]
        if flagged and not acknowledge_scrutiny:
            raise ApprovalError(409, "actions require explicit human scrutiny acknowledgement", flagged)
    props = {
        "approval_status": decision,
        "approved_by" if decision == "approved" else "rejected_by": p.subject,
        "decided_at": now_ms(),
        "decision_note": note[:1000],
        "scrutiny_acknowledged": bool(acknowledge_scrutiny),
        "mode": "approved" if decision == "approved" else "proposed",
        "execution": "none: this build has no executor; approval records human authorisation only",
    }
    rows = repo.rw(Q.UPDATE_ARTIFACT["Plan"], {"id": plan_id, "props": props})
    repo.audit(
        inv["id"],
        p.subject,
        f"plan.{decision}",
        {"plan_id": plan_id, "note": note[:1000], "roles": sorted(p.roles), "verifier": verification},
    )
    return {"plan": dict(rows[0][0]) if rows else props, "verification": verification}
