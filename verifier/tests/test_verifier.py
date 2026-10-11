"""Independent verifier: accepts valid certificates, rejects every mutation (kill rate reported)."""

from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from verifier.core import check

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def cert_and_export(tmp_path_factory):
    sys.path.insert(0, str(ROOT / "backend"))
    from app.ingestion.scenario import load, read_scenario, world_from
    from app.model import TrustPolicy
    from app.planner import engine

    led, meta = load(read_scenario("ghost_credential_a"), "unit")
    w = world_from(led, meta)
    now = meta.now
    out = {}
    for k in (0, 1):
        edges, cands, res = engine.plan(w, now, now, TrustPolicy.CONSERVATIVE, k)
        cert, lines = engine.certify_plan(w, now, now, TrustPolicy.CONSERVATIVE, edges, cands, res, k)
        p = tmp_path_factory.mktemp("v") / "edges.jsonl"
        p.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
        out[k] = (cert, str(p), lines)
    return out


def _m(f):
    def apply(c, lines):
        c = copy.deepcopy(c)
        f(c, lines)
        return c
    return apply


def _drop_removed(c, _):
    a = next(a for a in c["actions"] if a["removes"])
    a["removes"] = a["removes"][1:]


def _swap_target(c, lines):
    a = c["actions"][0]
    other = next(x for x in lines if x["kind"] == "action_cost" and x["action_id"] != a["id"])
    a["type"], a["target_id"], a["id"] = other["action_type"], other["target_id"], other["action_id"]
    a["cost"] = other["cost"]


def _swap_action_id(c, _):
    c["actions"][0]["id"] = "disable_identity:id:dev-alice"


def _flip_flow(c, _):
    c["flows"][0]["preserved"] = not c["flows"][0]["preserved"]


def _flow_kind(c, _):
    f = next(f for f in c["flows"] if f["kind"] == "soft")
    f["kind"] = "hard"


def _alter_total(c, _):
    c["cost"]["total"] -= 1


def _alter_action_cost(c, _):
    c["actions"][0]["cost"] -= 1
    c["cost"]["operational"] -= 1
    c["cost"]["total"] -= 1


def _change_T(c, _):
    c["world_time_T"] -= 86_400_000


def _change_tau(c, _):
    c["knowledge_time_tau"] -= 1


def _change_hash(c, _):
    c["snapshot_hash"] = "sha256:" + "0" * 64


def _inflate_k(c, _):
    c["robustness"]["k_certified"] += 1


def _hide_reopening(c, _):
    c["robustness"]["min_reopening_latent_edges"] = None


def _drop_action(c, _):
    c["actions"] = c["actions"][1:]


def _policy(c, _):
    c["trust_policy"] = "trust_filtered"


def _schema(c, _):
    c["schema_version"] = "2"


def _executed(c, _):
    c["mode"] = "executed"


def _fake_optimal_total(c, _):
    c["cost"]["total"] += 1
    c["cost"]["soft_flow_penalty"] += 1


def _sources(c, _):
    c["sources"] = c["sources"][:1]


def _bad_witness(c, _):
    c["robustness"]["witness_paths"] = [c["robustness"]["witness_paths"][0][1:]]


MUTATIONS = {
    "drop_removed_edge": _drop_removed, "swap_action_target": _swap_target, "swap_action_id": _swap_action_id,
    "flip_flow": _flip_flow, "flow_kind": _flow_kind, "alter_total_cost": _alter_total,
    "alter_action_cost": _alter_action_cost, "change_T": _change_T, "change_tau": _change_tau,
    "change_hash": _change_hash, "inflate_k": _inflate_k, "hide_reopening": _hide_reopening,
    "drop_action": _drop_action, "change_policy": _policy, "unknown_schema": _schema, "mode_executed": _executed,
    "fake_cost_penalty": _fake_optimal_total, "change_sources": _sources, "bad_witness": _bad_witness,
}


def test_valid_certificates_accepted(cert_and_export):
    for _k, (cert, path, _) in cert_and_export.items():
        assert check(cert, path) == []


def test_every_mutation_rejected(cert_and_export, record_property):
    cert, path, lines = cert_and_export[0]
    killed, survivors = 0, []
    for name, fn in MUTATIONS.items():
        mutated = _m(fn)(cert, lines)
        if check(mutated, path):
            killed += 1
        else:
            survivors.append(name)
    rate = killed / len(MUTATIONS)
    record_property("mutation_kill_rate", rate)
    (ROOT / ".artifacts").mkdir(exist_ok=True)
    (ROOT / ".artifacts" / "mutation_kill_rate.json").write_text(json.dumps(
        {"killed": killed, "total": len(MUTATIONS), "rate": rate, "survivors": survivors}))
    assert survivors == [], survivors


def test_tampered_export_rejected(cert_and_export, tmp_path):
    cert, _, lines = cert_and_export[0]
    tampered = copy.deepcopy(lines)
    e = next(x for x in tampered if x["kind"] == "edge" and x["cls"] == "LATENT")
    e["cls"] = "OBSERVED"
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in tampered))
    assert check(cert, str(p))


def test_malformed_inputs(cert_and_export, tmp_path):
    cert, path, _ = cert_and_export[0]
    assert check({}, path)
    c = copy.deepcopy(cert)
    del c["actions"]
    assert check(c, path)
    p = tmp_path / "bad.jsonl"
    p.write_text('{"kind": "edge"}\n')
    assert check(cert, str(p))


def test_cli_exit_codes(cert_and_export, tmp_path):
    cert, path, _ = cert_and_export[0]
    cp = tmp_path / "c.json"
    cp.write_text(json.dumps(cert))
    ok = subprocess.run([sys.executable, "-m", "verifier", "check", str(cp), path], cwd=ROOT, capture_output=True,
                        text=True, check=False)
    assert ok.returncode == 0 and "ACCEPTED" in ok.stdout
    bad = copy.deepcopy(cert)
    bad["cost"]["total"] += 7
    cp.write_text(json.dumps(bad))
    r = subprocess.run([sys.executable, "-m", "verifier", "check", str(cp), path], cwd=ROOT, capture_output=True,
                       text=True, check=False)
    assert r.returncode == 1 and "REJECTED" in r.stdout


def test_verifier_is_stdlib_only_and_independent():
    allowed = set(sys.stdlib_module_names) | {"verifier"}
    for f in (ROOT / "verifier").glob("*.py"):
        tree = ast.parse(f.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            for n in names:
                assert n in allowed and n != "app", f"{f.name} imports {n}"
    lines = sum(len(f.read_text().splitlines()) for f in (ROOT / "verifier").glob("*.py"))
    assert lines < 450, "keep the trusted base small enough to read in one sitting"
