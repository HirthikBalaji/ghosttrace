import { useEffect, useState } from "react";
import { api, fmt, qs } from "../api";
import { State, Synthetic } from "../components/common";
import type { BrainAnswer } from "../types";

const QUESTIONS = [
  { id: "owner", label: "Who owns…" }, { id: "experts", label: "Who knows about…" },
  { id: "dependents", label: "What depends on…" }, { id: "dependencies", label: "What does … depend on" },
  { id: "runbooks", label: "Which runbook applies to…" }, { id: "decisions", label: "Who decided why… (decision provenance)" },
];

export function BrainPage() {
  const [question, setQuestion] = useState("owner");
  const [subject, setSubject] = useState("svc:payments-api");
  const [T, setT] = useState("2026-03-02T09:00:00Z");
  const [tau, setTau] = useState("");
  const [ans, setAns] = useState<BrainAnswer | null>(null);
  const [cmp, setCmp] = useState<BrainAnswer | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [hits, setHits] = useState<{ id: string; label: string; name: string }[]>([]);

  useEffect(() => {
    if (subject.length < 2) return;
    const h = setTimeout(() => api.get<typeof hits>(`/api/v1/company/search${qs({ q: subject.split(":").pop() })}`).then(setHits).catch(() => setHits([])), 250);
    return () => clearTimeout(h);
  }, [subject]);

  async function ask(e?: React.FormEvent) {
    e?.preventDefault();
    setBusy(true); setErr(null); setCmp(null);
    try {
      setAns(await api.get<BrainAnswer>(`/api/v1/company/ask${qs({ question, subject_id: subject, asof_T: T, known_tau: tau })}`));
    } catch (x) { setErr((x as Error).message); setAns(null); } finally { setBusy(false); }
  }
  async function thenVsNow() {
    setBusy(true); setErr(null);
    try {
      setAns(await api.get<BrainAnswer>(`/api/v1/company/ask${qs({ question, subject_id: subject, asof_T: T, known_tau: T })}`));
      setCmp(await api.get<BrainAnswer>(`/api/v1/company/ask${qs({ question, subject_id: subject, asof_T: T })}`));
    } catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
  }

  return (
    <>
      <div className="page-head">
        <div><h1>Company Brain <Synthetic /></h1>
          <p>Answers come from bitemporal graph traversal. Every answer shows its time scope, supporting edges and source records, and flags stale or conflicting facts. Text search only locates entities.</p></div>
      </div>
      <form className="card" onSubmit={ask} aria-label="Ask the Company Brain">
        <div className="grid" style={{ gridTemplateColumns: "minmax(0,1.2fr) minmax(0,1.4fr) minmax(0,1fr) minmax(0,1fr) auto", alignItems: "end" }}>
          <label className="field">Question<select value={question} onChange={(e) => setQuestion(e.target.value)}>{QUESTIONS.map((q) => <option key={q.id} value={q.id}>{q.label}</option>)}</select></label>
          <label className="field">Subject (entity id)<input type="search" list="brain-hits" value={subject} onChange={(e) => setSubject(e.target.value)} maxLength={120} />
            <datalist id="brain-hits">{hits.map((h) => <option key={h.id} value={h.id}>{h.label}: {h.name}</option>)}</datalist></label>
          <label className="field">As of world time T (ISO, with offset)<input type="text" value={T} onChange={(e) => setT(e.target.value)} placeholder="2026-03-02T09:00:00Z" /></label>
          <label className="field">As known at τ (blank = now)<input type="text" value={tau} onChange={(e) => setTau(e.target.value)} placeholder="now" /></label>
          <button className="btn primary" disabled={busy}>Ask</button>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          <button type="button" className="btn sm" onClick={thenVsNow} disabled={busy}>Compare: as known then (τ = T) vs as known now</button>
        </div>
      </form>
      {err && <div className="callout bad" role="alert" style={{ marginTop: 12 }}>{err}</div>}
      <div className={`grid ${cmp ? "g2" : ""}`} style={{ marginTop: 16 }}>
        {ans && <AnswerCard a={ans} title={cmp ? "As known then" : "Answer"} />}
        {cmp && <AnswerCard a={cmp} title="As known now" />}
      </div>
      {!ans && !err && <State empty="Ask a question to see a source-backed, time-scoped answer." />}
    </>
  );
}

function AnswerCard({ a, title }: { a: BrainAnswer; title: string }) {
  return (
    <article className="card" aria-live="polite">
      <h4>{title}</h4>
      <h2 style={{ margin: "6px 0 10px" }}>{a.answer}</h2>
      <p className="small muted">Scope: valid at T = {fmt(a.temporal_scope.T_iso)}, as known at τ = {fmt(a.temporal_scope.tau_iso)}</p>
      {!!a.warnings.length && <div className="callout warn small"><b>Warnings</b><ul className="tight">{a.warnings.map((w) => <li key={w}>{w}</li>)}</ul></div>}
      {!!a.contradictions.length && <div className="callout bad small" style={{ marginTop: 8 }}><b>Contradictions</b><ul className="tight">{a.contradictions.map((c, i) => <li key={i} className="mono">{JSON.stringify(c)}</li>)}</ul></div>}
      {!!a.primary.length && (
        <div className="scroll" tabIndex={0} style={{ marginTop: 8 }}><table className="small"><thead><tr>{Object.keys(a.primary[0]).filter((k) => !["members"].includes(k)).slice(0, 7).map((k) => <th key={k}>{k}</th>)}</tr></thead>
          <tbody>{a.primary.map((r, i) => <tr key={i}>{Object.keys(a.primary[0]).filter((k) => !["members"].includes(k)).slice(0, 7).map((k) => <td key={k} className="mono">{Array.isArray(r[k]) ? r[k].join(", ") : String(r[k] ?? "—")}</td>)}</tr>)}</tbody></table></div>
      )}
      {a.primary[0]?.members && <p className="small">Team members: {a.primary[0].members.map((m: any) => m.name).join(", ") || "none recorded"}</p>}
      {!!a.paths.length && <div className="small"><h4>Graph paths</h4><ul className="tight">{a.paths.slice(0, 10).map((p, i) => <li key={i} className="mono">{p.join(" → ")}</li>)}</ul></div>}
      <div className="grid g2 small" style={{ marginTop: 8 }}>
        <div><h4>Supporting edges</h4><ul className="tight">{a.supporting_edge_ids.map((e) => <li key={e}><code>{e}</code></li>)}</ul></div>
        <div><h4>Source records</h4><ul className="tight">{a.source_ids.map((e) => <li key={e}><code>{e}</code></li>)}</ul></div>
      </div>
      {!!a.unknowns.length && <p className="small muted">Unknown: {a.unknowns.join("; ")}</p>}
    </article>
  );
}
