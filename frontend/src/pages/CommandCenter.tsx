import { useState } from "react";
import { api, fmt, isoOf } from "../api";
import { State, StatusBadge, Synthetic, useAsync } from "../components/common";
import type { Investigation } from "../types";

interface Scenario {
  scenario_id: string; title: string; description: string; loaded: boolean;
  incident: { incident_id: string; title: string; severity: string; T_incident: string };
}

export function CommandCenter({ onOpen }: { onOpen: (id: string) => void }) {
  const scen = useAsync(() => api.get<Scenario[]>("/api/v1/scenarios"), []);
  const invs = useAsync(() => api.get<Investigation[]>("/api/v1/investigations?limit=20"), []);
  const ready = useAsync(() => api.ready(), []);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function start(sid: string) {
    setBusy(sid);
    setErr(null);
    try {
      await api.post(`/api/v1/scenarios/${sid}/reset`);
      const inv = await api.post<Investigation>("/api/v1/investigations", {});
      await api.post(`/api/v1/investigations/${inv.id}/run`);
      onOpen(inv.id);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Command center <Synthetic /></h1>
          <p>Start a scenario to seed the FalkorDB workspace graph from a synthetic, timestamped ingestion log, then run the multi-agent investigation.</p>
        </div>
        <div className="row small" aria-live="polite">
          Service: {ready.data ? <StatusBadge value={ready.data.status === "ready" ? "completed" : "failed"} /> : "…"}
          <span className="muted">{ready.data?.status === "ready" ? "FalkorDB reachable" : ready.error ? "API unreachable" : ""}</span>
        </div>
      </div>
      {err && <div className="callout bad" role="alert">{err}</div>}
      <section className="grid g2" aria-label="Scenarios">
        <State loading={scen.loading} error={scen.error} onRetry={scen.reload}>
          {scen.data?.map((s) => (
            <article className="card" key={s.scenario_id}>
              <div className="row between"><h2>{s.title}</h2>{s.loaded && <span className="badge b-accent">loaded</span>}</div>
              <p className="muted small" style={{ marginTop: 0 }}>{s.description}</p>
              <dl className="kv">
                <dt>Incident</dt><dd>{s.incident.incident_id} — {s.incident.title}</dd>
                <dt>Severity</dt><dd><span className={`badge ${s.incident.severity === "critical" ? "b-bad" : "b-warn"}`}>{s.incident.severity}</span></dd>
                <dt>Incident time</dt><dd>{fmt(s.incident.T_incident)}</dd>
              </dl>
              <hr />
              <button className="btn primary" disabled={busy !== null} onClick={() => start(s.scenario_id)}>
                {busy === s.scenario_id ? "Seeding & starting…" : "Reset scenario & investigate"}
              </button>
            </article>
          ))}
        </State>
      </section>
      <section className="card" style={{ marginTop: 16 }} aria-label="Investigations">
        <div className="row between"><h2>Investigations</h2><button className="btn sm" onClick={invs.reload}>Refresh</button></div>
        <State loading={invs.loading} error={invs.error} empty={invs.data?.length === 0 && "No investigations in this workspace yet."} onRetry={invs.reload}>
          <div className="scroll" tabIndex={0}>
            <table>
              <thead><tr><th>Investigation</th><th>Incident</th><th>Status</th><th>Created</th><th>Analysis clock</th><th /></tr></thead>
              <tbody>
                {invs.data?.map((i) => (
                  <tr key={i.id}>
                    <td><code>{i.id}</code></td><td>{i.title}</td><td><StatusBadge value={i.status} /></td>
                    <td className="small">{fmt(isoOf(i.created_at))}</td>
                    <td className="small">T = {fmt(isoOf(i.T_analysis))} <span className="muted">(simulated)</span></td>
                    <td><button className="btn sm" onClick={() => onOpen(i.id)}>Open</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </State>
      </section>
    </>
  );
}
