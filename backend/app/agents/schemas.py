"""Typed, distinct input/output schemas per agent (Pydantic v2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

PathClass = str  # CONFIRMED | CONDITIONAL(k) | TEMPORALLY_UNCERTAIN


class PathOut(BaseModel):
    edge_ids: list[str]
    node_ids: list[str]
    path_class: PathClass
    latent_count: int
    uncertain_count: int
    assumptions: list[str]
    edge_classes: list[str]  # class per edge, from the deterministic snapshot

    @model_validator(mode="after")
    def _no_false_confirmation(self) -> PathOut:
        if self.path_class == "CONFIRMED" and any(c != "CONFIRMED" for c in self.edge_classes):
            raise ValueError("a path with a non-confirmed edge must not be labelled CONFIRMED")
        return self


class Hypothesis(BaseModel):
    id: str
    title: str
    kind: Literal["attack_path", "benign_prior_pattern"]
    target_ids: list[str]
    pivot_id: str | None = None
    path_class: PathClass | None
    paths: list[PathOut] = []
    supporting_evidence_ids: list[str] = []
    contradicting_evidence_ids: list[str] = []
    assumptions: list[str] = []
    unknowns: list[str] = []
    known_at_incident_time: bool | None = None


# ---- A. Investigator
class InvestigatorInput(BaseModel):
    investigation_id: str
    incident_id: str
    T_incident: int
    T_now: int
    tau: int
    max_depth: int = Field(8, ge=1, le=12)


class InvestigatorOutput(BaseModel):
    hypotheses: list[Hypothesis]
    paths: list[PathOut]
    supporting_evidence_ids: list[str]
    contradicting_evidence_ids: list[str]
    assumptions: list[str]
    unknowns: list[str]
    recommended_next_queries: list[str]
    reasoning_summary: str
    memory_consulted: list[dict[str, Any]] = []
    status: Literal["completed", "partial"]


# ---- B. Evidence verifier
class HypothesisVerdict(BaseModel):
    hypothesis_id: str
    status: Literal["supported", "partially_supported", "disputed", "insufficient_evidence"]
    reasons: list[str]
    citations_resolved: int
    citations_total: int
    independent_roots: int
    temporal_check: str
    flags: list[str] = []


class VerifierInput(BaseModel):
    investigation_id: str
    hypothesis_ids: list[str]
    T_incident: int
    tau: int


class VerifierOutput(BaseModel):
    verdicts: list[HypothesisVerdict]
    stale_runbooks: list[dict[str, Any]]
    disputed_removals: list[dict[str, Any]]
    injection_flags: list[dict[str, Any]]
    duplicate_evidence: list[dict[str, Any]]
    notes: list[str]


# ---- C. Containment planner
class PlannerInput(BaseModel):
    investigation_id: str
    T: int
    tau: int
    K: int = Field(2, ge=0, le=4)
    policy: Literal["conservative_defense", "trust_filtered"] = "conservative_defense"


class PlannerOutput(BaseModel):
    plan_ids: list[str]
    certificate_ids: list[str]
    pareto: list[dict[str, Any]]
    sensitivity: list[dict[str, Any]]
    baseline_b0: dict[str, Any]
    explanation: str
    advisor: dict[str, Any] = {}


# ---- F. Red team
class RedTeamInput(BaseModel):
    investigation_id: str
    certificate_ids: list[str]
    tau: int


class RedTeamOutput(BaseModel):
    findings: list[dict[str, Any]]
    nominations: list[dict[str, Any]]
    downgraded_certificate_ids: list[str]
    tampering_scenarios: list[dict[str, Any]]
    replan_required: bool
    tau_after: int


# ---- E. Memory curator
class CuratorInput(BaseModel):
    investigation_id: str


class CuratorOutput(BaseModel):
    written: list[dict[str, Any]]
    promotions: list[dict[str, Any]]


# ---- D. Company brain
class BrainQuery(BaseModel):
    question: Literal["owner", "experts", "dependencies", "dependents", "runbooks", "decisions"]
    subject_id: str = Field(min_length=1, max_length=120)
    T: int
    tau: int


class BrainAnswer(BaseModel):
    question: str
    subject_id: str
    answer: str
    primary: list[dict[str, Any]]
    supporting_edge_ids: list[str]
    source_ids: list[str]
    temporal_scope: dict[str, Any]
    warnings: list[str]
    contradictions: list[dict[str, Any]]
    unknowns: list[str]
    paths: list[list[str]] = []
