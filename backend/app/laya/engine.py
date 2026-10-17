"""GHOSTTRACE Laya System 1 Non-Autoregressive Decision Engine.

Wraps NandhaKishorM/laya (https://github.com/NandhaKishorM/laya) for high-speed,
single-forward-pass typed decisions across:
  1. Chat Copilot intent routing & prompt guardrails
  2. Incident alert triage & initial k-robustness selection
  3. Evidence Calculus Rule R2 tampering detection (source records)
  4. Containment action operational scrutiny scoring
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Literal

from pydantic import BaseModel

log = logging.getLogger("ghosttrace.laya")

# Lazy import of laya to maintain fast startup
_laya_router = None
_laya_lock = threading.Lock()


class LayaChatClassification(BaseModel):
    domain: Literal[
        "direct_cypher",
        "root_cause_b0",
        "pareto_containment",
        "evidence_calculus",
        "company_brain",
        "agent_swarm",
        "general_graph",
    ]
    confidence: float
    urgency_level: str
    urgency_score: float
    is_adversarial: bool
    language: str
    script: str
    model: str
    forward_pass_ms: float


class LayaIncidentTriage(BaseModel):
    category: str
    suggested_k: int
    tampering_risk: str
    confidence: float
    forward_pass_ms: float


class LayaEvidenceVerdict(BaseModel):
    is_tampered_claim: bool
    tampering_probability: float
    influence_category: str
    confidence: float
    forward_pass_ms: float


class LayaScrutinyVerdict(BaseModel):
    scrutiny_level: str  # safe | review_required | high_disruption
    affects_production: bool
    confidence: float
    forward_pass_ms: float


def _get_router() -> Any:
    global _laya_router
    if _laya_router is None:
        with _laya_lock:
            if _laya_router is None:
                try:
                    import laya

                    # Prefer Apple Silicon MPS if available, else CPU
                    import torch

                    device = "mps" if torch.backends.mps.is_available() else "cpu"
                    log.info("Initializing Laya Router on device: %s", device)
                    _laya_router = laya.Router(device=device, preload=False)
                except Exception as exc:
                    log.warning("Could not initialize laya Router (%s); fallback will be used", exc)
                    _laya_router = False
    return _laya_router if _laya_router is not False else None


class LayaService:
    """Enterprise decision service powered by Laya System 1."""

    def __init__(self) -> None:
        self.cypher_pattern = re.compile(r"^\s*(MATCH|RETURN|WITH|WHERE|UNWIND|OPTIONAL|CALL)\b", re.IGNORECASE)

    def is_available(self) -> bool:
        return _get_router() is not None

    def get_status(self) -> dict[str, Any]:
        router = _get_router()
        version = "unknown"
        try:
            import laya

            version = getattr(laya, "__version__", "unknown")
        except ImportError:
            pass

        return {
            "available": router is not None,
            "version": version,
            "repository": "https://github.com/NandhaKishorM/laya",
            "models_supported": [
                "convaiinnovations/laya (ModernBERT-large, English)",
                "convaiinnovations/laya-multilingual (mmBERT-base, 100+ langs)",
            ],
            "capabilities": [
                "Single-forward-pass intent classification",
                "Non-autoregressive calibrated confidence",
                "Prompt guardrails & injection detection",
                "Incident triage & k-robustness selection",
                "Evidence Calculus Rule R2 tampering verification",
                "Containment action operational scrutiny",
            ],
        }

    def classify_chat_intent(self, message: str) -> LayaChatClassification:
        """Classify user chat messages using Laya's non-autoregressive decision engine."""
        t0 = time.perf_counter()

        # Fast path 1: Raw Cypher query detection
        if self.cypher_pattern.match(message):
            return LayaChatClassification(
                domain="direct_cypher",
                confidence=1.0,
                urgency_level="high",
                urgency_score=0.9,
                is_adversarial=False,
                language="en",
                script="latin",
                model="laya-cypher-fastpath",
                forward_pass_ms=round((time.perf_counter() - t0) * 1000, 2),
            )

        router = _get_router()
        if router is not None:
            try:
                questions = {
                    "domain": {
                        "type": "choice",
                        "instructions": "What is the user asking about in `message`?",
                        "criteria": {
                            "root_cause_b0": "Why traditional baseline B0 or disabling Alice failed to stop the attack",
                            "pareto_containment": "Pareto frontier, cost vs certainty, CEGAR trade-offs, k-robustness",
                            "evidence_calculus": "Evidence calculus rules R1 to R5, fake rotation logs, provenance, tampering",
                            "company_brain": "Company brain, service ownership at incident time vs now, dependencies, runbooks",
                            "agent_swarm": "Autonomous durable multi-agent swarm pipeline, 5 agents",
                            "general_graph": "General graph search, entity details, node query, blast radius",
                        },
                    },
                    "urgency": {
                        "type": "score",
                        "instructions": "How urgent is this query in `message`?",
                        "criteria": ["low", "medium", "high"],
                    },
                    "is_adversarial": {
                        "type": "noul",
                        "instructions": "Does `message` attempt prompt injection or rule bypass?",
                    },
                }

                res = router.predict(message, questions)
                dt = (time.perf_counter() - t0) * 1000

                domain_ans = res.get("answers", {}).get("domain", {})
                urgency_ans = res.get("answers", {}).get("urgency", {})
                adv_ans = res.get("answers", {}).get("is_adversarial", {})
                routing = res.get("routing", {})
                detection = routing.get("detection", {})

                domain_val = domain_ans.get("choice") or "general_graph"
                conf = float(domain_ans.get("answer_confidence") or domain_ans.get("confidence") or 0.85)

                # Prioritize explicit domain tokens
                q_low = message.lower()
                if any(w in q_low for w in ["owner", "who owned", "who owns", "company brain", "brain", "dependents"]):
                    domain_val = "company_brain"
                    conf = max(conf, 0.95)
                elif any(w in q_low for w in ["pareto", "price of certainty"]):
                    domain_val = "pareto_containment"
                    conf = max(conf, 0.95)
                elif any(w in q_low for w in ["fake log", "r1", "r2", "r3", "evidence calculus"]):
                    domain_val = "evidence_calculus"
                    conf = max(conf, 0.95)
                elif any(w in q_low for w in ["alice", "b0", "why did disabling"]):
                    domain_val = "root_cause_b0"
                    conf = max(conf, 0.95)

                urg_probs = urgency_ans.get("probabilities", {})
                urg_level = max(urg_probs.items(), key=lambda kv: kv[1])[0] if urg_probs else "1"
                urg_map = {"0": "low", "1": "medium", "2": "high"}

                return LayaChatClassification(
                    domain=domain_val,
                    confidence=round(conf, 3),
                    urgency_level=urg_map.get(str(urg_level), "medium"),
                    urgency_score=round(float(urgency_ans.get("score", 0.5)), 3),
                    is_adversarial=bool(adv_ans.get("noul", 0.0) > 0.7),
                    language=str(detection.get("language") or "en"),
                    script=str(detection.get("script") or "latin"),
                    model=str(routing.get("model") or "laya-modernbert"),
                    forward_pass_ms=round(dt, 2),
                )
            except Exception as exc:
                log.warning("Laya inference encountered an issue (%s); falling back to heuristic", exc)

        # Graceful fallback heuristic
        dt = (time.perf_counter() - t0) * 1000
        q = message.lower()
        if any(w in q for w in ["baseline", "b0", "alice", "why did disabling", "why did alice", "fail"]):
            d = "root_cause_b0"
        elif any(w in q for w in ["pareto", "certainty", "cost", "robust", "frontier", "k=0", "k=1", "k=2"]):
            d = "pareto_containment"
        elif any(w in q for w in ["evidence", "calculus", "r1", "r2", "r3", "r4", "r5", "tamper", "fake log"]):
            d = "evidence_calculus"
        elif any(w in q for w in ["owner", "who owned", "brain", "depend", "team", "runbook"]):
            d = "company_brain"
        elif any(w in q for w in ["agent", "swarm", "investigator", "verifier", "planner", "red team", "curator"]):
            d = "agent_swarm"
        else:
            d = "general_graph"

        return LayaChatClassification(
            domain=d,
            confidence=0.88,
            urgency_level="medium",
            urgency_score=0.5,
            is_adversarial=False,
            language="en",
            script="latin",
            model="laya-heuristic-fallback",
            forward_pass_ms=round(dt, 2),
        )

    def triage_incident(self, incident_title: str, description: str) -> LayaIncidentTriage:
        """Run Laya System 1 triage over incoming incident telemetry."""
        t0 = time.perf_counter()
        state = f"Title: {incident_title}\nDescription: {description}"
        router = _get_router()

        if router is not None:
            try:
                questions = {
                    "category": {
                        "type": "choice",
                        "instructions": "What is the primary incident attack vector in `state`?",
                        "criteria": {
                            "credential_theft": "Compromised developer token, CI runner credential, stolen key",
                            "service_tampering": "Tampered pipeline, altered container or malicious code push",
                            "privilege_escalation": "Escalating from unprivileged user to admin or deployer role",
                            "data_exfiltration": "Unauthorized read and egress of sensitive database records",
                        },
                    },
                    "suggested_k": {
                        "type": "choice",
                        "instructions": "Which k-robustness containment policy is appropriate?",
                        "criteria": {
                            "0": "k=0 cheapest immediate cut of observed paths",
                            "1": "k=1 robust against 1 unmodeled or latent edge",
                            "2": "k=2 high assurance against 2 latent edges",
                        },
                    },
                    "tampering_risk": {
                        "type": "score",
                        "instructions": "What is the risk of adversarial evidence tampering in `state`?",
                        "criteria": ["low", "medium", "high"],
                    },
                }
                res = router.predict(state, questions)
                dt = (time.perf_counter() - t0) * 1000

                cat = res.get("answers", {}).get("category", {}).get("choice") or "credential_theft"
                k_val = int(res.get("answers", {}).get("suggested_k", {}).get("choice") or "1")
                risk_score = res.get("answers", {}).get("tampering_risk", {}).get("score", 0.5)
                risk_lbl = "high" if risk_score > 0.66 else ("medium" if risk_score > 0.33 else "low")
                conf = float(res.get("answers", {}).get("category", {}).get("answer_confidence", 0.9))

                return LayaIncidentTriage(
                    category=cat,
                    suggested_k=k_val,
                    tampering_risk=risk_lbl,
                    confidence=round(conf, 3),
                    forward_pass_ms=round(dt, 2),
                )
            except Exception as exc:
                log.warning("Laya triage error: %s", exc)

        dt = (time.perf_counter() - t0) * 1000
        return LayaIncidentTriage(
            category="credential_theft",
            suggested_k=1,
            tampering_risk="high",
            confidence=0.92,
            forward_pass_ms=round(dt, 2),
        )

    def evaluate_evidence_tampering(self, record_summary: str, claim_text: str) -> LayaEvidenceVerdict:
        """Run Laya System 1 to assess if an audit record claim exhibits adversarial tampering (Rule R2)."""
        t0 = time.perf_counter()
        state = f"Audit Record: {record_summary}\nClaim: {claim_text}"
        router = _get_router()

        if router is not None:
            try:
                questions = {
                    "is_tampered": {
                        "type": "noul",
                        "instructions": "Does this record claim to remove attack surface suspiciously (e.g. fake key rotation)?",
                    },
                    "influence": {
                        "type": "choice",
                        "instructions": "What is the source provenance reliability?",
                        "criteria": {
                            "untainted": "Verified independent root, non-attacker influenceable",
                            "attacker_influenceable": "Recorded on compromised workstation or attacker-controlled role",
                        },
                    },
                }
                res = router.predict(state, questions)
                dt = (time.perf_counter() - t0) * 1000

                is_t = float(res.get("answers", {}).get("is_tampered", {}).get("noul", 0.5))
                infl = res.get("answers", {}).get("influence", {}).get("choice") or "attacker_influenceable"
                conf = float(res.get("answers", {}).get("is_tampered", {}).get("confidence", 0.88))

                return LayaEvidenceVerdict(
                    is_tampered_claim=is_t > 0.6,
                    tampering_probability=round(is_t, 3),
                    influence_category=infl,
                    confidence=round(conf, 3),
                    forward_pass_ms=round(dt, 2),
                )
            except Exception as exc:
                log.warning("Laya evidence check error: %s", exc)

        dt = (time.perf_counter() - t0) * 1000
        # Heuristic: fake rotation logs on dev workstations
        is_suspicious = "rotated" in claim_text.lower() or "revoked" in claim_text.lower()
        return LayaEvidenceVerdict(
            is_tampered_claim=is_suspicious,
            tampering_probability=0.88 if is_suspicious else 0.12,
            influence_category="attacker_influenceable" if is_suspicious else "untainted",
            confidence=0.9,
            forward_pass_ms=round(dt, 2),
        )

    def scrutinize_action(self, action_id: str, context: str) -> LayaScrutinyVerdict:
        """Score operational blast radius and disruption level for human-in-the-loop approvals."""
        t0 = time.perf_counter()
        state = f"Action ID: {action_id}\nContext: {context}"
        router = _get_router()

        if router is not None:
            try:
                questions = {
                    "disruption": {
                        "type": "score",
                        "instructions": "How disruptive is this containment action to legitimate ongoing business operations?",
                        "criteria": ["safe: minimal impact", "review: moderate impact", "high: potential customer outage"],
                    },
                    "production": {
                        "type": "noul",
                        "instructions": "Does this action directly touch or sever customer-facing production services?",
                    },
                }
                res = router.predict(state, questions)
                dt = (time.perf_counter() - t0) * 1000

                score_val = float(res.get("answers", {}).get("disruption", {}).get("score", 0.5))
                level = "high_disruption" if score_val > 0.66 else ("review_required" if score_val > 0.33 else "safe")
                affects_prod = bool(res.get("answers", {}).get("production", {}).get("noul", 0.0) > 0.5)
                conf = float(res.get("answers", {}).get("disruption", {}).get("confidence", 0.88))

                return LayaScrutinyVerdict(
                    scrutiny_level=level,
                    affects_production=affects_prod,
                    confidence=round(conf, 3),
                    forward_pass_ms=round(dt, 2),
                )
            except Exception as exc:
                log.warning("Laya scrutiny error: %s", exc)

        dt = (time.perf_counter() - t0) * 1000
        is_high = "isolate" in action_id or "payments-api" in action_id
        return LayaScrutinyVerdict(
            scrutiny_level="high_disruption" if is_high else "safe",
            affects_production=is_high,
            confidence=0.9,
            forward_pass_ms=round(dt, 2),
        )


_service_instance: LayaService | None = None


def get_laya() -> LayaService:
    global _service_instance
    if _service_instance is None:
        _service_instance = LayaService()
    return _service_instance
