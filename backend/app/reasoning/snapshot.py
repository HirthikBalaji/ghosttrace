"""Snapshot construction: the set of edges active (or validity-uncertain) at (T, tau) under a trust policy.

Pure function over edge versions + source records. Used by the planner, the certificate exporter, the
load-bearing-evidence analysis (with a `falsified` source set) and as the reference implementation that
FalkorDB query results are differential-tested against.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping

from app.model import EdgeVersion, EpistemicClass, Flag, SnapEdge, SourceRecord, TrustPolicy
from app.reasoning.evidence import classify_asserted, dispute_flags, policy_filter
from app.temporal.predicate import TemporalStatus, temporal_status, validity_unknown


def _apply_falsification(v: EdgeVersion, falsified: frozenset[str]) -> EdgeVersion:
    """If every record that closed this version's validity is falsified, restore the prior end."""
    if v.valid_to_source_ids and set(v.valid_to_source_ids) <= falsified:
        vt, open_ = v.prior_valid_to, v.prior_valid_open_ended
        return dataclasses.replace(
            v,
            valid_to=vt,
            valid_open_ended=open_,
            validity_unknown=validity_unknown(v.valid_from, vt, open_),
        )
    return v


def build_snapshot(
    versions: Iterable[EdgeVersion],
    sources: Mapping[str, SourceRecord],
    T: int,
    tau: int,
    policy: TrustPolicy,
    falsified: frozenset[str] = frozenset(),
) -> dict[str, SnapEdge]:
    """Return {edge_id: SnapEdge} for every fact edge active or uncertain at (T, tau)."""
    live: dict[str, tuple[EdgeVersion, TemporalStatus]] = {}
    for v0 in versions:
        v = _apply_falsification(v0, falsified)
        st = temporal_status(v, T, tau)
        if st in (TemporalStatus.ACTIVE, TemporalStatus.UNCERTAIN):
            if v.edge_id in live:
                raise ValueError(f"two visible versions of fact {v.edge_id} at tau={tau}")
            live[v.edge_id] = (v, st)

    out: dict[str, SnapEdge] = {}
    derived: list[tuple[EdgeVersion, TemporalStatus]] = []
    for v, st in live.values():
        if v.kind == "derived":
            derived.append((v, st))
            continue
        flags: list[str] = []
        if v.kind == "latent":
            if not v.template_id:
                raise ValueError(f"latent edge {v.edge_id} has no template")
            cls = EpistemicClass.LATENT
            support = policy_filter(v.source_ids, sources, policy, falsified)
        else:
            support = policy_filter(v.source_ids, sources, policy, falsified)
            if not support:
                continue  # all evidence excluded by policy or falsified: the edge is not in this world
            cls, flags = classify_asserted(support, sources)
        flags += dispute_flags(v.dispute_source_ids, sources, policy, falsified)
        if v.stale:
            flags.append(Flag.STALE.value)
        out[v.edge_id] = SnapEdge(
            edge_id=v.edge_id,
            version=v.version,
            type=v.type,
            src=v.src,
            dst=v.dst,
            src_type=v.src_type,
            dst_type=v.dst_type,
            cls=cls.value,
            temporal=st.value,
            flags=flags,
            template_id=v.template_id,
            verify_cost=v.verify_cost,
            source_ids=support,
            dispute_source_ids=list(v.dispute_source_ids),
            cost_remove=v.cost_remove,
        )

    # DERIVED: deterministic rules over parent facts; weakest parent decides the class.
    for v, st in sorted(derived, key=lambda x: x[0].edge_id):
        parents = [out.get(p) for p in v.parent_ids]
        if any(p is None for p in parents):
            continue
        weak = any(p.cls == EpistemicClass.LATENT for p in parents if p is not None)
        flags = [Flag.WEAKLY_SUPPORTED.value] if weak else []
        if any(Flag.DISPUTED.value in p.flags for p in parents if p is not None):
            flags.append(Flag.DISPUTED.value)
        support = sorted({s for p in parents if p is not None for s in p.source_ids})
        out[v.edge_id] = SnapEdge(
            edge_id=v.edge_id,
            version=v.version,
            type=v.type,
            src=v.src,
            dst=v.dst,
            src_type=v.src_type,
            dst_type=v.dst_type,
            cls=(EpistemicClass.LATENT if weak else EpistemicClass.DERIVED).value,
            temporal=st.value,
            flags=flags,
            template_id=v.template_id or ("derived_weak" if weak else None),
            verify_cost=v.verify_cost,
            source_ids=support,
            cost_remove=v.cost_remove,
        )
    return out


def traversal_edges(snap: Mapping[str, SnapEdge]) -> list[SnapEdge]:
    from app.model import TRAVERSAL_EDGE_TYPES

    return sorted((e for e in snap.values() if e.type in TRAVERSAL_EDGE_TYPES), key=lambda e: e.edge_id)
