import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { Route } from "../App";
import { PathChips, State, StatusBadge, Synthetic, useAsync } from "../components/common";
import { ParetoChart } from "../components/ParetoChart";
import { AdvisorCard, type Advisor } from "../components/Advisor";
import { ApprovalPanel } from "../components/Approval";
import type { Me } from "../App";
import type { Action, Certificate, GraphData, ParetoPoint } from "../types";

interface ContainmentData {
  planner: { pareto: ParetoPoint[]; sensitivity: any[]; baseline_b0: any; explanation: string; certificate_ids: string[]; advisor?: Advisor } | null;
  plans: { plan_id: string; k: number; status: string; actions: Action[]; total: number | null; optimality: string; certificate_id?: string; iterations: number; nogoods: string[][]; elapsed_ms: number; approval_status?: "approved" | "rejected"; approved_by?: string; rejected_by?: string; decided_at?: number; decision_note?: string; execution?: string }[];
  certificates: { certificate_id: string; status: string; k_certified: number; statement: string }[];
  red_team: { findings: any[]; nominations: any[]; tampering_scenarios: any[]; downgraded_certificate_ids: string[] } | null;
}

export function ContainmentPage({ invId, go, me }: { invId: string; go: (r: Route, inv?: string | null, cert?: string | null) => void; me: Me | null }) {
  const d = useAsync(() => api.get<ContainmentData>(`/api/v1/investigations/${invId}/containment`), [invId]);
  const cands = useAsync(() => api.get<Action[]>(`/api/v1/investigations/${invId}/containment/candidates`), [invId]);
  const graph = useAsync(() => api.get<GraphData>(`/api/v1/investigations/${invId}/graph`), [invId]);
  const [k, setK] = useState(0);
  const [cert, setCert] = useState<Certificate | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [sim, setSim] = useState<Certificate | null>(null);
  const [simErr, setSimErr] = useState<string | null>(null);
  const [simBusy, setSimBusy] = useState(false);
  const plan = d.data?.plans.find((p) => p.k === k);
  const edgeInfo = useMemo(() => Object.fromEntries((graph.data?.edges ?? []).map((e) => [e.edge_id, e])), [graph.data]);

  async function loadCert(cid?: string) {
    if (!cid) return setCert(null);
    const r = await api.get<{ certificate: Certificate }>(`/api/v1/investigations/${invId}/certificate/${cid}`);
    setCert(r.certificate);
  }
  async function simulate() {
    setSimBusy(true); setSimErr(null);
    try {
      const r = await api.post<{ certificate: Certificate }>(`/api/v1/investigations/${invId}/containment/simulate`, { action_ids: [...picked] });
      setSim(r.certificate);
      d.reload();
    } catch (e) { setSimErr((e as Error).message); } finally { setSimBusy(false); }
  }
  const selectK = (kk: number) => setK(kk);
  useEffect(() => { loadCert(plan?.certificate_id); /* eslint-disable-next-line */ }, [plan?.certificate_id]);
  const removed = new Set(plan?.actions.flatMap((a) => a.removes) ?? []);
  const sens = d.data?.planner?.sensitivity.find((s) => s.k === k);

  return (
    <>
      <div className="page-head">
        <div><h1>Containment planner <Synthetic /></h1>
          <p>The deterministic CEGAR solver chooses actions; the model only explains. Every action is a <b>simulation</b> — labeled proposed / simulated / approved, never executed.</p></div>
        <button className="btn" onClick={d.reload}>Refresh</button>
      </div>
      <State loading={d.loading} error={d.error} onRetry={d.reload} empty={!d.data?.planner && "The planner has not completed yet."}>
        {d.data?.planner && (
          <>
            <div className="grid g2">
              <section className="card"><h2>Price of Certainty</h2>
                <ParetoChart points={d.data.planner.pareto} selected={k} onSelect={selectK} />
                <p className="small">{d.data.planner.explanation}</p>
              </section>
              <section className="card"><h2>Why not just disable the account?</h2>
                <div className={`callout ${d.data.planner.baseline_b0.status === "contained" ? "ok" : "bad"}`}>
                  <b>{d.data.planner.baseline_b0.label}</b>: <StatusBadge value={d.data.planner.baseline_b0.status} />
                  {d.data.planner.baseline_b0.residual_confirmed_paths.map((p: string[], i: number) => (
                    <div key={i} style={{ marginTop: 6 }}><span className="small muted">Residual CONFIRMED path:</span><PathChips ids={p} classes={edgeInfo} /></div>
                  ))}
                </div>
                <h3 style={{ marginTop: 14 }}>Evidence sensitivity (R4) at k={k}</h3>
                {sens ? (sens.differs ? (
                  <div className="callout warn small">Plans differ between trust policies.
                    <ul className="tight">{sens.only_conservative.map((a: string) => <li key={a}>only under conservative_defense: <code>{a}</code></li>)}
                      {sens.only_trust_filtered.map((a: string) => <li key={a}>only under trust_filtered: <code>{a}</code></li>)}</ul>
                    Conservative total {sens.conservative.total} vs trust-filtered {sens.trust_filtered.total}.</div>
                ) : <p className="small muted">Same plan under both trust policies.</p>) : <p className="muted small">n/a</p>}
              </section>
            </div>
            <AdvisorCard advisor={d.data.planner.advisor} onOpenCert={(cid) => go("certificate", invId, cid)} />
            {plan && (
              <section className="card" style={{ marginTop: 16 }}>
                <div className="row between"><h2>Plan at k = {k}</h2>
                  <div className="row"><StatusBadge value={plan.status} /><StatusBadge value={plan.optimality} />
                    <span className="small muted">{plan.iterations} CEGAR iterations · {plan.elapsed_ms} ms</span>
                    {plan.certificate_id && <button className="btn sm primary" onClick={() => go("certificate", invId, plan.certificate_id)}>Open certificate →</button>}</div></div>
                <div className="scroll" tabIndex={0}><table>
                  <thead><tr><th>Action</th><th>Target</th><th>Cuts (κ)</th><th>Cost & basis</th><th>Reversibility</th><th>Mode</th><th>Scrutiny</th></tr></thead>
                  <tbody>{plan.actions.map((a) => {
                    const scr = cert?.requires_human_scrutiny.find((s) => s.action_id === a.id);
                    return (<tr key={a.id}><td><b>{a.type.replaceAll("_", " ")}</b></td><td className="mono">{a.target_id}</td>
                      <td className="small mono">{a.removes.join(", ")}</td><td>{a.cost} <span className="small muted">— {a.cost_basis}</span></td>
                      <td className="small">{a.reversibility}</td><td><StatusBadge value="simulated" /></td>
                      <td>{scr ? <span className="badge b-bad" title={scr.reason}>⚑ requires human scrutiny</span> : <span className="muted small">—</span>}</td></tr>);
                  })}</tbody></table></div>
                <div style={{ marginTop: 12 }}>
                  <ApprovalPanel invId={invId} plan={plan} me={me} onDone={d.reload}
                    scrutiny={cert?.requires_human_scrutiny.map((x) => x.action_id) ?? []} />
                </div>
                {cert && (
                  <div className="grid g2" style={{ marginTop: 12 }}>
                    <div><h3>Assumption frontier</h3>
                      {cert.robustness.min_reopening_latent_edges === null ? <p className="small">No path survives even if every latent edge were true (within the modeled graph).</p> : (<>
                        <p className="small">Cheapest reopening needs <b>{cert.robustness.min_reopening_latent_edges}</b> unverified edge(s). Witness:</p>
                        {cert.robustness.witness_paths.map((p, i) => <PathChips key={i} ids={p} classes={edgeInfo} cut={removed} />)}
                        <h4 style={{ marginTop: 8 }}>Verify these first to close the gap</h4>
                        <ol className="tight small">{cert.robustness.verification_priority.map((v) => <li key={v.edge_id}><code>{v.edge_id}</code> — {v.template} (verify cost {v.verify_cost})</li>)}</ol></>)}
                    </div>
                    <div><h3>Flows</h3>
                      <ul className="tight small">{cert.flows.map((f) => <li key={f.flow_id}>{f.preserved ? "✔" : "✕"} <code>{f.flow_id}</code> ({f.kind}{f.kind === "soft" ? `, weight ${f.weight}` : ""}) {f.preserved ? "preserved" : "broken"}</li>)}</ul>
                      <p className="small">Cost: operational {cert.cost.operational} + soft-flow penalty {cert.cost.soft_flow_penalty} = <b>{cert.cost.total}</b></p>
                      {!!cert.disputed_removals.length && <p className="small">Disputed removals still counted (R2): {cert.disputed_removals.map((x) => <code key={x}>{x} </code>)}</p>}
                    </div>
                  </div>
                )}
              </section>
            )}
            <div className="grid g2" style={{ marginTop: 16 }}>
              <section className="card"><h2>Simulate an action set</h2>
                <p className="small muted">Pick actions and click Simulate. The result is a certificate: <b>contained</b> or <b>not contained</b> with residual paths. Nothing is executed.</p>
                <State loading={cands.loading} error={cands.error}>
                  <div className="scroll" tabIndex={0} style={{ maxHeight: 280 }}>
                    <table className="small"><tbody>{cands.data?.map((a) => (
                      <tr key={a.id}><td><label className="row"><input type="checkbox" checked={picked.has(a.id)}
                        onChange={(e) => { const n = new Set(picked); if (e.target.checked) n.add(a.id); else n.delete(a.id); setPicked(n); }} />
                        <span className="mono">{a.id}</span></label></td><td>{a.cost}</td></tr>))}</tbody></table>
                  </div>
                </State>
                <div className="row" style={{ marginTop: 8 }}><button className="btn primary" onClick={simulate} disabled={simBusy}>{simBusy ? "Simulating…" : "Simulate (explicit click)"}</button></div>
                {simErr && <div className="callout bad small" role="alert">{simErr}</div>}
                {sim && (
                  <div className={`callout ${sim.status === "contained" ? "ok" : "bad"} small`} style={{ marginTop: 8 }} aria-live="polite">
                    <b>{sim.status === "contained" ? "Contained" : "NOT contained"}</b> — total cost {sim.cost.total}; reopening distance {sim.robustness.min_reopening_latent_edges ?? "∞"}
                    {sim.residual_confirmed_paths.map((p, i) => <div key={i}>Residual: <PathChips ids={p} classes={edgeInfo} /></div>)}
                    {sim.flows.filter((f) => !f.preserved && f.kind === "hard").map((f) => <div key={f.flow_id}>Breaks hard flow <code>{f.flow_id}</code></div>)}
                    <div><button className="btn sm" onClick={() => go("certificate", invId, sim.certificate_id)}>Open certificate</button></div>
                  </div>
                )}
              </section>
              <section className="card"><h2>Red team</h2>
                {d.data.red_team ? (<>
                  <ul className="tight small">{d.data.red_team.findings.map((f) => <li key={f.certificate_id}><code>{f.certificate_id}</code> ({f.d_before === null ? "fully robust" : `k=${f.k_certified}`}): {f.result}</li>)}</ul>
                  <h4 style={{ marginTop: 8 }}>Latent nominations ({d.data.red_team.nominations.filter((n) => n.accepted).length} accepted / {d.data.red_team.nominations.length})</h4>
                  <ul className="tight small">{d.data.red_team.nominations.map((n, i) => <li key={i}>{n.accepted ? "✔" : "✕"} {n.template_id}: <code>{n.src}</code> → <code>{n.dst}</code> <span className="muted">— {n.reason}</span></li>)}</ul>
                  <h4 style={{ marginTop: 8 }}>Evidence-tampering scenarios</h4>
                  <ul className="tight small">{d.data.red_team.tampering_scenarios.slice(0, 6).map((t, i) => <li key={i}>Forge/suppress <code>{t.forge_or_suppress.join(", ")}</code> → {t.effect}</li>)}</ul>
                </>) : <p className="muted">Red team has not run yet.</p>}
              </section>
            </div>
          </>
        )}
      </State>
    </>
  );
}
