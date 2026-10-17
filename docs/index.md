---
layout: home

hero:
  name: "GHOSTTRACE"
  text: "Self-Verifying Multi-Agent Intelligence Engine"
  tagline: "Built on FalkorDB: Where an Investigator, Red-Team, and CEGAR Formal Verifier collaborate over a live temporal knowledge graph to eliminate hallucinated reasoning paths before execution."
  image:
    src: /screenshots/0-story.png
    alt: GHOSTTRACE Story Mode
  actions:
    - theme: brand
      text: Architecture & Swarm
      link: /architecture
    - theme: alt
      text: 🧠 Why FalkorDB is the Brain
      link: /why-falkordb
    - theme: alt
      text: 🎬 Demo Video & Walkthrough
      link: /demo-script

features:
  - icon: 🧠
    title: FalkorDB Graph Brain
    details: GraphBLAS sparse matrix linear algebra enables sub-2ms multi-hop path traversals up to 12 hops deep over bitemporal intervals.
    link: /why-falkordb
  - icon: 🛡️
    title: CEGAR Formal Verification
    details: Counterexample-Guided Abstraction Refinement ensures zero containment actions execute without a machine-checkable proof.
    link: /hard-problem
  - icon: 🐝
    title: 5-Agent Autonomous Swarm
    details: Investigator, Evidence Verifier, Containment Planner, Red Team, and Curator coordinate via atomic CAS leases in FalkorDB.
    link: /architecture
  - icon: ⏱️
    title: Bitemporal Company Brain
    details: Eliminates hindsight bias by decoupling world time T from knowledge time τ to resolve conflicting, stale CMDB records.
    link: /graph-schema
  - icon: ⚡
    title: Laya System 1 Triage
    details: Non-autoregressive ModernBERT decision engine powering calibrated confidence, prompt guardrails, and sub-second intent routing.
    link: /api
  - icon: 📊
    title: Zero-Tolerance Soundness Gate
    details: 60 randomized benchmark families with planted ground truth, tested against real FalkorDB with exit-on-violation in CI.
    link: /evaluation
---

## 🎬 Video Walkthrough

<div style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; max-width: 100%; border-radius: 8px; margin: 20px 0;">
  <iframe src="https://www.youtube.com/embed/nerrSAtqa4w" title="GhostTrace Demo Video" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: 0;" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>
</div>

---

## 🏆 Hackathon Tracks Entered

GHOSTTRACE is entered into **all three tracks** of the WeMakeDevs Graph Hacks 2026:

| Track | Core Challenge | How GHOSTTRACE Solves It with FalkorDB |
|:---|:---|:---|
| **1 · Agents That Act on Connected Data** | Autonomous actions over dense connected data | Time-valid multi-hop attack path enumeration over bitemporal graphs. A CEGAR containment optimizer computes the **Price-of-Certainty curve** ($k=0,1,2$), verified out-of-process. |
| **2 · Agent Memory & Coordination** | Durable multi-agent swarm state | 5-agent swarm coordinating directly through FalkorDB atomic CAS leases, durable tasks, handoffs, and provenance-tracked memory that survives restarts. |
| **3 · Company Brain** | Live enterprise knowledge & ownership | Bitemporal organizational knowledge graph tracking ownership, dependencies, and runbooks across world time $T$ and knowledge time $\tau$, resolving conflicting CMDB records. |

---

## 🧠 Why FalkorDB is the Brain

> **"Without FalkorDB's low-latency graph traversal, our CEGAR verification loop and multi-agent state synchronization cannot resolve multi-hop evidence chains in real time."**

FalkorDB is the primary graph database and sits in the live path of every decision:

```mermaid
flowchart LR
    A["Alert Ingested<br/>(dev-alice unusual login)"] --> B["Investigator Agent<br/>(Enumerates Multi-Hop Paths)"]
    B --> C["FalkorDB ws:demo<br/>(Live Bitemporal Graph)"]
    C --> D["Evidence Verifier<br/>(Falsification & Provenance)"]
    D --> E["CEGAR Planner<br/>(Min-Disruption Cut Set)"]
    E --> F["Red Team Agent<br/>(Latent Preconditions)"]
    F -- Counterexample Found --> E
    E -- Proof Accepted --> G["Machine-Checkable<br/>Certificate JSON"]
    G --> H["Independent Verifier<br/>(Out-of-Process Proof)"]
```

### 1. CEGAR Counterexample Loop & Multi-Hop Path Enumeration
```cypher
MATCH p=(s:Entity)-[*1..$depth]->(t:Entity)
WHERE s.id IN $sources AND t.id IN $targets
  AND all(r IN relationships(p) WHERE r.workspace_id = $ws AND r.edge_id IN $allowed AND (
    r.tx_from <= $tau AND (r.tx_to IS NULL OR $tau < r.tx_to)
    AND (r.valid_to IS NULL OR $T < r.valid_to)
    AND (r.valid_from IS NULL OR r.valid_from <= $T)
  ))
RETURN [r IN relationships(p) | r.edge_id] AS edge_ids, [n IN nodes(p) | n.id] AS node_ids LIMIT $limit
```

### 2. Atomic Compare-And-Set Task Leasing
```cypher
MATCH (t:AgentTask {task_id: $tid}) WHERE t.workspace_id = $ws AND
  (t.status = 'queued' OR (t.status = 'running' AND t.lease_expires_at < $now))
SET t.status = 'running', t.lease_owner = $owner, t.lease_expires_at = $exp,
    t.attempt_count = coalesce(t.attempt_count, 0) + 1, t.started_at = $now
RETURN properties(t);
```

---

## 🌐 Interactive Graph View

Experience the live graph visualization directly:
- **Lightweight Standalone View**: Open [`http://localhost:8000/graph-view`](http://localhost:8000/graph-view) served directly by FastAPI without needing Node/Vite.
- **Color-Coded by Agent Action**:
  - 🔵 **Blue**: Investigator discovered path & entities
  - 🟢 **Green**: Evidence Verifier approved (confirmed facts)
  - 🔴 **Red**: Red-Team counterexample / pruned via CEGAR
  - 🟣 **Purple**: Latent / $\kappa$ candidate state

---

## 🚀 Quick Navigation

- [System Architecture & 5-Agent Flow](/architecture)
- [The Hard Problem: Open-World Containment](/hard-problem)
- [Bitemporal Graph Schema](/graph-schema)
- [Formal Claims Ledger](/claims-ledger)
- [Evaluation Suite & Soundness Report](/evaluation)
- [REST API Specification](/api)
- [Judge FAQ & Architecture Highlights](/judge-faq)
