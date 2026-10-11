# Evaluation

Numbers live only in the generated [evals/report.md](../evals/report.md) and `evals/results.json`, both produced
by `evals/run_evals.py`. This page documents the method.

## Benchmark generator (`evals/generator/generator.py`)

The generator is seeded and deterministic. Its parameters are: mid-node count, branching, planted attack
paths, latent-edge density, the prior `p_latent_true` for hidden-true latent edges, decoy/false-flag rate
(`ai_frac`), weak-evidence rate, temporal churn, hard/soft flows and hidden unmodeled edges. Each instance
emits two artefacts:

- a **visible world**: a scenario in the same JSON schema as `data/scenarios`, ingested through the normal
  ledger;
- a **ground-truth world W\***: edges truly present at planning time. W\* contains visible true edges and
  latent edges drawn true from the prior. Attacker-written "removal" claims remain true in W\*. W\* also holds
  a few **unmodeled** edges that no system can see. Attacker-planted decoy edges are **false** in W\*.

Families: `small` (6 mid nodes; brute-force optimum available), `default` (10), and `adversarial` (10, more
decoys and weak evidence). The scaling study uses 10–160 mid nodes.

## Methods

| Id | Method |
|---|---|
| B0 | Disable the alerted account only |
| B1 | Greedy by degree centrality on a time- and trust-blind static graph (removal claims believed); ignores flows |
| B2 | Static minimum-cost cut (same naive graph) ignoring time, trust and must-keep flows |
| B3 | Mock "LLM-only" recommender: disable the alerted account and isolate whatever the alerts implicate; no graph verification |
| GT_k0/k1/k2 | GHOSTTRACE CEGAR planner at robustness levels 0, 1, 2 (conservative_defense) |

## Metrics (all computed on W\*, which the system never sees)

- **Residual exposure (modeled W\*)** — fraction of instances where a source→target path survives in W\*
  (excluding unmodeled edges) after applying the plan's action rules to W\*.
- **Residual exposure (incl. unmodeled)** — the same, but including edges no method could see. Certificates
  exclude these by an explicit assumption.
- **Certificate soundness violations** — the certificate claims "contained", yet a path made only of edges the
  system classified CONFIRMED exists in W\* after the plan. **Must be 0. The script exits 1 otherwise (CI gate).**
- **Hard flow broken** — fraction of plans that break at least one must-keep hard flow in W\*.
- **Mean true J** — operational cost plus soft-flow penalties evaluated in W\*.
- **Disruption regret** (small family) — `J(plan) − J(optimum)` against the brute-force k=0 optimum, over
  plans that contain the visible model. For GT_k1/k2 this is the Price of Certainty, not an error.
- **Evidence-attack success** — over instances with active decoys: the plan contains an attacker-induced
  action without a scrutiny flag. An attacker-induced action is one whose cut edges lie on S→T paths only where
  those paths rely on `possible_false_flag` evidence.
- **Robustness calibration** — for GHOSTTRACE plans bucketed by reopening distance d: the fraction reopened in
  modeled W\*. Valid only under the generator's synthetic prior.
- **Temporal/R2 correctness** — trusted pre-planning revocations must be absent from the snapshot, and
  attacker-written removal claims must leave the edge present and `disputed`.
- **Citation resolution** — evidence ids cited by planned actions that resolve to stored source records.
- **Verifier** — acceptance of every GHOSTTRACE certificate, plus mutation testing on a sample. Mutants
  identical to the original (equivalent) are counted separately, not as kills.
- **Scaling** — median and p95 with sample counts: solver time, cold vs warm replanning after new evidence
  (asserted equal results), FalkorDB snapshot query and Cypher path enumeration latency.
- **Cross-workspace isolation** — covered by the test suite (graph, memory, API, tools), not by the eval script.

Rates carry Wilson 95% intervals. All failures are listed in the report, with no cherry-picking.

## Reproduce

```bash
docker compose up -d falkordb
cd backend && uv run python ../evals/run_evals.py --n 100 --falkordb   # ~2 min on the dev laptop
```

`--quick` runs 20 instances per family. Seeds: small 0–99, default 1000–1099, adversarial 2000–2099, scaling
10000–10004.
