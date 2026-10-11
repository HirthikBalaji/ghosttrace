import { useState } from "react";
import { api, fmt, isoOf } from "../api";
import type { Route } from "../App";
import { PathChips, State, StatusBadge, Synthetic, useAsync } from "../components/common";
import type { Certificate } from "../types";

interface VerifyResult { exit_code: number; accepted: boolean; output: string; stderr: string; command: string }

export function CertificatePage({ invId, certId, go }: { invId: string; certId: string | null; go: (r: Route, inv?: string | null, cert?: string | null) => void }) {
  const list = useAsync(() => api.get<{ certificates: { certificate_id: string; status: string; k_certified: number; statement: string }[] }>(`/api/v1/investigations/${invId}/containment`), [invId]);
  const cid = certId ?? list.data?.certificates[0]?.certificate_id ?? null;
  const c = useAsync(() => (cid ? api.get<{ certificate: Certificate }>(`/api/v1/investigations/${invId}/certificate/${cid}`) : Promise.resolve(null)), [invId, cid]);
  const [v, setV] = useState<VerifyResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [showJson, setShowJson] = useState(false);
  const cert = c.data?.certificate;

  async function verify() {
    if (!cid) return;
    setBusy(true);
    try { setV(await api.post<VerifyResult>(`/api/v1/investigations/${invId}/certificate/${cid}/verify`)); }
    catch (e) { setV({ exit_code: -1, accepted: false, output: (e as Error).message, stderr: "", command: "" }); }
    finally { setBusy(false); }
  }
  async function download() {
    if (!cid || !cert) return;
    const edges = await api.text(`/api/v1/investigations/${invId}/certificate/${cid}/export`);
    for (const [name, body, type] of [[`${cid}.json`, JSON.stringify(cert, null, 2), "application/json"], [`${cid}.edges.jsonl`, edges, "application/x-ndjson"]] as const) {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([body], { type }));
      a.download = name;
      a.click();
      URL.revokeObjectURL(a.href);
    }
  }

  return (
    <>
      <div className="page-head">
        <div><h1>Certificates <Synthetic /></h1>
          <p>Machine-checkable claims with their assumptions. Verification runs the stdlib-only <code>verifier/</code> package in a separate process; it shares no code with the planner.</p></div>
      </div>
      <div className="grid" style={{ gridTemplateColumns: "300px minmax(0,1fr)" }}>
        <aside className="card" aria-label="Certificate list">
          <h3>All certificates</h3>
          <State loading={list.loading} error={list.error} empty={list.data?.certificates.length === 0 && "No certificates yet."}>
            <ul className="tight small" style={{ listStyle: "none", padding: 0 }}>
              {list.data?.certificates.map((x) => (
                <li key={x.certificate_id} style={{ marginBottom: 8 }}>
                  <button className="btn sm" aria-current={x.certificate_id === cid ? "true" : undefined} onClick={() => { setV(null); go("certificate", invId, x.certificate_id); }}>
                    <code>{x.certificate_id}</code></button>{" "}<StatusBadge value={x.status} /> <span className="muted">{x.status === "contained" ? `k=${x.k_certified}` : ""}</span>
                </li>
              ))}
            </ul>
          </State>
        </aside>
        <section className="card" aria-label="Certificate">
          <State loading={c.loading} error={c.error} onRetry={c.reload} empty={!cert && "Select a certificate."}>
            {cert && (
              <div className="stack">
                <div className="row between">
                  <h2><code>{cert.certificate_id}</code></h2>
                  <div className="row"><StatusBadge value={cert.status} /><StatusBadge value={cert.optimality.status} /><StatusBadge value={cert.mode} /></div>
                </div>
                <div className={`callout ${cert.status === "contained" ? "ok" : "bad"}`}><b>Statement.</b> {cert.statement}</div>
                <div className="row">
                  <button className="btn primary" onClick={verify} disabled={busy}>{busy ? "Verifying…" : "Verify with independent verifier"}</button>
                  <button className="btn" onClick={download}>Download certificate + export</button>
                  <button className="btn" aria-pressed={showJson} onClick={() => setShowJson(!showJson)}>{showJson ? "Hide" : "Show"} raw JSON</button>
                </div>
                {v && (
                  <div className={`callout ${v.accepted ? "ok" : "bad"}`} role="status">
                    <b>{v.accepted ? "ACCEPTED" : "REJECTED"}</b> (exit code {v.exit_code}) — <code>{v.command}</code>
                    <pre className="json" style={{ marginTop: 6 }}>{v.output}{v.stderr ? `\n${v.stderr}` : ""}</pre>
                  </div>
                )}
                <dl className="kv">
                  <dt>World time T</dt><dd>{fmt(isoOf(cert.world_time_T))}</dd>
                  <dt>Knowledge τ</dt><dd>{fmt(isoOf(cert.knowledge_time_tau))}</dd>
                  <dt>Snapshot</dt><dd className="mono">{cert.snapshot_hash}</dd>
                  <dt>Trust policy</dt><dd>{cert.trust_policy}</dd>
                  <dt>Sources → targets</dt><dd>{cert.sources.join(", ")} → {cert.targets.join(", ")}</dd>
                  <dt>Robustness</dt><dd>k-certified {cert.robustness.k_certified}; reopening distance {cert.robustness.min_reopening_latent_edges ?? "∞"}</dd>
                  <dt>Cost</dt><dd>{cert.cost.operational} + {cert.cost.soft_flow_penalty} = {cert.cost.total}</dd>
                  <dt>Optimality</dt><dd>{cert.optimality.status} — {cert.optimality.search_space}{cert.optimality.gap !== null ? `; gap ${cert.optimality.gap}` : ""}</dd>
                </dl>
                {!!cert.residual_confirmed_paths.length && (<div><h3>Residual CONFIRMED paths</h3>{cert.residual_confirmed_paths.map((p, i) => <PathChips key={i} ids={p} />)}</div>)}
                <div className="grid g2">
                  <div><h3>Assumptions</h3><ul className="tight small">{cert.assumptions.map((a) => <li key={a}>{a}</li>)}</ul></div>
                  <div><h3>Limitations</h3><ul className="tight small">{cert.limitations.map((a) => <li key={a}>{a}</li>)}</ul></div>
                </div>
                <div><h3>Load-bearing evidence (R5)</h3>
                  {cert.load_bearing_detail?.length ? (
                    <table className="small"><thead><tr><th>If these records were false…</th><th>…the certificate fails because</th></tr></thead>
                      <tbody>{cert.load_bearing_detail.map((l, i) => <tr key={i}><td>{l.sources.map((s) => <code key={s}>{s} </code>)}</td><td>{l.invalidates}</td></tr>)}</tbody></table>
                  ) : <p className="small muted">{cert.status === "contained" ? "None found up to the analysed set size." : "Not computed for non-contained plans."}</p>}
                </div>
                {!!cert.requires_human_scrutiny.length && (
                  <div className="callout warn small"><b>Requires human scrutiny (R3):</b>
                    <ul className="tight">{cert.requires_human_scrutiny.map((s) => <li key={s.action_id}><code>{s.action_id}</code> — {s.reason} ({s.false_flag_edges.join(", ")})</li>)}</ul></div>
                )}
                {showJson && <pre className="json">{JSON.stringify(cert, null, 2)}</pre>}
              </div>
            )}
          </State>
        </section>
      </div>
    </>
  );
}
