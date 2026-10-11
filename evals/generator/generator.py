"""Seeded, deterministic generator of synthetic organisation graphs with planted ground truth (§4.3).

Emits (a) a scenario dict in the same schema as data/scenarios/*.json — the *visible world* the system
sees — and (b) a ground-truth world W* = edges truly present at planning time T, used only by the
evaluator. W* contains: visible OBSERVED edges that are true, hidden-true latent edges (drawn from the
declared prior), edges whose removal was claimed by attacker-influenceable logs (still true), and a few
unmodeled edges invisible to the system. Decoy (attacker-planted) edges are false in W*.

Generator latent edges are inserted directly as template instantiations (preconditions bypassed); the
template engine itself is tested separately.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

BASE = datetime(2026, 1, 1, tzinfo=UTC)

TYPE_MAP: dict[tuple[str, str], str] = {
    ("Identity", "Host"): "CAN_ACCESS", ("Identity", "Service"): "CAN_ACCESS", ("Identity", "Asset"): "CAN_ACCESS",
    ("Identity", "Identity"): "CAN_ASSUME", ("Host", "Credential"): "HAS_CREDENTIAL",
    ("Service", "Credential"): "HAS_CREDENTIAL", ("Credential", "Identity"): "AUTHENTICATES_AS",
    ("Host", "Service"): "CONNECTS_TO", ("Service", "Service"): "CAN_ACCESS", ("Service", "Asset"): "CAN_ACCESS",
    ("Host", "Host"): "CONNECTS_TO", ("Host", "Asset"): "CAN_ACCESS",
}
LATENT_TEMPLATE = {"CAN_ASSUME": "group_inheritance_unmodeled", "CONNECTS_TO": "network_adjacency_unmodeled",
                   "HAS_CREDENTIAL": "shared_secret_path", "CAN_ACCESS": "wildcard_policy_expansion"}
VERIFY_COST = {"group_inheritance_unmodeled": 2, "network_adjacency_unmodeled": 3, "shared_secret_path": 2,
               "wildcard_policy_expansion": 2}
MID_TYPES = ["Host", "Credential", "Identity", "Service", "Identity", "Credential"]


def iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


@dataclass
class GenParams:
    n_mid: int = 10
    n_paths: int = 2
    branching: float = 1.2
    latent_density: float = 0.12
    p_latent_true: float = 0.3
    decoy: bool = True
    churn: bool = True
    n_hard: int = 2
    n_soft: int = 2
    ai_frac: float = 0.08
    weak_frac: float = 0.08
    hidden_unmodeled: int = 1
    n_targets: int = 1


@dataclass
class Instance:
    seed: int
    params: GenParams
    scenario: dict[str, Any]
    truth_edges: list[dict[str, str]]  # W*: {"id","src","dst","type"} true at planning time
    decoy_edge_ids: list[str] = field(default_factory=list)
    decoy_target: str | None = None


def generate(seed: int, p: GenParams | None = None) -> Instance:
    p = p or GenParams()
    rng = random.Random(seed)
    T_inc = BASE + timedelta(days=30)
    now = T_inc + timedelta(days=7)
    nodes: list[dict[str, Any]] = []
    types: dict[str, str] = {}

    def node(nid: str, label: str, **props: Any) -> None:
        types[nid] = label
        nodes.append({"id": nid, "label": label, "name": nid, **props})

    node("id:src-user", "Identity", cost_disable=rng.randint(1, 4))
    node("host:src-ws", "Host", cost_isolate=rng.randint(3, 9))
    sources = ["id:src-user", "host:src-ws"]
    targets = []
    for i in range(p.n_targets):
        node(f"asset:t{i}", "Asset", cost_isolate=rng.randint(15, 30))
        targets.append(f"asset:t{i}")
    for i in range(p.n_mid):
        t = MID_TYPES[rng.randrange(len(MID_TYPES))] if i >= 4 else ["Host", "Credential", "Identity", "Service"][i]
        cost = {"Identity": "cost_disable", "Credential": "cost_revoke", "Host": "cost_isolate", "Service": "cost_isolate"}[t]
        node(f"n{i}:{t.lower()}", t, **{cost: rng.randint(1, 12)})
    mids = [n["id"] for n in nodes if n["id"] not in sources + targets]

    src_recs: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    truth: list[dict[str, str]] = []
    decoys: list[str] = []
    revoked: set[str] = set()
    edges_seen: set[tuple[str, str]] = set()
    t_assert = iso(BASE + timedelta(days=1))

    def source(sid: str, integrity: str, root: str, trust: str, written_on: str | None = None,
               derived_from: list[str] | None = None) -> str:
        rec = {"source_id": sid, "system": "gen", "integrity": integrity, "root_id": root, "trust_class": trust,
               "observed_at": t_assert, "ingested_at": t_assert, "content": f"synthetic record {sid}"}
        if written_on:
            rec["written_on"] = written_on
        if derived_from:
            rec["derived_from"] = derived_from
        src_recs.append(rec)
        return sid

    def add_edge(a: str, b: str, force_true: bool = False) -> str | None:
        et = TYPE_MAP.get((types[a], types[b]))
        if et is None or a == b or (a, b) in edges_seen or b in sources or a in targets:
            return None
        edges_seen.add((a, b))
        eid = f"g:{a}->{b}"
        r = rng.random()
        ev: dict[str, Any] = {"op": "assert", "at": t_assert, "fact_id": eid, "type": et, "src": a, "dst": b,
                              "valid_from": iso(BASE), "valid_open_ended": True,
                              "cost_remove": rng.randint(1, 8)}
        true_now = True
        if not force_true and r < p.ai_frac:
            ev["sources"] = [source(f"s:{eid}:ai", "none", f"root:{eid}:ai", "low", written_on="host:src-ws")]
            decoys.append(eid)
            true_now = False  # planted by the attacker
        elif not force_true and r < p.ai_frac + p.weak_frac:
            s1 = source(f"s:{eid}:w1", "none", f"root:{eid}", "medium")
            s2 = source(f"s:{eid}:w2", "none", f"root:{eid}", "medium", derived_from=[s1])
            ev["sources"] = [s1, s2]  # duplicate root => counted once => LATENT weakly_supported
            true_now = rng.random() < 0.5
        else:
            ev["sources"] = [source(f"s:{eid}", "signed", f"root:{eid}", "high")]
        events.append(ev)
        if p.churn and not force_true and true_now and rng.random() < 0.08:
            # trusted revocation before planning time: inactive now (false in W*)
            rs = source(f"s:{eid}:revoke", "signed", f"root:{eid}:revoke", "high")
            events.append({"op": "remove", "at": iso(T_inc - timedelta(days=2)), "fact_id": eid,
                           "removed_at": iso(T_inc - timedelta(days=2)), "sources": [rs]})
            revoked.add(eid)
            true_now = False
        elif p.churn and true_now and rng.random() < 0.08:
            # attacker-written log claims removal; edge is in fact still present (R2 case)
            rs = source(f"s:{eid}:fakerevoke", "none", f"root:{eid}:fake", "low", written_on="host:src-ws")
            events.append({"op": "remove", "at": iso(T_inc + timedelta(hours=2)), "fact_id": eid,
                           "removed_at": iso(T_inc + timedelta(hours=1)), "sources": [rs]})
        if true_now:
            truth.append({"id": eid, "src": a, "dst": b, "type": et})
        return eid

    # planted attack paths
    for _ in range(p.n_paths):
        cur = rng.choice(sources)
        path_len = rng.randint(2, 5)
        visited = {cur}
        for step in range(path_len):
            opts = [m for m in mids if m not in visited and TYPE_MAP.get((types[cur], types[m]))]
            if step == path_len - 1 or not opts:
                tg = rng.choice(targets)
                if TYPE_MAP.get((types[cur], "Asset")):
                    add_edge(cur, tg, force_true=True)
                break
            nxt = rng.choice(opts)
            add_edge(cur, nxt, force_true=True)
            visited.add(nxt)
            cur = nxt
    # random extra structure
    for _ in range(int(p.branching * p.n_mid)):
        add_edge(rng.choice(sources + mids), rng.choice(mids + targets))
    # latent template edges (visible as LATENT), true in W* with the declared prior
    pairs = [(a, b) for a in sources + mids for b in mids + targets
             if TYPE_MAP.get((types[a], types[b])) in LATENT_TEMPLATE and (a, b) not in edges_seen and a != b
             and b not in sources]
    rng.shuffle(pairs)
    n_lat = int(len(pairs) * p.latent_density)
    for a, b in pairs[:n_lat]:
        et = TYPE_MAP[(types[a], types[b])]
        tpl = LATENT_TEMPLATE[et]
        edges_seen.add((a, b))
        events.append({"op": "latent", "at": t_assert, "template_id": tpl, "type": et, "src": a, "dst": b,
                       "verify_cost": VERIFY_COST[tpl]})
        if rng.random() < p.p_latent_true:
            truth.append({"id": f"lat:{tpl}:{a}->{b}", "src": a, "dst": b, "type": et})
    # hidden, unmodeled true edges (outside any certificate's scope by declared assumption)
    for i, (a, b) in enumerate(pairs[n_lat:n_lat + p.hidden_unmodeled]):
        truth.append({"id": f"hidden:{i}:{a}->{b}", "src": a, "dst": b, "type": TYPE_MAP[(types[a], types[b])],
                      "unmodeled": "true"})
    # flows between non-source nodes connected by true signed edges
    confirmed_adj: dict[str, list[str]] = {}
    for ev in events:
        if (ev["op"] == "assert" and ev["fact_id"] not in revoked and len(ev["sources"]) == 1
                and ev["sources"][0] == f"s:{ev['fact_id']}"):
            confirmed_adj.setdefault(ev["src"], []).append(ev["dst"])
    flow_pairs = [(u, v) for u, vs in confirmed_adj.items() for v in vs if u not in sources]
    rng.shuffle(flow_pairs)
    flows = []
    for i, (u, v) in enumerate(flow_pairs[:p.n_hard + p.n_soft]):
        hard = i < p.n_hard
        flows.append({"flow_id": f"flow:{i}", "u": u, "v": v, "weight": 100 if hard else rng.randint(1, 5),
                      "kind": "hard" if hard else "soft"})
    # decoy: an attacker-planted edge pointing at a high-fan-in node
    decoy_target = None
    if p.decoy:
        svc = [m for m in mids if types[m] == "Service"]
        if svc:
            decoy_target = rng.choice(svc)
            tg = rng.choice(targets)
            if (decoy_target, tg) not in edges_seen:
                edges_seen.add((decoy_target, tg))
                eid = f"g:{decoy_target}->{tg}:decoy"
                sid = source(f"s:{eid}", "none", f"root:{eid}", "low", written_on="host:src-ws")
                events.append({"op": "assert", "at": iso(T_inc + timedelta(hours=1)), "fact_id": eid,
                               "type": "CAN_ACCESS", "src": decoy_target, "dst": tg, "valid_from": iso(T_inc),
                               "valid_open_ended": True, "sources": [sid], "cost_remove": 2})
                decoys.append(eid)
            if (sources[1], decoy_target) not in edges_seen and TYPE_MAP.get(("Host", "Service")):
                add_edge(sources[1], decoy_target, force_true=True)
    scenario = {
        "scenario_id": f"gen_{seed}", "title": f"Generated instance {seed}", "synthetic": True,
        "generated": True,
        "description": "SYNTHETIC generated benchmark instance", "clock": {"now": iso(now)},
        "incident": {"incident_id": f"INC-GEN-{seed}", "title": "generated", "severity": "medium",
                     "T_incident": iso(T_inc), "alerted_identity": "id:src-user", "compromised_set": sources,
                     "targets": targets, "summary": "generated"},
        "nodes": nodes, "sources": src_recs, "events": events, "flows": flows, "memory_seed": [],
        "contradictions": [], "incident_evidence": [],
    }
    return Instance(seed, p, scenario, truth, decoys, decoy_target)
