import { useState } from "react";
import { api, fmt, isoOf } from "../api";
import { State, StatusBadge, Synthetic, useAsync } from "../components/common";
import type { Handoff, Memory, Task } from "../types";

interface AuditEvent { id: string; at: number; actor: string; action: string; detail: any }

export function MemoryAuditPage({ invId }: { invId: string | null }) {
  const mem = useAsync(() => api.get<Memory[]>("/api/v1/memory"), []);
  const audit = useAsync(() => (invId ? api.get<AuditEvent[]>(`/api/v1/audit/${invId}`) : Promise.resolve([])), [invId]);
  const inv = useAsync(() => (invId ? api.get<{ tasks: Task[]; handoffs: Handoff[] }>(`/api/v1/investigations/${invId}`) : Promise.resolve(null)), [invId]);
  const [filter, setFilter] = useState("all");
  const rows = (mem.data ?? []).filter((m) => filter === "all" || (filter === "tainted" ? m.taint : m.category === filter));

  async function exportReport(fmtName: "md" | "json") {
    if (!invId) return;
    const body = fmtName === "md" ? await api.text(`/api/v1/investigations/${invId}/report?format=md`)
      : JSON.stringify(await api.get(`/api/v1/investigations/${invId}/report?format=json`), null, 2);
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([body], { type: fmtName === "md" ? "text/markdown" : "application/json" }));
    a.download = `ghosttrace-${invId}.${fmtName}`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  return (
    <>
      <div className="page-head">
        <div><h1>Memory & audit <Synthetic /></h1>
          <p>Durable memory lives in the workspace graph with provenance (DERIVED_FROM source records), scope, freshness and taint. Tainted memory is visible but cannot be promoted or used for a certificate.</p></div>
        {invId && <div className="row"><button className="btn" onClick={() => exportReport("md")}>Export report (Markdown)</button><button className="btn" onClick={() => exportReport("json")}>Export report (JSON)</button></div>}
      </div>
      <section className="card">
        <div className="row between"><h2>Memory</h2>
          <label className="row small">Filter<select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="all">all</option><option value="episodic">episodic</option><option value="semantic">semantic</option>
            <option value="procedural">procedural</option><option value="tainted">tainted</option></select></label></div>
        <State loading={mem.loading} error={mem.error} onRetry={mem.reload} empty={rows.length === 0 && "No memory entries."}>
          <div className="scroll" tabIndex={0}><table>
            <thead><tr><th>Memory</th><th>Category</th><th>Content</th><th>Provenance</th><th>Scope</th><th>Status</th><th>Taint</th><th>Fresh until</th></tr></thead>
            <tbody>{rows.map((m) => (
              <tr key={m.memory_id}>
                <td className="mono small">{m.memory_id}{m.promoted_from && <div className="muted">promoted from {m.promoted_from}</div>}</td>
                <td><span className={`badge ${m.category === "semantic" ? "b-ok" : m.category === "procedural" ? "b-derived" : "b-neutral"}`}>{m.category}</span></td>
                <td className="small" style={{ maxWidth: 420 }}>{m.content}</td>
                <td className="small mono">{m.source_ids.join(", ")}</td>
                <td className="small">{m.scope}{m.investigation_id ? <div className="mono muted">{m.investigation_id}</div> : null}</td>
                <td><StatusBadge value={m.status === "active" ? "completed" : m.status} />{m.status === "active" && <span className="sr-only"> active</span>}</td>
                <td>{m.taint ? <span className="badge b-bad" title={m.taint_reasons.join("; ")}>⚑ tainted</span> : <span className="badge b-ok">clean</span>}
                  {m.taint && <div className="small muted">{m.taint_reasons.join("; ")}</div>}</td>
                <td className="small">{fmt(isoOf(m.expires_at))}</td>
              </tr>))}</tbody></table></div>
        </State>
      </section>
      {invId && (
        <div className="grid g2" style={{ marginTop: 16 }}>
          <section className="card"><h2>Handoffs</h2>
            <State loading={inv.loading} error={inv.error} empty={!inv.data?.handoffs.length && "No handoffs yet."}>
              <ol className="tight small">{inv.data?.handoffs.map((h) => (
                <li key={h.from_task + h.to_task}><b>{h.from_agent}</b> → <b>{h.to_agent}</b> at {fmt(isoOf(h.at))} <span className="muted">refs {h.refs.join(", ")}</span></li>))}</ol>
            </State>
          </section>
          <section className="card"><h2>Audit trail</h2>
            <State loading={audit.loading} error={audit.error} empty={!audit.data?.length && "No audit events."}>
              <ol className="tight small" tabIndex={0} aria-label="Audit events" style={{ maxHeight: 420, overflow: "auto" }}>{audit.data?.map((a) => (
                <li key={a.id}><span className="mono">{fmt(isoOf(a.at))}</span> <b>{a.actor}</b> {a.action}
                  {a.detail?.tool_calls && <span className="muted"> — {a.detail.tool_calls.length} tool calls: {[...new Set(a.detail.tool_calls.map((t: any) => t.tool))].join(", ")}</span>}
                  {a.detail?.accepted !== undefined && <span> — verifier {a.detail.accepted ? "ACCEPTED" : "REJECTED"}</span>}
                </li>))}</ol>
            </State>
          </section>
        </div>
      )}
    </>
  );
}
