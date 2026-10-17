# GHOSTTRACE: The First Graph-Native Incident Investigation & Response Platform

> **"The AI proposes, the graph disposes."**  
> Proven containment. Zero guesswork. Built on **FalkorDB**.

---

## 🎯 Short Summary / Elevator Pitch

Traditional incident response fails because disabling a compromised user account leaves cached tokens, CI runners, and lateral permissions wide open. **GHOSTTRACE** is a graph-native incident investigation and response platform powered by **FalkorDB** and bitemporal graph calculus. It exposes surviving multi-hop attack paths, computes the exact mathematical **Price of Certainty** across a Pareto frontier, and issues **machine-checkable containment certificates** validated out-of-process.

---

## ❗ What Problem Does It Solve?

1. **The "Disabling the Account" Fallacy**:
   - When an intrusion alert fires (e.g. impossible travel for `dev-alice`), defenders reflexively disable the user account.
   - Attackers exploit the connected system: Alice's developer workstation still holds an unexpired CI-runner token with deployment permissions into the payment API and cardholder database.
   - Disabling the user leaves a confirmed lateral attack path wide open.

2. **Intuition vs. Provable Trade-offs (The Price of Certainty)**:
   - Security teams face an impossible dilemma: apply a cheap, fragile fix (e.g., terminate one session) that an unobserved credential can bypass, or deploy a heavy-handed cut (e.g., sever subnets) that destroys revenue.
   - Current tools offer no quantifiable trade-off curve between business disruption and adversarial risk.

3. **Attacker Deception & Generative AI Hallucinations**:
   - Sophisticated attackers plant false credential-rotation logs and trigger diversionary SIEM alerts to mislead defenders into breaking their own systems.
   - Generative LLM "copilots" hallucinate nonexistent actions or propose disruptive cuts because they are ungrounded and lack formal proof guarantees.

4. **Hindsight Bias & Conflicting Enterprise CMDBs**:
   - Incident investigations fail when teams conflate *World Time* (when an event happened) with *Knowledge Time* (when defenders learned about it).
   - Stale CMDB records dispute service ownership, leaving teams arguing over who owns a compromised resource while the attack progresses.

---

## 🛡️ How Does GHOSTTRACE Solve It?

### 1. Bitemporal Graph Calculus on FalkorDB
GHOSTTRACE indexes identities, workloads, credentials, and network edges across two orthogonal dimensions:
- **World Time ($T$)**: The timestamp when an event occurred or an edge was valid.
- **Knowledge Time ($\tau$)**: The timestamp when the telemetry became known to defenders.

Defenders scrub through bitemporal time sliders to reconstruct what was *knowable then* versus what is *known now*, permanently eliminating retrospective hindsight bias.

### 2. "The AI Proposes, the Graph Disposes"
LLM agents (Claude / Laya ModernBERT System 1) propose candidate plans under uncertainty, but **the graph and the verifier decide**:
- Candidate plans are simulated counterfactually in FalkorDB without touching production infrastructure.
- Plans that fail to eliminate all attack paths or violate critical business flows (e.g., nightly batch exports) are mathematically rejected with concrete witness counterexamples.
- Only provably sound plans are accepted.

### 3. The Price of Certainty (Pareto Optimization)
GHOSTTRACE computes a multi-point Pareto curve showing the exact cost of each level of robustness against unobserved edges ($d$):
- **$k=0$ (Cost 3)**: Cheapest containment, but 0-robust (a single unverified edge can reopen access).
- **$k=1$ (Cost 10)**: Survives any single wrong assumption or latent credential.
- **$k=2$ (Cost 14)**: Maximum resilience against multi-hop bypasses.

### 4. Attacker-Aware Evidence Calculus (Rules R1–R4)
- **Rule R2**: Evidence logs originating from compromised hosts cannot remove attack surface.
- **Rules R3/R4**: Actions triggered solely by uncorroborated, planted alerts are flagged as `requires_human_scrutiny`, preventing attackers from weaponizing defender playbooks.

### 5. Out-of-Process Mathematical Verification
Every containment plan generates an assumption-explicit, cryptographically hashed JSON certificate. An independent, Python standard-library-only verifier formally checks soundness out-of-process before any human approval is requested (0 soundness violations across 900 test certificates).

### 6. Durable Multi-Agent Swarm with Graph Memory
A coordinated 5-agent swarm runs directly on FalkorDB:
1. **Investigator**: Explores multi-hop paths and confirms active lateral movement.
2. **Evidence Verifier**: Applies Evidence Calculus to filter spoofed telemetry.
3. **Containment Planner**: Computes CEGAR cuts and Pareto frontiers.
4. **Red Team**: Hypothesizes latent edges and adversarial countermoves.
5. **Memory Curator**: Maintains episodic and semantic memory with taint tracking and quarantine.

All agent tasks, compare-and-swap leases, and handoffs persist directly as FalkorDB graph nodes, allowing investigations to seamlessly survive system restarts.

---

## 👥 Who Is It For?

| Role | Why They Need GHOSTTRACE |
|---|---|
| **Incident Responders & SOC Tier 2/3** | Eliminates alert fatigue and rabbit holes by surfacing the actual surviving attack graph, distinguishing genuine evidence from attacker false flags. |
| **Security Engineers & Platform Architects** | Allows testing and simulating containment options counterfactually, ensuring containment doesn't break mission-critical dependencies. |
| **CISOs & Executive Leadership** | Replaces black-box "AI trust" with verifiable certificates, giving executive leadership defensible, mathematically proven containment decisions. |
| **Audit & Compliance Teams** | Provides an immutable bitemporal ledger of what was known, what was assumed, and which actions were approved at every second of an incident. |

---

## 🏗️ Architecture & Technology Stack

- **Graph Database**: [FalkorDB](https://www.falkordb.com/) (Atomic CAS leases, bitemporal traversal, Cypher pattern matching)
- **AI / Decision Engines**:
  - Anthropic Claude (Plan proposals & scenario summarization)
  - Laya ModernBERT System 1 (Sub-second non-autoregressive intent routing & prompt guardrails)
- **Formal Verification**: Out-of-process mathematical proof engine (stdlib-only, zero external dependencies)
- **Backend**: Python 3.12, FastAPI, Soundfile, KittenTTS 2
- **Frontend**: React 19, TypeScript, Vite, Tailwind CSS, Playwright
- **Deployment**: Docker, Docker Compose, Caddy (TLS/HTTPS), OIDC PKCE authentication
