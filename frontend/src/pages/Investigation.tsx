import { useCallback, useEffect, useMemo, useState } from "react";
import { api, fmt, isoOf, qs, stream } from "../api";
import type { Route } from "../App";
import { ClassBadge, FlagBadges, State, StatusBadge, Synthetic, useAsync } from "../components/common";
import { GraphView, Legend } from "../components/GraphView";
import type { GEdge, GraphData, Handoff, Hypothesis, Investigation, Source, Task } from "../types";

const STAGES = ["investigator", "evidence_verifier", "containment_planner", "red_team", "memory_curator"];
const DAY = 86_400_000;

export function useInvestigation(invId: string) {
  const [state, setState] = useState<{ investigation: Investigation; tasks: Task[]; handoffs: Handoff[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState<"stream" | "poll" | "idle">("idle");
  useEffect(() => {
    let alive = true;
    let timer: number | undefined;
    const ctl = new AbortController();
    const load = async () => {
      const d = await api.get<{ investigation: Investigation; tasks: Task[]; handoffs: Handoff[] }>(`/api/v1/investigations/${invId}`);
      if (alive) { setState(d); setError(null); }
      return d;
    };
    const poll = async () => {
      try {
        const d = await load();
        if (alive && ["running", "created"].includes(d.investigation.status)) { setLive("poll"); timer = window.setTimeout(poll, 900); }
        else if (alive) setLive("idle");
      } catch (e) { if (alive) setError((e as Error).message); }
    };
    (async () => {
      try {
        const d = await load();
        if (!["running", "created"].includes(d.investigation.status)) return;
        setLive("stream");
        await stream(`/api/v1/investigations/${invId}/events`, () => { load().catch(() => undefined); }, ctl.signal);
        if (alive) { await load(); setLive("idle"); }
      } catch (e) {
        if (alive && (e as Error).name !== "AbortError") poll(); // streaming unavailable: fall back to polling
      }
    })();
    return () => { alive = false; ctl.abort(); if (timer) clearTimeout(timer); };
  }, [invId]);
  return { state, error, live };
}

export function Pipeline({ tasks }: { tasks: Task[] }) {
  return (
    <ol className="pipeline" aria-label="Agent pipeline" style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {STAGES.map((s) => {
        const t = [...tasks].reverse().find((x) => x.agent_type === s);
        const st = t?.status ?? "pending";
        return (
          <li key={s} className={`stage ${st}`}>
            <b>{s.replaceAll("_", " ")}</b>
            <span className="small row">{t ? <StatusBadge value={st} /> : <span className="badge b-neutral">pending</span>}
              {t && t.attempt_count > 1 && <span className="muted">attempt {t.attempt_count}</span>}
              {t?.tool_calls !== undefined && <span className="muted">{t.tool_calls} tool calls</span>}</span>
            {t?.error && <span className="small" style={{ color: "var(--bad)" }}>{t.error_category}: {t.error}</span>}
          </li>
        );
      })}
    </ol>
  );
}

function TimeControls({ inv, T, tau, setT, setTau }: { inv: Investigation; T: number; tau: number; setT: (n: number) => void; setTau: (n: number) => void }) {
  const lo = inv.T_incident - 365 * DAY, hi = inv.T_analysis;
  const step = 3_600_000;
  return (
    <div className="card" aria-label="Time controls">
      <div className="timectl">
        <label className="field">World time T — when facts were true: <b className="mono">{fmt(isoOf(T))}</b>
          <input type="range" min={lo} max={hi} step={step} value={T} onChange={(e) => setT(Number(e.target.value))} aria-valuetext={isoOf(T)} />
        </label>
        <label className="field">Knowledge time τ — what we knew by then: <b className="mono">{fmt(isoOf(tau))}</b>
          <input type="range" min={lo} max={hi} step={step} value={tau} onChange={(e) => setTau(Number(e.target.value))} aria-valuetext={isoOf(tau)} />
        </label>
        <div className="row">
          <button className="btn sm" onClick={() => { setT(inv.T_incident); setTau(inv.T_incident); }}>Incident, as known then</button>
          <button className="btn sm" onClick={() => { setT(inv.T_incident); setTau(inv.tau_analysis); }}>Incident, as known now</button>
          <button className="btn sm" onClick={() => { setT(inv.T_analysis); setTau(inv.tau_analysis); }}>Now</button>
        </div>
      </div>
    </div>
  );
}

export function EdgeDetail({ edge, invId, sources }: { edge: GEdge | null; invId: string; sources: Record<string, Source> }) {
  const [hist, setHist] = useState<any[] | null>(null);
  useEffect(() => setHist(null), [edge]);
  if (!edge) return <p className="muted small">Select an edge in the graph or table to see its provenance, validity and why it exists.</p>;
  const why = edge.kind === "latent" ? `Latent candidate from allowlisted template “${edge.template_id}”, accepted because its graph preconditions hold. Not observed.`
    : edge.kind === "derived" ? `Derived by rule “${edge.rule_id}” from parent facts ${edge.parent_ids?.join(", ")}.`
    : edge.temporal === "INACTIVE" ? "Known fact, but not valid at the selected world time T."
    : `Asserted by ${edge.source_ids?.length ?? 0} source record(s); class computed by rules R1–R3.`;
  return (
    <div className="stack" aria-live="polite">
      <div className="row"><ClassBadge value={edge.temporal === "ACTIVE" ? edge.cls : edge.temporal} /><FlagBadges flags={edge.flags} /></div>
      <dl className="kv">
        <dt>Edge</dt><dd className="mono">{edge.edge_id} (v{edge.version})</dd>
        <dt>Relationship</dt><dd><code>{edge.src}</code> —{edge.type}→ <code>{edge.dst}</code></dd>
        <dt>Valid</dt><dd>[{fmt(edge.valid_from)}, {edge.valid_to ? fmt(edge.valid_to) : edge.valid_open_ended ? "open-ended (asserted)" : "unknown"})</dd>
        <dt>Known since</dt><dd>{fmt(edge.tx_from)}{edge.tx_to ? ` until ${fmt(edge.tx_to)}` : ""}</dd>
        {edge.template_id && <><dt>Verify cost</dt><dd>{edge.verify_cost}</dd></>}
        <dt>Why it exists</dt><dd>{why}</dd>
      </dl>
      {edge.note && <p className="small muted">{edge.note}</p>}
      {!!edge.source_ids?.length && (
        <div><h4>Supporting sources</h4>
          <ul className="tight small">{edge.source_ids.map((s) => <SourceLine key={s} s={sources[s]} id={s} />)}</ul></div>
      )}
      {!!edge.dispute_source_ids?.length && (
        <div className="callout warn small"><b>Disputed removal (R2):</b> a removal claim exists but does not remove the edge.
          <ul className="tight">{edge.dispute_source_ids.map((s) => <SourceLine key={s} s={sources[s]} id={s} />)}</ul></div>
      )}
      {!!edge.valid_to_source_ids?.length && (
        <div className="small"><h4>Closed by</h4><ul className="tight">{edge.valid_to_source_ids.map((s) => <SourceLine key={s} s={sources[s]} id={s} />)}</ul></div>
      )}
      <button className="btn sm" onClick={async () => setHist(await api.get<any[]>(`/api/v1/investigations/${invId}/edges/${encodeURIComponent(edge.edge_id)}/history`))}>
        Show bitemporal history
      </button>
      {hist && (
        <table className="small"><thead><tr><th>v</th><th>valid</th><th>known</th></tr></thead>
          <tbody>{hist.map((h) => <tr key={h.version}><td>{h.version}</td>
            <td>[{fmt(h.valid_from_iso)}, {h.valid_to_iso ? fmt(h.valid_to_iso) : h.valid_open_ended ? "open" : "?"})</td>
            <td>[{fmt(h.tx_from_iso)}, {h.tx_to_iso ? fmt(h.tx_to_iso) : "now"})</td></tr>)}</tbody></table>
      )}
    </div>
  );
}

function SourceLine({ s, id }: { s?: Source; id: string }) {
  if (!s) return <li><code>{id}</code> <span className="muted">(not loaded)</span></li>;
  return (
    <li><code>{id}</code> — {s.system} · integrity <b>{s.integrity}</b> · trust {s.trust_class}
      {s.attacker_influenceable && <span className="badge b-bad" style={{ marginLeft: 4 }}>⚑ attacker-influenceable</span>}
      {s.contains_instructions && <span className="badge b-bad" style={{ marginLeft: 4 }}>⚠ embedded instructions (data only)</span>}
      <div className="muted">“{s.content}”</div></li>
  );
}

export function InvestigationPage({ invId, go }: { invId: string; go: (r: Route, inv?: string | null, cert?: string | null) => void }) {
  const { state, error, live } = useInvestigation(invId);
  const inv = state?.investigation;
  const [T, setT] = useState<number | null>(null);
  const [tau, setTau] = useState<number | null>(null);
  const [policy, setPolicy] = useState("conservative_defense");
  const [sel, setSel] = useState<GEdge | null>(null);
  const [view, setView] = useState<"graph" | "table">("graph");
  const [hyp, setHyp] = useState<string | null>(null);
  const [labels, setLabels] = useState(false);
  useEffect(() => { if (inv && T === null) { setT(inv.T_analysis); setTau(inv.tau_analysis); } }, [inv, T]);
  const [dT, setDT] = useState<[number, number] | null>(null);
  useEffect(() => { if (T === null || tau === null) return; const h = setTimeout(() => setDT([T, tau]), 250); return () => clearTimeout(h); }, [T, tau]);
  const graph = useAsync(() => dT ? api.get<GraphData>(`/api/v1/investigations/${invId}/graph${qs({ T: dT[0], tau: dT[1], policy })}`) : Promise.resolve(null as any), [invId, dT?.[0], dT?.[1], policy]);
  const ev = useAsync(() => api.get<Source[]>(`/api/v1/investigations/${invId}/evidence`), [invId]);
  const hy = useAsync(() => api.get<{ investigator: { hypotheses: Hypothesis[]; reasoning_summary: string } | null }>(`/api/v1/investigations/${invId}/hypotheses`), [invId, inv?.status]);
  const sources = useMemo(() => Object.fromEntries((ev.data ?? []).map((s) => [s.source_id, s])), [ev.data]);
  const hl = useMemo(() => {
    const h = hy.data?.investigator?.hypotheses.find((x) => x.id === hyp);
    return new Set(h?.paths[0]?.edge_ids ?? []);
  }, [hy.data, hyp]);
  const onEdge = useCallback((e: GEdge) => setSel(e), []);

  async function run() { await api.post(`/api/v1/investigations/${invId}/run`); window.location.reload(); }
  async function cancel() { await api.post(`/api/v1/investigations/${invId}/cancel`); window.location.reload(); }

  if (error) return <State error={error} />;
  if (!inv || !state) return <State loading />;
  const incidentEvidence = (ev.data ?? []).filter((s) => s.incident_evidence);
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{inv.title} <Synthetic /></h1>
          <p>Investigation <code>{inv.id}</code> · <StatusBadge value={inv.status} /> · analysis clock T = {fmt(isoOf(inv.T_analysis))} ({inv.clock})</p>
        </div>
        <div className="row">
          {["created", "failed"].includes(inv.status) && <button className="btn primary" onClick={run}>Run investigation</button>}
          {inv.status === "running" && <button className="btn danger" onClick={cancel}>Cancel</button>}
          <button className="btn" onClick={() => go("containment")}>Containment →</button>
        </div>
      </div>
      <div className="card">
        <Pipeline tasks={state.tasks} />
        {live !== "idle" && <p className="small muted" aria-live="polite" style={{ margin: "8px 0 0" }}>Live progress via {live === "stream" ? "server-sent events" : "polling (stream unavailable)"}…</p>}
      </div>
      <div style={{ height: 16 }} />
      {T !== null && tau !== null && <TimeControls inv={inv} T={T} tau={tau} setT={setT} setTau={setTau} />}
      <div style={{ height: 16 }} />
      <div className="workspace">
        <aside className="stack" aria-label="Incident facts">
          <section className="card">
            <h3>Incident</h3>
            <dl className="kv small"><dt>Incident</dt><dd>{inv.incident_id}</dd><dt>Occurred</dt><dd>{fmt(isoOf(inv.T_incident))}</dd></dl>
          </section>
          <section className="card">
            <h3>Hypotheses</h3>
            <State loading={hy.loading} error={hy.error} empty={!hy.data?.investigator && "Available after the investigator stage completes."}>
              <ul className="tight small" style={{ listStyle: "none", padding: 0 }}>
                {hy.data?.investigator?.hypotheses.map((h) => (
                  <li key={h.id} style={{ marginBottom: 8 }}>
                    <button className="btn sm" aria-pressed={hyp === h.id} onClick={() => setHyp(hyp === h.id ? null : h.id)} style={{ textAlign: "left" }}>
                      {stripClass(h.title)}
                    </button>{" "}<ClassBadge value={h.path_class} />
                  </li>
                ))}
              </ul>
              <p className="small muted">{hy.data?.investigator?.reasoning_summary}</p>
            </State>
          </section>
          <section className="card">
            <h3>Evidence timeline</h3>
            <State loading={ev.loading} error={ev.error}>
              <ol className="tight small">
                {incidentEvidence.map((s) => (
                  <li key={s.source_id}><span className="mono">{fmt(s.observed_at_iso)}</span> — {s.system}
                    {s.attacker_influenceable && <span className="badge b-bad">⚑ attacker-influenceable</span>}
                    {s.contains_instructions && <span className="badge b-bad">⚠ embedded instructions</span>}
                    <div className="muted">“{s.content}”</div></li>
                ))}
              </ol>
            </State>
          </section>
        </aside>
        <section aria-label="Graph">
          <div className="row between" style={{ marginBottom: 8 }}>
            <div className="row" role="group" aria-label="View">
              <button className="btn sm" aria-pressed={view === "graph"} onClick={() => setView("graph")}>Graph</button>
              <button className="btn sm" aria-pressed={view === "table"} onClick={() => setView("table")}>Table</button>
            </div>
            <label className="row small">Trust policy
              <select value={policy} onChange={(e) => setPolicy(e.target.value)}>
                <option value="conservative_defense">conservative_defense (R1–R3)</option>
                <option value="trust_filtered">trust_filtered (exclude attacker-influenceable)</option>
              </select>
            </label>
          </div>
          <State loading={graph.loading && !graph.data} error={graph.error} onRetry={graph.reload}>
            {graph.data && (view === "graph" ? (
              <>
                <GraphView data={graph.data} highlight={hl} onSelectEdge={onEdge} showLabels={labels} onToggleLabels={() => setLabels(!labels)} />
                <Legend />
                <p className="small muted">{graph.data.edges.length} edges active or validity-uncertain at T={fmt(graph.data.T)} as known at τ={fmt(graph.data.tau)}; {graph.data.inactive_edges.length} known but inactive.</p>
              </>
            ) : (
              <div className="card scroll" tabIndex={0} style={{ maxHeight: 600 }}>
                <table>
                  <caption className="small muted" style={{ textAlign: "left" }}>Edges at T={fmt(graph.data.T)}, τ={fmt(graph.data.tau)}</caption>
                  <thead><tr><th>Edge</th><th>From → to</th><th>Class</th><th>Flags</th><th>Valid</th></tr></thead>
                  <tbody>
                    {[...graph.data.edges, ...graph.data.inactive_edges].map((e) => (
                      <tr key={e.edge_id + e.version} className={sel?.edge_id === e.edge_id ? "sel" : ""} onClick={() => setSel(e)}>
                        <td><button className="btn sm" onClick={() => setSel(e)}>{e.type}</button></td>
                        <td className="mono">{e.src} → {e.dst}</td>
                        <td><ClassBadge value={e.temporal === "ACTIVE" ? e.cls : e.temporal} /></td>
                        <td><FlagBadges flags={e.flags} /></td>
                        <td className="small">{fmt(e.valid_from)} → {e.valid_to ? fmt(e.valid_to) : "…"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </State>
        </section>
        <aside className="right card" aria-label="Edge details">
          <h3>Provenance & validity</h3>
          <EdgeDetail edge={sel} invId={invId} sources={sources} />
        </aside>
      </div>
    </>
  );
}

export function stripClass(t: string) {
  return t.replace(/ \((CONFIRMED|CONDITIONAL\(\d+\)|TEMPORALLY_UNCERTAIN)\)$/, "");
}
