"""Allowlisted LATENT-edge templates (§3.2).

A LATENT edge is a *candidate* capability that was not observed. It may be created only by instantiating
one of these templates, and only if its preconditions hold over the graph. A language model (or the Red
Team agent) may *nominate* an instantiation; `check_preconditions` decides. The precondition is executed
as a constant, parameterised Cypher query against FalkorDB (`CYPHER`), and mirrored here in Python over a
snapshot for pure tests; the two are differential-tested.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.model import SnapEdge
from app.temporal.predicate import temporal_predicate

_P = temporal_predicate


@dataclass(frozen=True)
class Template:
    template_id: str
    edge_type: str
    src_types: frozenset[str]
    dst_types: frozenset[str]
    verify_cost: int
    explanation: str
    cypher: str  # returns one row with column `ok` (boolean); params $src $dst $T $tau


TEMPLATES: dict[str, Template] = {
    t.template_id: t for t in [
        Template(
            "group_inheritance_unmodeled", "CAN_ASSUME",
            frozenset({"Service", "Identity", "Host", "BuildRunner"}), frozenset({"Identity"}), 2,
            "src shares an undeclared group with a peer that can assume dst; group-level trust may be inherited.",
            "MATCH (s {id:$src})-[m1:MEMBER_OF]->(g:Group)<-[m2:MEMBER_OF]-(peer)-[r:CAN_ASSUME]->(d {id:$dst}) "
            f"WHERE peer.id <> s.id AND {_P('m1')} AND {_P('m2')} AND {_P('r')} RETURN count(*) > 0 AS ok",
        ),
        Template(
            "ci_trigger_unmodeled", "CAN_ASSUME", frozenset({"Repository"}), frozenset({"Identity"}), 1,
            "dst builds src; pushing code to src may execute in dst's context (pipeline injection).",
            "MATCH (s:Repository {id:$src})-[r:BUILT_BY]->(d:Identity {id:$dst}) "
            f"WHERE {_P('r')} RETURN count(*) > 0 AS ok",
        ),
        Template(
            "network_adjacency_unmodeled", "CONNECTS_TO",
            frozenset({"Host", "Service", "BuildRunner"}), frozenset({"Host", "Service", "Asset"}), 3,
            "src and dst sit in the same network segment; an unmodeled route may exist.",
            "MATCH (s {id:$src}), (d {id:$dst}) WHERE s.segment IS NOT NULL AND s.segment = d.segment "
            "AND s.id <> d.id RETURN count(*) > 0 AS ok",
        ),
        Template(
            "shared_secret_path", "HAS_CREDENTIAL", frozenset({"Host", "Service", "BuildRunner"}),
            frozenset({"Credential"}), 2,
            "src runs on the same host as a holder of credential dst; the secret may be readable.",
            "MATCH (s {id:$src})-[r1:RUNS_ON]->(h:Host)<-[r2:RUNS_ON]-(holder)-[r3:HAS_CREDENTIAL]->(c:Credential {id:$dst}) "
            f"WHERE holder.id <> s.id AND {_P('r1')} AND {_P('r2')} AND {_P('r3')} RETURN count(*) > 0 AS ok",
        ),
        Template(
            "wildcard_policy_expansion", "CAN_ACCESS", frozenset({"Identity"}), frozenset({"Service", "Asset"}), 2,
            "src holds a wildcard policy whose pattern matches dst's id.",
            "MATCH (s:Identity {id:$src})-[r:HAS_POLICY]->(p:Policy), (d {id:$dst}) "
            f"WHERE p.wildcard_prefix IS NOT NULL AND d.id STARTS WITH p.wildcard_prefix AND {_P('r')} "
            "RETURN count(*) > 0 AS ok",
        ),
    ]
}


class TemplateRejected(ValueError):
    pass


def check_types(template_id: str, src_type: str | None, dst_type: str | None) -> Template:
    t = TEMPLATES.get(template_id)
    if t is None:
        raise TemplateRejected(f"template {template_id!r} is not allowlisted")
    if src_type not in t.src_types or dst_type not in t.dst_types:
        raise TemplateRejected(f"{template_id}: node types ({src_type}, {dst_type}) do not fit the template")
    return t


def check_preconditions_py(template_id: str, src: str, dst: str, snap: Mapping[str, SnapEdge],
                           node_props: Mapping[str, Mapping[str, Any]]) -> bool:
    """Python mirror of the Cypher preconditions over a (T, tau) snapshot of all fact edges."""
    edges = list(snap.values())
    if template_id == "group_inheritance_unmodeled":
        groups = {e.dst for e in edges if e.type == "MEMBER_OF" and e.src == src and e.dst_type == "Group"}
        peers = {e.src for e in edges if e.type == "MEMBER_OF" and e.dst in groups and e.src != src}
        return any(e.type == "CAN_ASSUME" and e.src in peers and e.dst == dst for e in edges)
    if template_id == "ci_trigger_unmodeled":
        return any(e.type == "BUILT_BY" and e.src == src and e.dst == dst for e in edges)
    if template_id == "network_adjacency_unmodeled":
        a, b = node_props.get(src, {}).get("segment"), node_props.get(dst, {}).get("segment")
        return a is not None and a == b and src != dst
    if template_id == "shared_secret_path":
        hosts = {e.dst for e in edges if e.type == "RUNS_ON" and e.src == src}
        holders = {e.src for e in edges if e.type == "RUNS_ON" and e.dst in hosts and e.src != src}
        return any(e.type == "HAS_CREDENTIAL" and e.src in holders and e.dst == dst for e in edges)
    if template_id == "wildcard_policy_expansion":
        pols = {e.dst for e in edges if e.type == "HAS_POLICY" and e.src == src}
        return any(dst.startswith(str(node_props.get(p, {}).get("wildcard_prefix") or "\0")) for p in pols)
    raise TemplateRejected(f"template {template_id!r} is not allowlisted")
