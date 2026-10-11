"""Adversarial evidence calculus: rules R1-R3 and source independence (§3.3). Pure functions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from app.model import EpistemicClass, Flag, SourceRecord, TrustPolicy

VERIFIED_INTEGRITY = ("signed", "hash_verified")


def _ancestors(sid: str, sources: Mapping[str, SourceRecord]) -> set[str]:
    seen: set[str] = set()
    stack = list(sources[sid].derived_from) if sid in sources else []
    while stack:
        x = stack.pop()
        if x in seen:
            continue
        seen.add(x)
        if x in sources:
            stack.extend(sources[x].derived_from)
    return seen


def independent(a: str, b: str, sources: Mapping[str, SourceRecord]) -> bool:
    """Distinct root_id and neither derives from the other in the provenance DAG."""
    sa, sb = sources[a], sources[b]
    if sa.root_id == sb.root_id:
        return False
    return a not in _ancestors(b, sources) and b not in _ancestors(a, sources)


def independent_root_count(ids: Iterable[str], sources: Mapping[str, SourceRecord]) -> int:
    """Size of a greedy maximal set of mutually independent sources (counts distinct roots, not records)."""
    chosen: list[str] = []
    for sid in sorted(set(ids)):
        if sid in sources and all(independent(sid, c, sources) for c in chosen):
            chosen.append(sid)
    return len(chosen)


def policy_filter(
    ids: Iterable[str], sources: Mapping[str, SourceRecord], policy: TrustPolicy, falsified: frozenset[str] = frozenset()
) -> list[str]:
    out = [s for s in ids if s in sources and s not in falsified]
    if policy == TrustPolicy.TRUST_FILTERED:
        out = [s for s in out if not sources[s].attacker_influenceable]
    return out


def meets_r1(ids: Iterable[str], sources: Mapping[str, SourceRecord]) -> bool:
    """R1: >=1 integrity-verified non-attacker-influenceable source, or >=2 independent sources."""
    ids = [s for s in ids if s in sources]
    if any(sources[s].integrity in VERIFIED_INTEGRITY and not sources[s].attacker_influenceable for s in ids):
        return True
    return independent_root_count(ids, sources) >= 2


def trusted_removal(ids: Iterable[str], sources: Mapping[str, SourceRecord]) -> bool:
    """R2: a surface-removing claim is honored only if R1 holds using non-attacker-influenceable sources."""
    return meets_r1([s for s in ids if s in sources and not sources[s].attacker_influenceable], sources)


def classify_asserted(support: list[str], sources: Mapping[str, SourceRecord]) -> tuple[EpistemicClass, list[str]]:
    """Classify a surface-expanding assertion from its (already policy-filtered) support."""
    if support and all(sources[s].attacker_influenceable for s in support):
        return EpistemicClass.LATENT, [Flag.POSSIBLE_FALSE_FLAG.value]  # R3
    if meets_r1(support, sources):
        return EpistemicClass.OBSERVED, []
    return EpistemicClass.LATENT, [Flag.WEAKLY_SUPPORTED.value]  # R1 not met


def dispute_flags(
    dispute_ids: list[str], sources: Mapping[str, SourceRecord], policy: TrustPolicy, falsified: frozenset[str] = frozenset()
) -> list[str]:
    """R2: untrusted removal claims mark the edge disputed; the edge still counts for containment."""
    return [Flag.DISPUTED.value] if policy_filter(dispute_ids, sources, policy, falsified) else []


def false_flag_only(support: list[str], sources: Mapping[str, SourceRecord]) -> bool:
    return bool(support) and all(sources[s].attacker_influenceable for s in support if s in sources)
