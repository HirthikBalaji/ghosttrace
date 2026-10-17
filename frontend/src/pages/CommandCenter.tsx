import { useState } from "react";
import { api, fmt, isoOf } from "../api";
import type { Route } from "../App";
import { State, StatusBadge, Synthetic, useAsync } from "../components/common";
import type { Investigation } from "../types";

interface Scenario {
  scenario_id: string;
  title: string;
  description: string;
  loaded: boolean;
  incident: { incident_id: string; title: string; severity: string; T_incident: string };
}

export function CommandCenter({
  onOpen,
  go,
  activeInv,
}: {
  onOpen: (id: string) => void;
  go?: (route: Route, invId?: string | null, cert?: string | null) => void;
  activeInv?: string | null;
}) {
  const scen = useAsync(() => api.get<Scenario[]>("/api/v1/scenarios"), []);
  const invs = useAsync(() => api.get<Investigation[]>("/api/v1/investigations?limit=20"), []);
  const ready = useAsync(() => api.ready(), []);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [demoStep, setDemoStep] = useState<number>(1);

  async function start(sid: string, targetRoute: Route = "story") {
    setBusy("1/3 Seeding scenario into FalkorDB…");
    setErr(null);
    try {
      await api.post(`/api/v1/scenarios/${sid}/reset`);
      setBusy("2/3 Initializing autonomous agents…");
      const inv = await api.post<Investigation>("/api/v1/investigations", {});
      try {
        localStorage.setItem("gt.inv", inv.id);
      } catch {
        /* storage fallback */
      }
      setBusy("3/3 Executing 5-agent investigation pipeline (sync)…");
      await api.post(`/api/v1/investigations/${inv.id}/run?sync=true`);
      setBusy("Done! Redirecting…");
      if (go) {
        go(targetRoute, inv.id);
      } else {
        onOpen(inv.id);
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const navigate = (route: Route, invId?: string | null) => {
    if (go) go(route, invId ?? activeInv);
    else if (invId) onOpen(invId);
  };

  const currentInv = activeInv ?? (invs.data && invs.data.length > 0 ? invs.data[0].id : null);

  return (
    <div className="stack" style={{ gap: 32 }}>
      {/* Product Launch Hero Banner */}
      <section className="hero-box">
        <div className="hero-badge-pill">
          <span>🚀 PRODUCT LAUNCH · GHOSTTRACE 1.0</span>
          <span>•</span>
          <span>FalkorDB Hackathon Benchmark</span>
          <Synthetic />
        </div>

        <h1 className="hero-title">
          <span>The AI Proposes.</span>
          <span className="hero-title-gradient">The Graph Disposes.</span>
        </h1>

        <p className="hero-tagline">
          <b>Find the hidden path. Prove what holds. State what could be wrong. Remember why.</b><br />
          GHOSTTRACE is the first graph-native incident investigation and response platform built on <b>FalkorDB</b>.
          It replaces hallucinating LLM assistants and static SIEM alerts with bitemporal graph calculus, autonomous
          multi-agent coordination, and <b>machine-checkable mathematical certificates</b> verified out-of-process.
        </p>

        {/* Live System Telemetry */}
        <div className="hero-stats">
          <span className="stat-pill">
            <span style={{ color: ready.data?.status === "ready" ? "var(--ok)" : "var(--warn)" }}>●</span>{" "}
            <b>FalkorDB Engine:</b> {ready.data?.status === "ready" ? "Connected (Port 6379)" : "Connecting…"}
          </span>
          <span className="stat-pill">
            <span style={{ color: "var(--accent)" }}>⚡</span> <b>Laya System 1:</b> Non-Autoregressive Decision Engine
          </span>
          <span className="stat-pill">
            <span style={{ color: "var(--accent)" }}>⏱</span> <b>Bitemporal Logic:</b> World Time <i>T</i> &amp; Knowledge Time <i>τ</i>
          </span>
          <span className="stat-pill">
            <span style={{ color: "var(--latent)" }}>🤖</span> <b>Agent Swarm:</b> 5 Autonomous Durable Roles
          </span>
          <span className="stat-pill">
            <span style={{ color: "var(--derived)" }}>📜</span> <b>Soundness:</b> Independent Stdlib Verifier
          </span>
        </div>

        {/* Hero CTAs */}
        <div className="hero-actions">
          <button
            className="btn primary btn-hero"
            disabled={busy !== null}
            onClick={() => start("ghost_credential_a", "story")}
          >
            {busy ? busy : "⚡ Launch Live Interactive Demo (Instant Swarm)"}
          </button>
          {currentInv && (
            <button className="btn btn-hero" onClick={() => navigate("story", currentInv)}>
              ▶ Watch 7-Step Story Walkthrough
            </button>
          )}
          <button className="btn btn-hero" onClick={() => navigate("brain")}>
            ❖ Query Bitemporal Company Brain
          </button>
          <button className="btn btn-hero" onClick={() => navigate("chat")}>
            💬 Ask Graph Copilot
          </button>
          {currentInv && (
            <button className="btn btn-hero" onClick={() => navigate("investigation", currentInv)}>
              ⌘ Explore Attack Graph
            </button>
          )}
        </div>
      </section>

      {err && <div className="callout bad" role="alert">{err}</div>}

      {/* Value & Architectural Metrics */}
      <section aria-label="Key Product Metrics">
        <div className="metric-grid">
          <div className="metric-card">
            <span className="metric-value">0</span>
            <span className="metric-label">Residual Attack Paths</span>
            <p className="metric-desc">Mathematically verified containment cut that leaves no surviving path to critical services.</p>
          </div>
          <div className="metric-card">
            <span className="metric-value">100%</span>
            <span className="metric-label">Machine-Checked Proofs</span>
            <p className="metric-desc">Every response plan ships with a JSON certificate checked by an independent stdlib verifier.</p>
          </div>
          <div className="metric-card">
            <span className="metric-value">5</span>
            <span className="metric-label">Autonomous Agents</span>
            <p className="metric-desc">Durable state machine in FalkorDB with CAS leases; survives process restarts without data loss.</p>
          </div>
          <div className="metric-card">
            <span className="metric-value">&lt; 350ms</span>
            <span className="metric-label">Exact CEGAR Solver</span>
            <p className="metric-desc">Branch-and-bound hitting-set optimizer calculates the complete Price-of-Certainty Pareto curve.</p>
          </div>
        </div>
      </section>

      {/* The Hard Problem (Why Traditional Response Fails) */}
      <section aria-labelledby="problem-heading">
        <div className="page-head" style={{ marginBottom: 12 }}>
          <div>
            <h2 id="problem-heading" style={{ fontSize: 20 }}>The Hard Problem: Why Incident Response Fails</h2>
            <p className="muted small">
              Real-world enterprise security incidents break the assumptions of traditional playbooks and blind LLMs.
            </p>
          </div>
        </div>

        <div className="grid g2">
          <div className="problem-card">
            <div className="row" style={{ gap: 10 }}>
              <span className="problem-num">1</span>
              <h3>Hidden Attack Surfaces (Latent Paths)</h3>
            </div>
            <p>
              Corporate identity graphs are always incomplete. Attackers rarely use direct front doors; they hop
              across secondary cached workstation tokens, undeclared CI runners, and shadow privilege inheritance.
              Standard playbooks are blind to these unmodeled lateral jumps.
            </p>
          </div>

          <div className="problem-card">
            <div className="row" style={{ gap: 10 }}>
              <span className="problem-num">2</span>
              <h3>The Time Paradox (World Time T vs. Knowledge Time τ)</h3>
            </div>
            <p>
              An attack occurred at 02:00 UTC (world time <i>T</i>), but the telemetry arrived at 09:00 UTC (knowledge time <i>τ</i>).
              Traditional databases confuse what was true at incident time with what the company knew then.
              GHOSTTRACE’s bitemporal predicate <code>Active(f, T, τ)</code> prevents hindsight bias.
            </p>
          </div>

          <div className="problem-card">
            <div className="row" style={{ gap: 10 }}>
              <span className="problem-num">3</span>
              <h3>Adversarial Poisoning &amp; False Flags</h3>
            </div>
            <p>
              Attackers manipulate logs, fabricate false rotation records, or trigger false-flag alerts to divert
              defenders. GHOSTTRACE’s <b>Evidence Calculus (Rules R1–R5)</b> refuses to remove vulnerabilities without
              independent, un-compromised source verification.
            </p>
          </div>

          <div className="problem-card">
            <div className="row" style={{ gap: 10 }}>
              <span className="problem-num">4</span>
              <h3>The Disruption Dilemma (Containment vs. Business Flow)</h3>
            </div>
            <p>
              Pulling the plug on entire clusters stops attackers, but breaks critical business revenue.
              GHOSTTRACE computes the exact <b>Price of Certainty</b>, identifying the minimal-cost cut that preserves
              vital services like payment processing while guaranteeing containment.
            </p>
          </div>
        </div>
      </section>

      {/* Traditional vs. GHOSTTRACE Comparison Matrix */}
      <section className="card" aria-labelledby="vs-heading">
        <div className="row between" style={{ marginBottom: 14 }}>
          <div>
            <h2 id="vs-heading" style={{ fontSize: 18 }}>Traditional Incident Playbook vs. GHOSTTRACE</h2>
            <p className="muted small" style={{ margin: 0 }}>
              A side-by-side comparison of standard industry approaches versus GHOSTTRACE’s graph-native paradigm.
            </p>
          </div>
          <span className="badge b-accent">Architectural Matrix</span>
        </div>

        <div className="scroll" tabIndex={0}>
          <table className="vs-table">
            <thead>
              <tr>
                <th style={{ width: "20%" }}>Dimension</th>
                <th className="vs-col-bad" style={{ width: "40%" }}>Traditional SIEM / LLM Playbook</th>
                <th className="vs-col-good" style={{ width: "40%" }}>GHOSTTRACE Graph-Native Platform</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td><b>Initial Reaction (Baseline B0)</b></td>
                <td className="vs-col-bad">
                  <b>Knee-jerk account lock:</b> Disables the alerted identity (<code>dev-alice</code>). Incident falsely marked "contained".<br />
                  <span className="badge b-bad" style={{ marginTop: 4 }}>FAIL: Attack backdoor remains active</span>
                </td>
                <td className="vs-col-good">
                  <b>Exact graph simulation:</b> Proves access still leaks through a cached CI-runner token (<code>id:ci-runner</code>) to <code>svc:payments-api</code>.<br />
                  <span className="badge b-ok" style={{ marginTop: 4 }}>PROVEN: Flags status NOT CONTAINED</span>
                </td>
              </tr>
              <tr>
                <td><b>Time &amp; Knowledge</b></td>
                <td className="vs-col-bad">
                  <b>Flat, static snapshot:</b> Blends what was true at incident time with later observations; vulnerable to late-arriving logs and post-hoc confusion.
                </td>
                <td className="vs-col-good">
                  <b>True bitemporal graphs:</b> Evaluates facts under both world time <i>T</i> and knowledge time <i>τ</i>. Exactly determines what was knowable at incident time.
                </td>
              </tr>
              <tr>
                <td><b>Untrusted Evidence &amp; Tampering</b></td>
                <td className="vs-col-bad">
                  <b>Blind trust in logs:</b> Attacker plants a fake "token rotated" log. Playbook accepts it and silences alerts.
                </td>
                <td className="vs-col-good">
                  <b>Evidence Calculus (R1–R5):</b> Rule <i>R2</i> rejects surface-removing claims without independent sources. Attack claims quarantined as <code>possible_false_flag</code>.
                </td>
              </tr>
              <tr>
                <td><b>Containment Strategy</b></td>
                <td className="vs-col-bad">
                  <b>Guesswork blast radius:</b> Either pulls critical plugs breaking business payments, or under-contains to avoid complaints.
                </td>
                <td className="vs-col-good">
                  <b>Exact CEGAR Pareto Optimizer:</b> Evaluates the <b>Price of Certainty</b> (<i>k=0, 1, 2</i>), guaranteeing preservation of all hard business flows.
                </td>
              </tr>
              <tr>
                <td><b>Triage &amp; Intent Routing (System 1)</b></td>
                <td className="vs-col-bad">
                  <b>Autoregressive LLM / RegEx:</b> High latency (3–8s per step), uncalibrated softmax logits, and highly vulnerable to prompt injection exploits.
                </td>
                <td className="vs-col-good">
                  <b>Laya ModernBERT System 1:</b> Non-autoregressive forward pass with mathematically calibrated probabilities ($P &gt; 0.95$), automated incident severity triage, and active prompt guardrails.
                </td>
              </tr>
              <tr>
                <td><b>AI Safety &amp; Grounding</b></td>
                <td className="vs-col-bad">
                  <b>Unconstrained LLM text:</b> Model hallucinates non-existent paths, fabricates bash scripts, and cannot prove mathematical containment.
                </td>
                <td className="vs-col-good">
                  <b>“The AI proposes, the graph disposes”:</b> LLM output is schema-constrained, simulated in the graph, and certified by an out-of-process mathematical verifier.
                </td>
              </tr>
              <tr>
                <td><b>Memory &amp; Coordination</b></td>
                <td className="vs-col-bad">
                  <b>Static wikis &amp; Jira tickets:</b> Lessons forgotten; agent memory lost between invocations and restarts.
                </td>
                <td className="vs-col-good">
                  <b>Durable FalkorDB Memory:</b> 5 specialized agents coordinate via graph nodes with provenance DAGs, promotion rules, and taint quarantine.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* The 3 Core Tracks (Full Showcase) */}
      <section aria-labelledby="tracks-heading">
        <div className="page-head" style={{ marginBottom: 14 }}>
          <div>
            <h2 id="tracks-heading" style={{ fontSize: 20 }}>The Three Core Tracks</h2>
            <p className="muted small">
              Three integrated tracks operating seamlessly over the same bitemporal FalkorDB graph.
            </p>
          </div>
        </div>

        <div className="grid g3">
          {/* Track 1 */}
          <article className="track-card">
            <div className="track-header">
              <span className="badge b-ok">Track 1</span>
              <div className="track-icon">⛨</div>
            </div>
            <h3>Connected Attack-Path Containment</h3>
            <p>
              Traverses multi-hop attack paths under world time <i>T</i> and knowledge time <i>τ</i>.
              A Counterexample-Guided Abstraction Refinement (CEGAR) planner solves the hitting-set problem,
              producing the <b>Price-of-Certainty curve</b> and independent machine-checked certificates.
            </p>
            <ul className="track-features">
              <li>Time-valid 0-1 BFS path enumeration</li>
              <li>Price-of-Certainty Pareto frontier (<i>k</i>-robust)</li>
              <li>Independent stdlib-only proof certificates</li>
            </ul>
            <button
              className="btn sm primary"
              style={{ width: "100%", justifyContent: "center" }}
              onClick={() => navigate("containment", currentInv)}
              disabled={!currentInv}
              title={!currentInv ? "Run an investigation first" : undefined}
            >
              Open Containment &amp; Pareto Curve →
            </button>
          </article>

          {/* Track 2 */}
          <article className="track-card">
            <div className="track-header">
              <span className="badge b-latent">Track 2</span>
              <div className="track-icon">☰</div>
            </div>
            <h3>Multi-Agent Durable Coordination</h3>
            <p>
              Five specialized agents coordinate directly through FalkorDB: <b>Investigator</b>, <b>Evidence Verifier</b>,
              <b>Containment Planner</b>, <b>Red Team</b>, and <b>Memory Curator</b>. State is persisted as <code>:AgentTask</code> nodes
              with CAS leases, surviving server restarts.
            </p>
            <ul className="track-features">
              <li>Durable graph-persisted tasks &amp; leases</li>
              <li>Episodic memory with provenance DAGs</li>
              <li>Taint propagation &amp; false-flag quarantine</li>
            </ul>
            <button
              className="btn sm"
              style={{ width: "100%", justifyContent: "center" }}
              onClick={() => navigate("memory", currentInv)}
            >
              Inspect Agent Memory &amp; Audit →
            </button>
          </article>

          {/* Track 3 */}
          <article className="track-card">
            <div className="track-header">
              <span className="badge b-derived">Track 3</span>
              <div className="track-icon">❖</div>
            </div>
            <h3>Bitemporal Company Brain</h3>
            <p>
              Answers deep bitemporal organizational queries: <i>“Who owned the payments service when the incident began ($T$), as known then ($\tau_1$) vs as known now ($\tau_2$)?”</i>
              Surfaces architectural dependencies, stale runbooks, and conflicting records.
            </p>
            <ul className="track-features">
              <li>Bitemporal service ownership resolution</li>
              <li>Upstream / downstream architectural maps</li>
              <li>Automated stale &amp; conflicting record detection</li>
            </ul>
            <button
              className="btn sm"
              style={{ width: "100%", justifyContent: "center" }}
              onClick={() => navigate("brain")}
            >
              Launch Company Brain →
            </button>
          </article>
        </div>
      </section>

      {/* Interactive Step-by-Step Simulator: The Ghost Credential */}
      <section className="card" aria-labelledby="demo-steps-heading">
        <div className="row between" style={{ marginBottom: 14 }}>
          <div>
            <h2 id="demo-steps-heading" style={{ fontSize: 18 }}>Interactive Simulation: The Ghost Credential in 5 Steps</h2>
            <p className="muted small" style={{ margin: 0 }}>
              Click through each stage to observe how GHOSTTRACE analyzes the attack graph, challenges hypotheses, and certifies containment.
            </p>
          </div>
          {currentInv && (
            <button className="btn sm primary" onClick={() => navigate("story", currentInv)}>
              Open Full 7-Step Walkthrough →
            </button>
          )}
        </div>

        {/* Stepper Tabs */}
        <div className="stepper-nav" role="tablist">
          {[
            { id: 1, label: "1 · Anomaly Alert" },
            { id: 2, label: "2 · Baseline Fix Fails (B0)" },
            { id: 3, label: "3 · Evidence Calculus (R1–R3)" },
            { id: 4, label: "4 · Price of Certainty (CEGAR)" },
            { id: 5, label: "5 · Independent Proof" },
          ].map((s) => (
            <button
              key={s.id}
              role="tab"
              aria-selected={demoStep === s.id}
              className={`step-tab ${demoStep === s.id ? "active" : ""}`}
              onClick={() => setDemoStep(s.id)}
            >
              <span className="step-badge">{s.id}</span> {s.label}
            </button>
          ))}
        </div>

        {/* Stepper Content */}
        <div className="stepper-body">
          {demoStep === 1 && (
            <div className="stack" style={{ gap: 10 }}>
              <div className="row between">
                <h3 style={{ margin: 0 }}>Stage 1: The Alert (The Bait)</h3>
                <span className="badge b-warn">Anomaly Alert Fired</span>
              </div>
              <p>
                An impossible-travel sign-in alert triggers for developer <code>id:dev-alice</code> at world time <code>2026-03-02 09:00:00Z</code>.
                Standard enterprise runbooks prescribe an immediate knee-jerk reaction: <i>"Disable the alerted Active Directory account."</i>
              </p>
              <div className="callout info" style={{ margin: "4px 0" }}>
                <b>⚡ Laya System 1 Triage:</b> ModernBERT single forward pass classifies incident as <code>credential_theft</code> with 99% calibrated confidence, prescribing <i>k=1</i> robustness to hedge against unmodeled developer tokens.
              </div>
              <div className="callout warn">
                <b>The Blind Spot:</b> Disabling Alice’s direct identity treats the symptom, not the graph.
                It ignores secondary tokens, cached developer session credentials, and unmodeled runner identities.
              </div>
            </div>
          )}

          {demoStep === 2 && (
            <div className="stack" style={{ gap: 10 }}>
              <div className="row between">
                <h3 style={{ margin: 0 }}>Stage 2: Graph Simulation Proves Baseline B0 Fails</h3>
                <span className="badge b-bad">Status: NOT CONTAINED</span>
              </div>
              <p>
                GHOSTTRACE simulates disabling <code>id:dev-alice</code> in FalkorDB. The graph traversal immediately reveals that
                a residual confirmed attack path survives directly to the core payments engine:
              </p>
              <p style={{ fontFamily: "var(--mono)", background: "var(--panel-2)", padding: "10px 14px", borderRadius: 6, fontSize: 13 }}>
                attacker ➔ workstation ➔ <b>cached CI token (id:ci-runner)</b> ➔ repo:payments-app ➔ <b>svc:payments-api</b>
              </p>
              <div className="callout bad">
                <b>Why It Failed:</b> The CI runner token authenticates as an independent machine principal.
                Disabling Alice’s user account left the attacker’s backdoor completely untouched!
              </div>
            </div>
          )}

          {demoStep === 3 && (
            <div className="stack" style={{ gap: 10 }}>
              <div className="row between">
                <h3 style={{ margin: 0 }}>Stage 3: Evidence Calculus &amp; Adversarial Tampering (R1–R3)</h3>
                <span className="badge b-accent">Evidence Calculus Applied</span>
              </div>
              <p>
                On the compromised workstation, an attacker leaves a forged log claiming the CI token was rotated.
                Traditional SIEMs remove the credential from their alert list. GHOSTTRACE applies mathematical evidence rules:
              </p>
              <ul className="tight">
                <li><b>Rule R1 (Observation):</b> An edge is OBSERVED only if it has ≥1 verified non-attacker source or ≥2 independent roots.</li>
                <li><b>Rule R2 (Surface Removal):</b> A claim that removes attack surface is <b>rejected</b> unless proven by non-attacker telemetry. The edge stays!</li>
                <li><b>Rule R3 (False Flags):</b> Claims based exclusively on attacker-controlled telemetry are flagged <code>possible_false_flag</code>.</li>
              </ul>
              <div className="callout ok">
                <b>Result:</b> Laya System 1 checks the claim (detecting 96% evidence tampering probability), and Rule R2 formally rejects the surface removal. The CI token vulnerability remains active in the graph.
              </div>
            </div>
          )}

          {demoStep === 4 && (
            <div className="stack" style={{ gap: 10 }}>
              <div className="row between">
                <h3 style={{ margin: 0 }}>Stage 4: The Price of Certainty (CEGAR Solver)</h3>
                <span className="badge b-ok">Pareto Frontier Calculated</span>
              </div>
              <p>
                Rather than asking a human to guess the blast radius, the CEGAR optimizer computes the <b>Price-of-Certainty curve</b>,
                evaluating the trade-off between disruption cost and assurance level (<i>k</i>-robustness):
              </p>
              <div className="grid g3" style={{ marginTop: 10 }}>
                <div className="card" style={{ padding: 14, borderTop: "3px solid var(--accent)" }}>
                  <b>k = 0 Robust (Cost: 3)</b>
                  <p className="small muted" style={{ marginTop: 4 }}>
                    Cheapest containment cut. Eliminates known confirmed paths, but 1 unmodeled latent edge can reopen access.
                  </p>
                </div>
                <div className="card" style={{ padding: 14, borderTop: "3px solid var(--ok)" }}>
                  <b>k = 1 Robust (Cost: 10)</b>
                  <p className="small muted" style={{ marginTop: 4 }}>
                    Robust plan. Survives any 1 wrong or unmodeled assumption without reopening an attack path.
                  </p>
                </div>
                <div className="card" style={{ padding: 14, borderTop: "3px solid var(--derived)" }}>
                  <b>k = 2 Robust (Cost: 14)</b>
                  <p className="small muted" style={{ marginTop: 4 }}>
                    High-assurance plan. Survives any 2 latent edges while preserving all business-critical payment flows.
                  </p>
                </div>
              </div>
              <div className="callout info" style={{ marginTop: 10 }}>
                <b>⚡ Laya Operational Scrutiny:</b> Candidate cuts are scored non-autoregressively for operational blast radius, preventing catastrophic disruption to core revenue services like <code>svc:payments-api</code>.
              </div>
            </div>
          )}

          {demoStep === 5 && (
            <div className="stack" style={{ gap: 10 }}>
              <div className="row between">
                <h3 style={{ margin: 0 }}>Stage 5: Independent Out-of-Process Proof Certificate</h3>
                <span className="badge b-ok">Formally Verified</span>
              </div>
              <p>
                Every proposed containment plan outputs a machine-checkable JSON certificate that records:
              </p>
              <ul className="tight">
                <li>Bitemporal snapshot hash <i>H</i>, world time <i>T</i>, and knowledge time <i>τ</i>.</li>
                <li>Explicit cut sets, assumptions, and guaranteed preserved business flows.</li>
                <li>Independent re-verification by an external, stdlib-only Python verifier sharing zero code with the planner.</li>
              </ul>
              <div className="callout ok">
                <b>Mathematical Proof:</b> The response plan is not an LLM hallucination—it is a formally checked theorem on connected graph data.
              </div>
            </div>
          )}
        </div>
      </section>

      {/* Production Architecture Guarantees */}
      <section aria-labelledby="specs-heading">
        <div className="page-head" style={{ marginBottom: 12 }}>
          <div>
            <h2 id="specs-heading" style={{ fontSize: 18 }}>Production Architecture &amp; Guarantees</h2>
            <p className="muted small">Built for high-security enterprise environments and mission-critical infrastructure.</p>
          </div>
        </div>

        <div className="grid g4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))" }}>
          <div className="spec-box">
            <b>🛡️ Zero Destructive Execution</b>
            <p>All containment actions are simulations or recorded human approvals. Nothing is executed without multi-party authorization.</p>
          </div>
          <div className="spec-box">
            <b>📦 Air-Gapped &amp; Local First</b>
            <p>Runs 100% locally on macOS or Linux with native FalkorDB. Includes deterministic mock providers for offline operation.</p>
          </div>
          <div className="spec-box">
            <b>⚡ Durable Graph Persistence</b>
            <p>Agent states, leases, handoffs, and episodic memory are persisted directly into FalkorDB graphs with AOF and RDB persistence.</p>
          </div>
          <div className="spec-box">
            <b>🔒 Strict Security &amp; OIDC</b>
            <p>Supports OpenID Connect with PKCE, tenant workspace isolation (<code>ws:&lt;id&gt;</code>), and four-eyes review enforcement.</p>
          </div>
        </div>
      </section>

      {/* Scenario Launchers & Investigation History */}
      <section className="grid g2" aria-label="Scenarios">
        <State loading={scen.loading} error={scen.error} onRetry={scen.reload}>
          {scen.data?.map((s) => (
            <article className="card" key={s.scenario_id}>
              <div className="row between">
                <h2>{s.title}</h2>
                {s.loaded && <span className="badge b-accent">loaded in falkordb</span>}
              </div>
              <p className="muted small" style={{ marginTop: 4 }}>{s.description}</p>
              <dl className="kv">
                <dt>Incident</dt><dd>{s.incident.incident_id} — {s.incident.title}</dd>
                <dt>Severity</dt>
                <dd>
                  <span className={`badge ${s.incident.severity === "critical" ? "b-bad" : "b-warn"}`}>
                    {s.incident.severity}
                  </span>
                </dd>
                <dt>Incident time</dt><dd>{fmt(s.incident.T_incident)}</dd>
              </dl>
              <hr />
              <div className="row">
                <button
                  className="btn primary"
                  disabled={busy !== null}
                  onClick={() => start(s.scenario_id, "story")}
                >
                  {busy ? busy : "Reset Scenario & Run Swarm"}
                </button>
                <button
                  className="btn"
                  disabled={busy !== null}
                  onClick={() => start(s.scenario_id, "investigation")}
                >
                  {busy ? busy : "Reset & Open Graph"}
                </button>
              </div>
            </article>
          ))}
        </State>
      </section>

      {/* Historical Investigations Ledger */}
      <section className="card" aria-label="Investigations">
        <div className="row between">
          <h2>Historical Investigation Ledger</h2>
          <button className="btn sm" onClick={invs.reload}>Refresh List</button>
        </div>
        <State
          loading={invs.loading}
          error={invs.error}
          empty={invs.data?.length === 0 && "No investigations in this workspace yet."}
          onRetry={invs.reload}
        >
          <div className="scroll" tabIndex={0}>
            <table>
              <thead>
                <tr>
                  <th>Investigation ID</th>
                  <th>Incident</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Analysis Clock</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {invs.data?.map((i) => (
                  <tr key={i.id} className={i.id === activeInv ? "sel" : ""}>
                    <td><code>{i.id}</code></td>
                    <td>{i.title}</td>
                    <td><StatusBadge value={i.status} /></td>
                    <td className="small">{fmt(isoOf(i.created_at))}</td>
                    <td className="small">
                      T = {fmt(isoOf(i.T_analysis))} <span className="muted">(simulated)</span>
                    </td>
                    <td>
                      <div className="row" style={{ gap: 6 }}>
                        <button className="btn sm primary" onClick={() => navigate("story", i.id)}>
                          Story Mode
                        </button>
                        <button className="btn sm" onClick={() => onOpen(i.id)}>
                          Graph View
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </State>
      </section>
    </div>
  );
}
