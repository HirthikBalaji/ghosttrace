import { StatusBadge } from "./common";

export interface AdvisorProposal {
  title: string;
  rationale: string;
  action_ids: string[];
  verdict: "accepted" | "rejected";
  reasons: string[];
  certificate_id?: string;
  total_cost?: number;
  extra_cost_vs_optimum?: number | null;
}
export interface Advisor {
  provider: string;
  model: string | null;
  status: "ok" | "unavailable";
  error?: string;
  k0_optimum_cost: number | null;
  proposals: AdvisorProposal[];
  dropped_proposals?: number;
}

// "The model proposes, the graph disposes": every AI-suggested plan is simulated and certified by the
// deterministic engine; it is shown as accepted only if its certificate says contained.
export function AdvisorCard({ advisor, onOpenCert }: { advisor: Advisor | undefined; onOpenCert: (id: string) => void }) {
  if (!advisor || !advisor.provider) return null;
  const label = advisor.provider === "mock" ? "deterministic mock advisor (offline demo)" : `${advisor.provider} · ${advisor.model}`;
  return (
    <section className="card" style={{ marginTop: 16 }} aria-labelledby="advisor-h">
      <div className="row between">
        <h2 id="advisor-h">Model advisor — the AI proposes, the graph disposes</h2>
        <span className="badge b-neutral">{label}</span>
      </div>
      <p className="small muted" style={{ marginTop: 0 }}>
        The model saw the candidate actions, hard flows and the incident evidence (as untrusted data). Each plan it proposed was
        simulated and certified by the deterministic engine. It never decides on its own.
      </p>
      {advisor.status === "unavailable" ? (
        <div className="callout warn small">Advisor unavailable ({advisor.error}). The certified plans above do not depend on it.</div>
      ) : (
        <div className="grid g3">
          {advisor.proposals.map((p, i) => (
            <article key={i} className={`callout ${p.verdict === "accepted" ? "ok" : "bad"}`}>
              <div className="row between">
                <b>{p.title}</b>
                <span className={`badge ${p.verdict === "accepted" ? "b-ok" : "b-bad"}`}>
                  {p.verdict === "accepted" ? "✔ accepted" : "✕ rejected"}
                </span>
              </div>
              <p className="small muted" style={{ margin: "4px 0" }}>“{p.rationale}”</p>
              <ul className="tight small mono">{p.action_ids.map((a) => <li key={a}>{a}</li>)}</ul>
              <ul className="tight small" style={{ marginTop: 6 }}>{p.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
              {p.certificate_id && (
                <div className="row" style={{ marginTop: 6 }}>
                  <StatusBadge value="simulated" />
                  <button className="btn sm" onClick={() => onOpenCert(p.certificate_id!)}>Certificate</button>
                </div>
              )}
            </article>
          ))}
        </div>
      )}
      {!!advisor.dropped_proposals && <p className="small muted">{advisor.dropped_proposals} further proposal(s) exceeded the cap and were not evaluated.</p>}
    </section>
  );
}
