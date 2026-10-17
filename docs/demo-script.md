# Demo script (≈3½ minutes)
<iframe width="100%" height="450" src="https://www.youtube.com/embed/nerrSAtqa4w" title="GhostTrace Demo Video" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen style="border-radius: 8px; margin: 16px 0;"></iframe>

Shortest version: open **Story mode** and walk the seven steps. Each step's "See the evidence" button jumps to the
detailed view. The full narrated walkthrough is available on [YouTube](https://www.youtube.com/watch?v=nerrSAtqa4w) and in [`ghosttrace_demo_with_voiceover.mp4`](../ghosttrace_demo_with_voiceover.mp4) (silent recording in `docs/demo/ghosttrace-demo.webm`).

**Setup.** Run `docker compose up -d --build` and open http://localhost:8080, or use `make api` and `make web`.
Everything shown is synthetic, and every action is a simulation. This script was rehearsed: the Playwright test
`frontend/e2e/demo.spec.ts` runs the same steps and passed against both the dev stack and the Compose stack.

| Time | Do | Say / point at |
|---|---|---|
| 0:00 | Command center → **Reset scenario & investigate** on *The Ghost Credential* | "An impossible-travel alert for dev-alice. A single event is not the connected system." |
| 0:20 | The Investigation page opens. Watch the five pipeline stages complete | "Each agent is a persisted task with a lease and a handoff, not a role in one prompt." |
| 0:30 | Select hypothesis *via cred:ci-token* (CONFIRMED). Click edges | Identity → workstation → **CI runner token** → ci-runner → deploy-role → payments-api → cardholder-db. Each edge has a source, a validity interval and a class. |
| 0:45 | Click **Incident, as known then**, then **Incident, as known now** | "At incident time we didn't know the token was cached. The EDR scan arrived later. τ changes the world." |
| 0:55 | Hypotheses page | The verifier flags RB-7 ("disable the account") as written before the CI credential existed. The rotation log is from the compromised host, so R2 disputes the edge instead of removing it. The duplicate SIEM alerts count as one root. The prior-incident "benign" memory is disputed. |
| 1:25 | Containment page | B0: disabling dev-alice leaves a **residual CONFIRMED path**. The **Price of Certainty** curve shows costs 3, 10 and 14 for k = 0, 1 and 2. |
| 1:45 | Click the k=1 point | Assumption frontier: the witness path plus "verify these edges first". `remove grant ws-alice→shared-config` is flagged **requires human scrutiny**. R4: it appears only under `conservative_defense` because a planted alert drives it. |
| 2:00 | Containment → **Model advisor** card | "The AI proposes, the graph disposes." Disabling the account is rejected (a confirmed path survives); isolating what the alerts name is rejected (a confirmed path still survives and it breaks a hard flow); rotating the credential is accepted at the certified optimum. |
| 2:05 | **Open certificate → Verify with independent verifier** | ACCEPTED (exit code 0) from a separate stdlib-only process. Show the statement, assumptions, limitations and load-bearing evidence: "if the IAM revocation record were false, a confirmed path survives." |
| 2:20 | Company Brain → **Compare: as known then vs as known now** | `team:payments` (stale CMDB record) as known then; `team:platform` (backfilled reorg) as known now. The undated SRE wiki claim is flagged. |
| 2:45 | Memory & audit | The episodic memory and the promoted semantic memory (6 independent roots). False-flag and injection memories are **tainted**. Handoffs and the audit trail are listed. Then restart: `docker compose restart backend` — the investigation and memory are all still there. |
| 3:05 | Command center → *Ghost Credential B* | A different topology. The hard nightly-export flow rules out the cheapest network cut, so the computed plan differs. |
| 3:20 | Open `evals/report.md` | 0 soundness violations across 900 certificates; baselines vs GHOSTTRACE with Wilson intervals; limitations: synthetic only, unmodeled edges. |

## 📸 Step-by-Step UI Screenshots

### 1. Story Mode & Incident Overview
*Guided narrative through The Ghost Credential scenario with live evidence inspector.*
![Story Mode](/screenshots/0-story.png)

### 2. 5-Agent Swarm Live Timeline & Coordination
*5 specialized agents coordinate via FalkorDB CAS leases and durable task handoffs.*
![Investigation Timeline](/screenshots/1-investigation.png)

### 3. Hypotheses & Bitemporal Reasoning ($T$ vs $\tau$)
*Multi-hop attack path reconstruction under world time $T$ and knowledge time $\tau$.*
![Hypotheses](/screenshots/2-hypotheses.png)

### 4. CEGAR Containment & Price of Certainty Curve
*CEGAR optimizer computes the Price-of-Certainty curve ($k=0, 1, 2$ robustness).*
![Containment](/screenshots/3-containment.png)

### 5. Machine-Checkable Proof Certificate
*Independent stdlib-only verifier checks containment proof out-of-process.*
![Certificate](/screenshots/4-certificate.png)

### 6. Company Brain (CMDB Reconciliation)
*Reconciles conflicting ownership and stale CMDB records across time.*
![Company Brain](/screenshots/5-brain.png)

### 7. Durable Agent Memory & Provenance Audit
*Quarantined tainted inputs, provenance tracking, and state that survives backend restarts.*
![Agent Memory](/screenshots/6-memory.png)
