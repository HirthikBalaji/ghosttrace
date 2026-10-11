import { api } from "../api";
import { ClassBadge, PathChips, State, StatusBadge, Synthetic, useAsync } from "../components/common";
import type { Hypothesis, Verdict } from "../types";
import { stripClass } from "./Investigation";

interface HypData {
  investigator: { hypotheses: Hypothesis[]; reasoning_summary: string; unknowns: string[]; memory_consulted: any[] } | null;
  verifier: { verdicts: Verdict[]; stale_runbooks: any[]; disputed_removals: any[]; injection_flags: any[]; duplicate_evidence: any[]; notes: string[] } | null;
}

export function HypothesesPage({ invId }: { invId: string }) {
  const d = useAsync(() => api.get<HypData>(`/api/v1/investigations/${invId}/hypotheses`), [invId]);
  const vmap = Object.fromEntries((d.data?.verifier?.verdicts ?? []).map((v) => [v.hypothesis_id, v]));
  return (
    <>
      <div className="page-head">
        <div><h1>Hypothesis comparison <Synthetic /></h1>
          <p>The investigator proposes; the evidence verifier independently re-fetches records, re-derives path classes and tries to falsify. No probability percentages are shown: statuses come from defined rules.</p></div>
        <button className="btn" onClick={d.reload}>Refresh</button>
      </div>
      <State loading={d.loading} error={d.error} onRetry={d.reload} empty={!d.data?.investigator && "Hypotheses appear after the investigator stage completes."}>
        <div className="grid g2">
          {d.data?.investigator?.hypotheses.map((h) => {
            const v = vmap[h.id];
            return (
              <article className="card" key={h.id}>
                <div className="row between"><h3>{stripClass(h.title)}</h3>{v && <StatusBadge value={v.status} />}</div>
                <div className="row small" style={{ marginBottom: 8 }}><ClassBadge value={h.path_class} />
                  {h.known_at_incident_time === false && <span className="badge b-warn">⧗ not knowable at incident time</span>}
                  {h.kind === "benign_prior_pattern" && <span className="badge b-neutral">from prior-incident memory</span>}</div>
                {h.paths[0] && (<><h4>Best path</h4><PathChips ids={h.paths[0].edge_ids}
                  classes={Object.fromEntries(h.paths[0].edge_ids.map((e, i) => [e, { confirmed: h.paths[0].edge_classes[i] === "CONFIRMED", temporal: h.paths[0].edge_classes[i] === "UNCERTAIN" ? "UNCERTAIN" : "ACTIVE" }]))} /></>)}
                <div className="grid g2 small" style={{ marginTop: 10 }}>
                  <div><h4>Supporting ({h.supporting_evidence_ids.length})</h4><ul className="tight">{h.supporting_evidence_ids.slice(0, 8).map((s) => <li key={s}><code>{s}</code></li>)}</ul></div>
                  <div><h4>Contradicting ({h.contradicting_evidence_ids.length})</h4><ul className="tight">{h.contradicting_evidence_ids.slice(0, 8).map((s) => <li key={s}><code>{s}</code></li>)}</ul>
                    {!h.contradicting_evidence_ids.length && <p className="muted">none found</p>}</div>
                </div>
                {v && (<><h4 style={{ marginTop: 8 }}>Verifier</h4>
                  <ul className="tight small">{v.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
                  <dl className="kv small" style={{ marginTop: 6 }}>
                    <dt>Temporal</dt><dd>{v.temporal_check}</dd>
                    <dt>Citations</dt><dd>{v.citations_resolved}/{v.citations_total} resolve to stored records</dd>
                    <dt>Independent roots</dt><dd>{v.independent_roots} <span className="muted">(distinct upstream origins, not record count)</span></dd>
                  </dl></>)}
                {!!h.unknowns.length && (<><h4 style={{ marginTop: 8 }}>Missing information</h4><ul className="tight small">{h.unknowns.map((u) => <li key={u}>{u}</li>)}</ul></>)}
              </article>
            );
          })}
        </div>
        {d.data?.verifier && (
          <div className="grid g2" style={{ marginTop: 16 }}>
            <section className="card"><h3>Stale guidance</h3>
              {d.data.verifier.stale_runbooks.length ? d.data.verifier.stale_runbooks.map((r) => (
                <div className="callout warn small" key={r.runbook_id}><b>{r.name}</b> — “{r.recommendation}”<br />{r.reason}</div>
              )) : <p className="muted small">No stale runbooks detected.</p>}
              <h3 style={{ marginTop: 12 }}>Disputed removals (R2)</h3>
              <ul className="tight small">{d.data.verifier.disputed_removals.map((x) => <li key={x.edge_id}><code>{x.edge_id}</code> — claim by {x.dispute_source_ids.join(", ")}: {x.rule}</li>)}</ul>
            </section>
            <section className="card"><h3>Untrusted content & duplicates</h3>
              <ul className="tight small">{d.data.verifier.injection_flags.map((x) => <li key={x.source_id}><span className="badge b-bad">⚠ injection</span> <code>{x.source_id}</code>: {x.note}</li>)}</ul>
              <ul className="tight small">{d.data.verifier.duplicate_evidence.map((x) => <li key={x.edge_id}><code>{x.edge_id}</code>: {x.records} records but {x.independent_roots} independent root → <ClassBadge value={x.class} /></li>)}</ul>
              <h3 style={{ marginTop: 12 }}>Memory consulted</h3>
              <ul className="tight small">{d.data.investigator?.memory_consulted.map((m) => <li key={m.memory_id}><code>{m.memory_id}</code> ({m.category}{m.taint ? ", tainted" : ""}) — {m.content}</li>)}</ul>
              <p className="small muted">Prior-incident memory informs a competing hypothesis; it never decides the outcome.</p>
            </section>
          </div>
        )}
      </State>
    </>
  );
}
