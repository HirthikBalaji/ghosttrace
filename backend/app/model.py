"""Core in-memory domain model shared by ingestion, reasoning and the planner."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class TrustPolicy(StrEnum):
    CONSERVATIVE = "conservative_defense"
    TRUST_FILTERED = "trust_filtered"


class EpistemicClass(StrEnum):
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    LATENT = "LATENT"


class Flag(StrEnum):
    DISPUTED = "disputed"
    STALE = "stale"
    SUPERSEDED = "superseded"
    WEAKLY_SUPPORTED = "weakly_supported"
    POSSIBLE_FALSE_FLAG = "possible_false_flag"


# Capability-flow edges: u -> v means "control of u yields capability over v".
TRAVERSAL_EDGE_TYPES: tuple[str, ...] = (
    "HAS_CREDENTIAL", "AUTHENTICATES_AS", "CAN_ASSUME", "CAN_ACCESS", "CONNECTS_TO", "DEPLOYS_TO",
)
# Organizational / knowledge edges (Company Brain); same bitemporal schema, never traversed for attack paths.
KNOWLEDGE_EDGE_TYPES: tuple[str, ...] = (
    "OWNS", "MEMBER_OF", "KNOWS_ABOUT", "DEPENDS_ON", "APPLIES_TO", "HAS_POLICY", "BUILT_BY",
    "RUNS_ON", "RECORDED_IN", "AFFECTS", "MITIGATES", "RECOMMENDS", "RELATED_TO", "DEPLOYED_FROM",
)
ALL_FACT_EDGE_TYPES = TRAVERSAL_EDGE_TYPES + KNOWLEDGE_EDGE_TYPES

NODE_LABELS: tuple[str, ...] = (
    "Person", "Team", "Identity", "Credential", "Asset", "Service", "Repository", "Deployment", "BuildRunner",
    "Host", "Group", "Policy", "Runbook", "Document", "Decision", "SecurityEvent", "Incident",
)


@dataclass
class SourceRecord:
    source_id: str
    integrity: str  # signed | hash_verified | none
    attacker_influenceable: bool
    root_id: str
    trust_class: str  # high | medium | low
    observed_at: int
    ingested_at: int
    derived_from: list[str] = field(default_factory=list)
    system: str = ""
    content: str = ""
    contains_instructions: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EdgeVersion:
    """One bitemporal version of a fact edge. Facts are never deleted; versions supersede."""

    edge_id: str  # stable fact id
    version: int
    type: str
    src: str
    dst: str
    src_type: str
    dst_type: str
    workspace_id: str
    tx_from: int
    tx_to: int | None = None
    valid_from: int | None = None
    valid_to: int | None = None
    valid_open_ended: bool = False
    validity_unknown: bool = False
    kind: str = "asserted"  # asserted | derived | latent
    source_ids: list[str] = field(default_factory=list)
    dispute_source_ids: list[str] = field(default_factory=list)
    valid_to_source_ids: list[str] = field(default_factory=list)
    prior_valid_to: int | None = None
    prior_valid_open_ended: bool = False
    rule_id: str | None = None
    parent_ids: list[str] = field(default_factory=list)
    template_id: str | None = None
    verify_cost: int = 1
    stale: bool = False
    cost_remove: int | None = None
    created_by: str = "ingestion"
    note: str = ""
    supersedes: int | None = None

    @property
    def version_key(self) -> str:
        return f"{self.edge_id}@{self.version}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Node:
    id: str
    label: str
    workspace_id: str
    name: str = ""
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class Flow:
    flow_id: str
    u: str
    v: str
    weight: int
    kind: str  # hard | soft
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"flow_id": self.flow_id, "u": self.u, "v": self.v, "weight": self.weight, "kind": self.kind}


@dataclass
class SnapEdge:
    """An edge as it appears in the (T, tau, policy) snapshot."""

    edge_id: str
    version: int
    type: str
    src: str
    dst: str
    src_type: str
    dst_type: str
    cls: str
    temporal: str
    flags: list[str] = field(default_factory=list)
    template_id: str | None = None
    verify_cost: int = 1
    source_ids: list[str] = field(default_factory=list)
    dispute_source_ids: list[str] = field(default_factory=list)
    cost_remove: int | None = None

    @property
    def confirmed(self) -> bool:
        return self.cls in (EpistemicClass.OBSERVED, EpistemicClass.DERIVED) and self.temporal == "ACTIVE"

    def export(self) -> dict[str, Any]:
        return {
            "kind": "edge", "edge_id": self.edge_id, "version": self.version, "type": self.type,
            "src": self.src, "dst": self.dst, "src_type": self.src_type, "dst_type": self.dst_type,
            "cls": self.cls, "temporal": self.temporal, "flags": sorted(self.flags),
            "template_id": self.template_id, "verify_cost": self.verify_cost,
        }
