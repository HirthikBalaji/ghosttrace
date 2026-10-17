import { useEffect, useState } from "react";
import { api } from "../api";
import type { Route } from "../App";
import type { Advisor } from "../components/Advisor";
import { PathChips, State, Synthetic, useAsync } from "../components/common";
import { ParetoChart } from "../components/ParetoChart";
import type { Hypothesis, ParetoPoint } from "../types";

interface Data {
  planner: { pareto: ParetoPoint[]; baseline_b0: { status: string; residual_confirmed_paths: string[][] }; sensitivity: any[]; advisor?: Advisor } | null;
  certificates: { certificate_id: string; status: string; k_certified: number }[];
}

// Guided walkthrough: one claim per step, each backed by a live number and a link to the evidence.
export function StoryPage({ invId, go }: { invId: string; go: (r: Route, inv?: string | null, cert?: string | null) => void }) {
  const c = useAsync(() => api.get<Data>(`/api/v1/investigations/${invId}/containment`), [invId]);
  const h = useAsync(() => api.get<{ investigator: { hypotheses: Hypothesis[] } | null }>(`/api/v1/investigations/${invId}/hypotheses`), [invId]);
  const [k, setK] = useState(0);
  const [verdict, setVerdict] = useState<string | null>(null);
  const p = c.data?.planner;
  const confirmed = h.data?.investigator?.hypotheses.find((x) => x.path_class === "CONFIRMED");
  const k1 = p?.sensitivity.find((s) => s.k === 1);
  const pts = p?.pareto ?? [];
  const cost = (kk: number) => pts.find((x) => x.k === kk)?.total_cost;
  const firstCert = c.data?.certificates.find((x) => x.status === "contained");
  const adv = p?.advisor;

  async function verify() {
    if (!firstCert) return;
    const r = await api.post<{ accepted: boolean; output: string }>(`/api/v1/investigations/${invId}/certificate/${firstCert.certificate_id}/verify`);
    setVerdict(r.accepted ? `ACCEPTED by the independent verifier (${r.output})` : `REJECTED: ${r.output}`);
  }

  useEffect(() => {
    if (!p && !c.error && !c.loading) {
      const timer = setTimeout(() => {
        c.reload();
        h.reload();
      }, 700);
      return () => clearTimeout(timer);
    }
  }, [p, c.error, c.loading, c.reload, h.reload]);

  const Step = ({ n, title, children, to }: { n: number; title: string; children: React.ReactNode; to?: Route }) => (
    <section className="card story-step" aria-labelledby={`s${n}`}>
      <div className="row between">
        <h2 id={`s${n}`}><span className="badge b-accent" aria-hidden="true">{n}</span> {title}</h2>
        {to && <button className="btn sm" onClick={() => go(to)}>See the evidence →</button>}
      </div>
      {children}
    </section>
  );

  return (
    <>
      <div className="page-head">
        <div><h1>The Ghost Credential, in seven steps <Synthetic /></h1>
          <p>Every number here is computed live from the graph for this investigation.</p></div>
      </div>
      <State loading={c.loading || h.loading} error={c.error || h.error} empty={!p && "Executing investigation swarm… Waiting for containment planner output."}>
        {p && (
          <div className="stack">
            <Step n={1} title="The alert is not the answer" to="investigation">
              <p>An impossible-travel sign-in for <code>dev-alice</code>. The runbook says: disable the account.</p>
            </Step>
            <Step n={2} title="Disabling the account does not contain it" to="containment">
              <p>Status after disabling only the alerted account: <b className="badge b-bad">{p.baseline_b0.status.replace("_", " ")}</b>. A confirmed path survives:</p>
              {p.baseline_b0.residual_confirmed_paths.slice(0, 1).map((x, i) => <PathChips key={i} ids={x} />)}
            </Step>
            <Step n={3} title="The hidden path" to="hypotheses">
              <p>{confirmed ? <>{confirmed.title.replace(/ \(CONFIRMED\)$/, "")}. </> : null}
                A CI-runner token cached on the developer's workstation authenticates as a different principal, so disabling the developer
                does not touch it. {confirmed?.known_at_incident_time === false && "It was not even knowable at incident time — the scan arrived later."}</p>
            </Step>
            <Step n={4} title="The Price of Certainty" to="containment">
              <p>Cheapest plan that leaves no confirmed path: <b>{cost(0)}</b>. But one unverified edge would reopen it.
                Surviving any single wrong assumption costs <b>{cost(1)}</b>; any two, <b>{cost(2)}</b>.</p>
              <ParetoChart points={pts} selected={k} onSelect={setK} />
            </Step>
            <Step n={5} title="Don't let the attacker write your plan" to="hypotheses">
              <p>A log on the compromised workstation claims the token was rotated. It does not remove the edge (rule R2).
                A planted alert pushes an extra action; it is flagged for human scrutiny, and appears only when attacker-controlled evidence is trusted:
                {k1?.only_conservative?.length ? <> <code>{k1.only_conservative.join(", ")}</code></> : " (none)"}.</p>
            </Step>
            <Step n={6} title="The AI proposes, the graph disposes" to="containment">
              {adv && adv.proposals.length ? (
                <ul className="tight">{adv.proposals.map((x) => (
                  <li key={x.title}><span className={`badge ${x.verdict === "accepted" ? "b-ok" : "b-bad"}`}>{x.verdict}</span> {x.title} — <span className="muted">{x.reasons[0]}</span></li>
                ))}</ul>
              ) : <p className="muted">No advisor proposals for this run.</p>}
            </Step>
            <Step n={7} title="Don't trust us — check it" to="certificate">
              <p>Each plan ships with a certificate. A separate, stdlib-only verifier that shares no code with the planner re-derives it.</p>
              <button className="btn primary" onClick={verify} disabled={!firstCert}>Verify the k=0 certificate now</button>
              {verdict && <p role="status" className={`callout ${verdict.startsWith("ACCEPTED") ? "ok" : "bad"}`}>{verdict}</p>}
            </Step>
          </div>
        )}
      </State>
    </>
  );
}
