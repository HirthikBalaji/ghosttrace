import { useState } from "react";
import { api, fmt, isoOf } from "../api";
import type { Me } from "../App";

export interface PlanApproval {
  plan_id: string;
  status: string;
  certificate_id?: string;
  approval_status?: "approved" | "rejected";
  approved_by?: string;
  rejected_by?: string;
  decided_at?: number;
  decision_note?: string;
  execution?: string;
}

// Human decision on a certified plan. Approval is a recorded authorisation, never an execution.
export function ApprovalPanel({ invId, plan, scrutiny, me, onDone }: {
  invId: string; plan: PlanApproval; scrutiny: string[]; me: Me | null; onDone: () => void;
}) {
  const [note, setNote] = useState("");
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (plan.status !== "contained" || !plan.certificate_id) return null;
  if (plan.approval_status) {
    return (
      <div className={`callout ${plan.approval_status === "approved" ? "ok" : "warn"} small`} role="status">
        <b>{plan.approval_status === "approved" ? "Approved" : "Rejected"}</b> by <code>{plan.approved_by ?? plan.rejected_by}</code>
        {plan.decided_at ? ` at ${fmt(isoOf(plan.decided_at))}` : ""}{plan.decision_note ? ` — “${plan.decision_note}”` : ""}
        <div className="muted">{plan.execution}</div>
      </div>
    );
  }
  const canApprove = !!me?.roles.some((r) => r === "approver" || r === "admin");
  async function decide(decision: "approved" | "rejected") {
    setBusy(true); setErr(null);
    try {
      await api.post(`/api/v1/investigations/${invId}/plans/${plan.plan_id}/decision`, { decision, note, acknowledge_scrutiny: ack });
      onDone();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  return (
    <div className="callout small" aria-label="Human approval">
      <b>Human approval</b> — records an authorisation for this certified plan. The certificate is re-verified independently at
      approval time. Nothing is executed by this system.
      {!canApprove && <p className="muted">Your roles ({me?.roles.join(", ") || "none"}) cannot approve plans; an approver must.</p>}
      {canApprove && (
        <div className="stack" style={{ marginTop: 8 }}>
          <label className="field">Decision note
            <input type="text" value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} placeholder="what you checked" />
          </label>
          {scrutiny.length > 0 && (
            <label className="row"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />
              I have independently checked the scrutiny-flagged action(s): <code>{scrutiny.join(", ")}</code></label>
          )}
          <div className="row">
            <button className="btn primary" disabled={busy || (scrutiny.length > 0 && !ack)} onClick={() => decide("approved")}>Approve plan</button>
            <button className="btn danger" disabled={busy} onClick={() => decide("rejected")}>Reject</button>
          </div>
          {err && <div className="callout bad" role="alert">{err}</div>}
        </div>
      )}
    </div>
  );
}
