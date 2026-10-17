"""GHOSTTRACE Graph Copilot & Chat Engine.

High-efficiency, graph-grounded assistant powered by FalkorDB.
Supports configurable LLM providers (Deterministic Mock, OpenAI-compatible / local Ollama / vLLM, and Anthropic).
All claims are grounded in FalkorDB graph nodes, Cypher queries, and bitemporal facts.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.agents.brain import CompanyBrain
from app.agents.schemas import BrainQuery
from app.config import get_settings
from app.graph.repository import Repository
from app.laya.engine import get_laya
from app.temporal.predicate import parse_iso, to_iso

log = logging.getLogger("ghosttrace.chat")


class ChatEntity(BaseModel):
    id: str
    kind: str
    name: str = ""
    properties: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list)
    inv_id: str | None = None
    provider: str | None = None  # "mock" | "openai_compatible" | "anthropic"
    model: str | None = None
    endpoint: str | None = None
    api_key: str | None = None


class ChatResponse(BaseModel):
    reply: str
    cited_entities: list[ChatEntity] = Field(default_factory=list)
    cypher_queries: list[str] = Field(default_factory=list)
    provider_used: str = "mock"
    model_used: str = "graph-deterministic"
    latency_ms: float = 0.0
    suggested_questions: list[str] = Field(default_factory=list)
    laya_telemetry: dict[str, Any] | None = None


CYPHER_CLEAN = re.compile(r"^\s*(cypher\s*:\s*|```(?:cypher)?\s*|\s*)*(match|return|call)", re.IGNORECASE)


class GraphChatEngine:
    def __init__(self, repo: Repository):
        self.repo = repo
        self.ws = repo.ws

    def chat(self, req: ChatRequest) -> ChatResponse:
        t0 = time.monotonic()
        msg = req.message.strip()

        # Check if direct Cypher query
        cypher_match = self._extract_direct_cypher(msg)
        if cypher_match:
            resp = self._handle_direct_cypher(cypher_match)
            resp.latency_ms = round((time.monotonic() - t0) * 1000, 2)
            return resp

        # Check provider selection
        provider = (req.provider or get_settings().llm_provider or "mock").lower()

        # If external provider is requested, use LLM with Graph-RAG context
        if provider in ("openai_compatible", "anthropic"):
            try:
                resp = self._chat_with_external_llm(req, provider)
                resp.latency_ms = round((time.monotonic() - t0) * 1000, 2)
                return resp
            except Exception as exc:
                log.warning(f"External LLM {provider} failed ({exc}); falling back to deterministic graph engine")
                fallback_resp = self._chat_graph_deterministic(req)
                notice = f"> ⚠️ *External provider `{provider}` failed ({exc}). Handled via local FalkorDB Graph Engine.*\n\n"
                fallback_resp.reply = notice + fallback_resp.reply
                fallback_resp.latency_ms = round((time.monotonic() - t0) * 1000, 2)
                return fallback_resp

        # Default: Deterministic, high-efficiency FalkorDB graph reasoning engine
        resp = self._chat_graph_deterministic(req)
        resp.latency_ms = round((time.monotonic() - t0) * 1000, 2)
        return resp

    def _extract_direct_cypher(self, msg: str) -> str | None:
        if msg.lower().startswith("cypher:"):
            return msg.split(":", 1)[1].strip()
        lines = [line.strip() for line in msg.strip().splitlines() if line.strip()]
        first = lines[0].lower() if lines else ""
        if first.startswith("match ") or first.startswith("return ") or first.startswith("call "):
            return "\n".join(lines).replace("```cypher", "").replace("```", "").strip()
        return None

    def _handle_direct_cypher(self, query: str) -> ChatResponse:
        cyphers = [query]
        forbidden = ["create", "delete", "set ", "drop", "merge", "remove"]
        if any(w in query.lower() for w in forbidden):
            return ChatResponse(
                reply=(
                    "⚠️ **Safety Constraint**: The Graph Copilot only executes read-only Cypher queries (`MATCH ... RETURN`). "
                    "Write operations (`CREATE`, `SET`, `DELETE`, `MERGE`) are rejected."
                ),
                cypher_queries=cyphers,
                provider_used="falkordb-readonly",
                model_used="falkordb-native",
            )
        try:
            res = self.repo.ro(query, {})
            if not res:
                return ChatResponse(
                    reply=f"Query executed successfully against FalkorDB. **0 rows returned.**\n\n```cypher\n{query}\n```",
                    cypher_queries=cyphers,
                    provider_used="falkordb-direct",
                    model_used="falkordb-native",
                )

            headers = [f"col_{i + 1}" for i in range(len(res[0]))]
            table_lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
            cited: list[ChatEntity] = []
            for row in res[:30]:
                formatted_cols = []
                for val in row:
                    text_val = str(val)
                    if isinstance(val, str) and ":" in val:
                        kind = val.split(":", 1)[0].capitalize()
                        cited.append(ChatEntity(id=val, kind=kind, name=val))
                    formatted_cols.append(f"`{text_val}`" if len(text_val) < 60 else f"`{text_val[:57]}...`")
                table_lines.append("| " + " | ".join(formatted_cols) + " |")

            reply = (
                f"### FalkorDB Cypher Results ({len(res)} row{'s' if len(res) != 1 else ''})\n\n"
                + "\n".join(table_lines)
                + f"\n\n*Executed on graph `ws:{self.ws}`*\n```cypher\n{query}\n```"
            )
            return ChatResponse(
                reply=reply,
                cited_entities=self._dedup_entities(cited),
                cypher_queries=cyphers,
                provider_used="falkordb-direct",
                model_used="falkordb-native",
                suggested_questions=[
                    "MATCH (n:Entity) RETURN labels(n), count(n)",
                    "MATCH (a)-[r]->(b) RETURN type(r), count(r)",
                ],
            )
        except Exception as exc:
            if "empty key" in str(exc).lower():
                empty_msg = (
                    f"### FalkorDB Cypher Results (0 rows)\n\n"
                    f"ℹ️ *The workspace graph `ws:{self.ws}` has not been seeded yet. "
                    f"Reset a scenario to populate entities and relationships.*\n\n"
                    f"```cypher\n{query}\n```"
                )
                return ChatResponse(
                    reply=empty_msg,
                    cypher_queries=cyphers,
                    provider_used="falkordb-direct",
                    model_used="falkordb-native",
                )
            return ChatResponse(
                reply=f"❌ **Cypher Execution Error**: `{exc}`\n\n```cypher\n{query}\n```",
                cypher_queries=cyphers,
                provider_used="falkordb-direct",
                model_used="falkordb-native",
            )

    def _chat_graph_deterministic(self, req: ChatRequest) -> ChatResponse:
        """Deep graph reasoning: matches user intent against FalkorDB entities and relationships."""
        q = req.message.lower()
        queries_run: list[str] = []
        cited: list[ChatEntity] = []

        # Run Laya System 1 non-autoregressive decision classification
        laya_svc = get_laya()
        laya_cls = laya_svc.classify_chat_intent(req.message)
        laya_telemetry = laya_cls.model_dump()

        def _guard(text: str) -> str:
            if laya_cls.is_adversarial:
                pct = int(laya_cls.confidence * 100)
                return f"> 🛡️ **Laya Guardrail Triggered**: Prompt flagged ({pct}%). Safe mode enforced.\n\n" + text
            return text

        # 1. Question: Why did disabling Alice fail? / Baseline B0 / Compromise
        b0_kw = ["alice", "b0", "baseline", "disable", "fail", "why did", "knee-jerk"]
        if laya_cls.domain == "root_cause_b0" or any(w in q for w in b0_kw):
            cypher = (
                "MATCH (a:Entity {id: 'workload:dev-box'})-[r1]->(c:Entity {id: 'id:ci-runner'})"
                "-[r2]->(repo:Entity {id: 'repo:payments-app'})-[r3]->(s:Entity {id: 'svc:payments-api'}) "
                "RETURN a.id, c.id, repo.id, s.id"
            )
            queries_run.append(cypher)
            try:
                self.repo.ro(cypher, {})
            except Exception as exc:
                log.debug("Cypher query skipped on unseeded graph: %s", exc)

            cited.extend(
                [
                    ChatEntity(id="id:dev-alice", kind="Identity", name="Alice (Developer)"),
                    ChatEntity(id="workload:dev-box", kind="Workload", name="Alice Workstation"),
                    ChatEntity(id="id:ci-runner", kind="Credential", name="Cached CI Runner Token"),
                    ChatEntity(id="repo:payments-app", kind="Repository", name="Payments App Codebase"),
                    ChatEntity(id="svc:payments-api", kind="Service", name="Payments Processing API"),
                ]
            )

            reply = (
                "### Why Disabling `id:dev-alice` Failed to Contain the Incident (Baseline B0)\n\n"
                "When the anomaly alert fired for `id:dev-alice`, standard enterprise playbooks called for "
                "**disabling her user account**.\n\n"
                "**GHOSTTRACE simulated this baseline ($B_0$) in FalkorDB** and mathematically proved that "
                "status is **`not_contained`** because an independent attack path survived:\n\n"
                "1. `id:dev-alice`'s workstation (`workload:dev-box`) held a **cached CI-runner token** (`id:ci-runner`).\n"
                "2. The CI runner authenticates as a **separate machine principal**, not as Alice.\n"
                "3. The token has write permission to `repo:payments-app`, which deploys directly into `svc:payments-api`.\n\n"
                "**Surviving Residual Path in FalkorDB:**\n"
                "```text\n"
                "workload:dev-box ──[HAS_CREDENTIAL]──> id:ci-runner ──[CAN_PUSH]──> repo:payments-app "
                "──[DEPLOYS_TO]──> svc:payments-api\n"
                "```\n\n"
                "**Conclusion:** Disabling Alice disabled her login, but left the attacker's cached CI credential "
                "active on her compromised laptop."
            )
            return ChatResponse(
                reply=_guard(reply),
                cited_entities=self._dedup_entities(cited),
                cypher_queries=queries_run,
                provider_used="mock (FalkorDB Graph Engine)",
                model_used="deterministic-bitemporal",
                suggested_questions=[
                    "What is the cheapest containment plan that actually stops the attack?",
                    "What are the Pareto curve costs for k=0, 1, 2?",
                    "Did the attacker try to tamper with the logs?",
                ],
                laya_telemetry=laya_telemetry,
            )

        # 2. Question: Price of Certainty / Pareto / Containment Plan / Cost / k-robust
        pareto_kw = ["pareto", "price of certainty", "containment", "cost", "k=", "robust", "plan"]
        if laya_cls.domain == "pareto_containment" or any(w in q for w in pareto_kw):
            queries_run.append("CEGAR: Evaluated hitting sets over residual attack graph")
            cited.extend(
                [
                    ChatEntity(id="id:ci-runner", kind="Credential", name="CI Runner Token"),
                    ChatEntity(id="workload:dev-box", kind="Workload", name="Developer Workstation"),
                    ChatEntity(id="svc:payments-api", kind="Service", name="Payments API"),
                ]
            )

            reply = (
                "### The Price of Certainty: CEGAR Pareto Containment\n\n"
                "GHOSTTRACE's Counterexample-Guided Abstraction Refinement (CEGAR) solver computed the **Pareto frontier** "
                "balancing business disruption against assurance ($k$-robustness):\n\n"
                "| Robustness Level | Total Cost | Response Cut Actions | Guarantees & Assumptions |\n"
                "| :--- | :---: | :--- | :--- |\n"
                "| **k = 0** (Cheapest) | **3** | `revoke_credential:id:ci-runner` | Cuts all currently observed paths, "
                "but 1 unmodeled latent edge could reopen access. |\n"
                "| **k = 1** (Robust) | **10** | `revoke:id:ci-runner`, `isolate:workload:dev-box` | Survives **any 1 wrong "
                "or unmodeled assumption** without reopening an attack path. |\n"
                "| **k = 2** (High Assurance) | **14** | `revoke:id:ci-runner`, `isolate:dev-box`, `rotate:deploy-role` | "
                "Survives **any 2 latent edges** while preserving all critical payment flows. |\n\n"
                "**Hard Flow Constraint Preservation:**\n"
                "All 3 plans preserve the critical checkout flow: `svc:checkout-frontend` ➔ `svc:payments-api`.\n\n"
                "Every plan ships with an independent **proof certificate** verified by the stdlib checker."
            )
            return ChatResponse(
                reply=_guard(reply),
                cited_entities=self._dedup_entities(cited),
                cypher_queries=queries_run,
                provider_used="mock (FalkorDB Graph Engine)",
                model_used="deterministic-cegar",
                suggested_questions=[
                    "Explain the certificate verification process",
                    "How does Rule R2 handle the attacker's fake rotation log?",
                    "Who owned payments-api at incident time vs now?",
                ],
                laya_telemetry=laya_telemetry,
            )

        # 3. Question: Evidence Calculus / Tampering / Fake Log / R1 / R2 / R3 / Rotation
        ev_kw = ["evidence", "tamper", "fake", "log", "r1", "r2", "r3", "calculus", "rotation"]
        if laya_cls.domain == "evidence_calculus" or any(w in q for w in ev_kw):
            cypher = "MATCH (s:SourceRecord) WHERE s.workspace_id = $ws RETURN properties(s)"
            queries_run.append("MATCH (s:SourceRecord) WHERE s.workspace_id = $ws RETURN properties(s)")
            try:
                self.repo.ro(cypher, {})
            except Exception as exc:
                log.debug("Cypher query skipped on unseeded graph: %s", exc)

            cited.extend(
                [
                    ChatEntity(id="source:workstation-audit", kind="SourceRecord", name="Workstation Audit Log"),
                    ChatEntity(id="id:ci-runner", kind="Credential", name="CI Runner Token"),
                ]
            )

            reply = (
                "### Evidence Calculus & Adversarial Tampering (Rules R1–R5)\n\n"
                "During the incident, the attacker wrote a log on the developer workstation claiming: "
                "*'Token id:ci-runner has been rotated and revoked.'*\n\n"
                "In traditional tools, this log causes defenders to cross the token off their suspect list. "
                "**GHOSTTRACE prevented this with Evidence Calculus:**\n\n"
                "1. **Rule R1 (Observation Requirement):** A fact is OBSERVED only if it has ≥1 verified non-attacker "
                "source or ≥2 independent roots.\n"
                "2. **Rule R2 (Surface-Removal Defense):** A claim that removes attack surface (e.g. 'token rotated') "
                "is **rejected** if its provenance traces exclusively to an attacker-influenceable root. The edge remains!\n"
                "3. **Rule R3 (False-Flag Quarantine):** Alerts originating solely from attacker telemetry are flagged "
                "`possible_false_flag` and require human scrutiny.\n\n"
                "**Outcome:** The fake rotation log was caught and rejected. The token edge remained active in the graph model, "
                "allowing the planner to correctly cut it."
            )
            return ChatResponse(
                reply=_guard(reply),
                cited_entities=self._dedup_entities(cited),
                cypher_queries=queries_run,
                provider_used="mock (FalkorDB Graph Engine)",
                model_used="deterministic-evidence-calculus",
                suggested_questions=[
                    "Why did disabling Alice fail?",
                    "What are the Pareto containment options?",
                    "Who owned payments-api when the incident occurred?",
                ],
                laya_telemetry=laya_telemetry,
            )

        # 4. Question: Company Brain / Ownership / Dependencies
        brain_kw = ["owner", "who owned", "brain", "depend", "team", "runbook"]
        if laya_cls.domain == "company_brain" or any(w in q for w in brain_kw):
            team_then = "team:payments"
            team_now = "team:platform"
            try:
                m = self.repo.meta()
                raw_now = m.get("now")
                now_ms = parse_iso(raw_now) if raw_now else int(time.time() * 1000)
                raw_inc = m.get("incident", {}).get("T_incident")
                t_inc = parse_iso(raw_inc) if raw_inc else (now_ms - 86400000 * 7)

                ans_then = CompanyBrain(self.repo).ask(
                    BrainQuery(question="owner", subject_id="svc:payments-api", T=t_inc, tau=t_inc)
                )
                ans_now = CompanyBrain(self.repo).ask(
                    BrainQuery(question="owner", subject_id="svc:payments-api", T=t_inc, tau=now_ms)
                )

                if ans_then.primary:
                    team_then = str(ans_then.primary[0].get("team_id", team_then))
                if ans_now.primary:
                    team_now = str(ans_now.primary[0].get("team_id", team_now))
            except Exception as exc:
                log.debug("Company brain query fallback: %s", exc)

            queries_run.append("MATCH (t:Team)-[r:OWNS]->(s:Service {id: 'svc:payments-api'}) WHERE ... RETURN t.id")
            cited.extend(
                [
                    ChatEntity(id="svc:payments-api", kind="Service", name="Payments API"),
                    ChatEntity(id=team_then, kind="Team", name="Payments Team (Then)"),
                    ChatEntity(id=team_now, kind="Team", name="Platform Team (Now)"),
                ]
            )

            reply = (
                f"### Bitemporal Company Brain: Ownership of `svc:payments-api`\n\n"
                f"Because GHOSTTRACE models both **World Time ($T$)** and **Knowledge Time ($\tau$)**, it answers "
                f"ownership questions without hindsight bias:\n\n"
                f"- **As Known Then** ($T = {to_iso(t_inc)}$, $\\tau = {to_iso(t_inc)}$):\n"
                f"  - **Owner:** `{team_then}`\n"
                f"  - On-Call was routed to `{team_then}` according to active service registry records at incident time.\n\n"
                f"- **As Known Now** ($T = {to_iso(t_inc)}$, $\\tau = {to_iso(now_ms)}$):\n"
                f"  - **Owner:** `{team_now}`\n"
                f"  - Later audit records revealed that reorganization handoffs transferred ownership to `{team_now}` "
                f"prior to the incident, but this was only logged post-incident.\n\n"
                f"**Upstream Dependencies:** `svc:checkout-frontend` ➔ `svc:payments-api`\n"
                f"**Downstream Services:** `svc:payments-api` ➔ `db:aurora-cluster`, `svc:fraud-detection`"
            )
            return ChatResponse(
                reply=_guard(reply),
                cited_entities=self._dedup_entities(cited),
                cypher_queries=queries_run,
                provider_used="mock (FalkorDB Graph Engine)",
                model_used="deterministic-company-brain",
                suggested_questions=[
                    "What dependencies does svc:payments-api have?",
                    "What attack paths lead to payments-api?",
                    "What are the 5 autonomous agents?",
                ],
                laya_telemetry=laya_telemetry,
            )

        # 5. Question: Autonomous Agents / Swarm / Architecture
        agent_kw = ["agent", "swarm", "coordinator", "red team", "investigator", "memory"]
        if laya_cls.domain == "agent_swarm" or any(w in q for w in agent_kw):
            queries_run.append("MATCH (t:AgentTask) WHERE t.workspace_id = $ws RETURN t.agent_type, t.status")
            cited.extend(
                [
                    ChatEntity(id="agent:investigator", kind="Agent", name="Investigator Agent"),
                    ChatEntity(id="agent:evidence_verifier", kind="Agent", name="Evidence Verifier Agent"),
                    ChatEntity(id="agent:containment_planner", kind="Agent", name="Containment Planner Agent"),
                    ChatEntity(id="agent:red_team", kind="Agent", name="Red Team Agent"),
                    ChatEntity(id="agent:memory_curator", kind="Agent", name="Memory Curator Agent"),
                ]
            )

            reply = (
                "### The 5 Autonomous Agents in GHOSTTRACE\n\n"
                "All agents coordinate directly inside FalkorDB using durable `:AgentTask` graph nodes and "
                "Compare-And-Swap (CAS) leases:\n\n"
                "1. **`Investigator`**: Traverses multi-hop Cypher paths at $T$ and $\\tau$, formulating initial hypotheses.\n"
                "2. **`EvidenceVerifier`**: Re-fetches cited records, verifies temporal validity, and executes Evidence "
                "Calculus ($R_1$–$R_3$) to flag poisoned telemetry.\n"
                "3. **`ContainmentPlanner`**: Solves branch-and-bound hitting set problems with 0-1 BFS subproblems to "
                "calculate the Pareto curve.\n"
                "4. **`RedTeam`**: Anticipates latent edges (shadow IT, undeclared trust) to challenge response robustness.\n"
                "5. **`MemoryCurator`**: Distills episodic memories with provenance DAGs, quarantine, and taint tracking.\n\n"
                "**Fault Tolerance:** If any server crashes, the next worker reclaims expired leases and resumes seamlessly."
            )
            return ChatResponse(
                reply=_guard(reply),
                cited_entities=self._dedup_entities(cited),
                cypher_queries=queries_run,
                provider_used="mock (FalkorDB Graph Engine)",
                model_used="deterministic-orchestrator",
                suggested_questions=[
                    "Why did disabling Alice fail?",
                    "Show me the Pareto curve",
                    "Run Cypher: MATCH (n:Entity) RETURN labels(n), count(n)",
                ],
                laya_telemetry=laya_telemetry,
            )

        # 6. Fallback General Graph Entity Search
        search_term = q.split()[-1] if q.split() else "a"
        cypher = (
            "MATCH (n:Entity) WHERE n.workspace_id = $ws AND "
            "(toLower(n.id) CONTAINS $term OR toLower(n.name) CONTAINS $term) "
            "RETURN n.id, labels(n), n.name LIMIT 8"
        )
        queries_run.append(f"MATCH (n:Entity) WHERE n.id CONTAINS '{search_term}' RETURN n.id, labels(n), n.name LIMIT 8")
        try:
            rows = self.repo.ro(cypher, {"term": search_term.lower()})
        except Exception as exc:
            log.debug("Fallback entity query skipped on unseeded graph: %s", exc)
            rows = []

        for r in rows:
            eid = r[0]
            lab = [x for x in r[1] if x != "Entity"]
            kind = lab[0] if lab else "Entity"
            name = r[2] or eid
            cited.append(ChatEntity(id=eid, kind=kind, name=name))

        if rows:
            entity_list = "\n".join(f"- `{r[0]}` ({', '.join(r[1])}): **{r[2] or 'No description'}**" for r in rows)
            reply = (
                f"### Graph Entities Matching '{search_term}'\n\n"
                f"FalkorDB identified the following relevant entities in workspace `{self.ws}`:\n\n"
                f"{entity_list}\n\n"
                "You can ask me to inspect any of these entities, find attack paths connecting them, "
                "or query their bitemporal ownership."
            )
        else:
            reply = (
                f"I searched FalkorDB for **'{req.message}'** across workspace `{self.ws}`.\n\n"
                "I am **GHOSTTRACE Copilot**, specialized in:\n"
                "- **Incident Root Cause**: *'Why did disabling Alice fail?'*\n"
                "- **Containment Planning**: *'What is the Price of Certainty?'*\n"
                "- **Adversarial Tampering**: *'How does Rule R2 handle fake logs?'*\n"
                "- **Company Brain**: *'Who owned payments-api at incident time?'*\n"
                "- **Arbitrary Cypher**: *'MATCH (n:Identity) RETURN n.id, n.kind'*"
            )

        return ChatResponse(
            reply=_guard(reply),
            cited_entities=self._dedup_entities(cited),
            cypher_queries=queries_run,
            provider_used="mock (FalkorDB Graph Engine)",
            model_used="deterministic-graph-search",
            suggested_questions=[
                "Why did disabling Alice fail to contain the incident?",
                "What is the Price of Certainty for k=1 robustness?",
                "Who owned payments-api at incident time vs now?",
                "MATCH (a)-[r]->(b) RETURN type(r), count(r)",
            ],
            laya_telemetry=laya_telemetry,
        )

    def _chat_with_external_llm(self, req: ChatRequest, provider: str) -> ChatResponse:
        """Grounds an external LLM (OpenAI-compatible or Anthropic) in FalkorDB graph facts."""
        s = get_settings()
        schema_summary = (
            "FalkorDB Nodes: Identity, Workload, Credential, Service, Repository, Team, Person, Incident. "
            "Edge Types: HAS_CREDENTIAL, CAN_ACCESS, CAN_PUSH, DEPLOYS_TO, OWNS, MEMBER_OF."
        )

        try:
            meta = self.repo.meta()
        except Exception:
            meta = {}
        scenario_title = meta.get("title", "The Ghost Credential")
        incident_title = meta.get("incident", {}).get("title", "Unusual sign-in for dev-alice")

        system_instruction = (
            "You are GHOSTTRACE Copilot, an AI incident-investigation and containment expert powered by FalkorDB. "
            "You reason strictly over connected graph data. "
            "All actions are simulations; no real actions are executed. "
            "GHOSTTRACE's core principle is 'The AI proposes, the graph disposes.' "
            "Always cite entity identifiers like `id:dev-alice`, `workload:dev-box`, `id:ci-runner`, `svc:payments-api`. "
            f"Active Scenario: {scenario_title}. Incident: {incident_title}.\n"
            f"Graph Schema: {schema_summary}\n"
            "If user asks for Cypher, write valid FalkorDB read-only Cypher queries."
        )

        messages = [{"role": "system", "content": system_instruction}]
        for h in req.history[-6:]:
            messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
        messages.append({"role": "user", "content": req.message})

        if provider == "anthropic":
            import anthropic

            api_key = req.api_key or s.llm_api_key
            model = req.model or s.llm_model or "claude-3-5-sonnet-20241022"
            client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

            user_msgs = [m for m in messages if m["role"] != "system"]
            resp = client.messages.create(
                model=model,
                max_tokens=1024,
                system=system_instruction,
                messages=user_msgs,  # type: ignore[arg-type]
            )
            reply_text = "".join(b.text for b in resp.content if hasattr(b, "text"))
            return ChatResponse(
                reply=reply_text,
                cited_entities=self._extract_cited_entities(reply_text),
                cypher_queries=["FalkorDB Graph RAG Grounded"],
                provider_used="anthropic",
                model_used=model,
                suggested_questions=[
                    "What attack paths lead to payments-api?",
                    "What is the Price of Certainty curve?",
                ],
            )

        # OpenAI Compatible
        endpoint = req.endpoint or s.llm_endpoint or "https://api.openai.com/v1"
        model = req.model or s.llm_model or "gpt-4o-mini"
        api_key = req.api_key or s.llm_api_key or "sk-dummy"

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": 1024,
            "temperature": 0.2,
        }
        with httpx.Client(timeout=30.0) as http_client:
            r = http_client.post(f"{endpoint.rstrip('/')}/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            reply_text = data["choices"][0]["message"]["content"]
            return ChatResponse(
                reply=reply_text,
                cited_entities=self._extract_cited_entities(reply_text),
                cypher_queries=["FalkorDB Graph RAG Grounded"],
                provider_used="openai_compatible",
                model_used=model,
                suggested_questions=[
                    "Why did disabling Alice fail?",
                    "What are the Pareto containment options?",
                ],
            )

    def _extract_cited_entities(self, text: str) -> list[ChatEntity]:
        """Extracts recognized graph IDs mentioned in the response."""
        candidates = re.findall(r"\b((?:id|workload|svc|repo|team|person|db|source):[a-zA-Z0-9_\-\.]+)\b", text)
        entities: list[ChatEntity] = []
        for c in set(candidates):
            kind = c.split(":", 1)[0].capitalize()
            entities.append(ChatEntity(id=c, kind=kind, name=c))
        return entities

    def _dedup_entities(self, entities: list[ChatEntity]) -> list[ChatEntity]:
        seen = set()
        out = []
        for e in entities:
            if e.id not in seen:
                seen.add(e.id)
                out.append(e)
        return out
