# The hard problem: open-world containment

## Statement

The input has four parts:

- (a) a graph of identities, credentials, permissions, workloads, dependencies and deployments that is
  **known to be incomplete**;
- (b) facts that change over time and are **learned later than they became true**;
- (c) evidence of **mixed trustworthiness**, some of it possibly planted or suppressed by the attacker;
- (d) business-critical flows that **must keep working**.

The task is to produce a response plan with a machine-checkable certificate, and to keep that certificate
correct as evidence arrives. The certificate states four things: what the plan guarantees, under which
assumptions, how cheaply those assumptions could be false, and what the plan costs.

**We do not claim to solve this problem.** Minimum-cost interdiction of attack paths is NP-hard in general.
No one can prove that an unmodeled path is absent. GHOSTTRACE pushes a measurable frontier and states where
it stops.

## Model (as implemented)

| Concept | Definition | Code |
|---|---|---|
| Fact | Edge version with `[valid_from, valid_to)` and `[tx_from, tx_to)` in UTC epoch ms; half-open; never deleted | `app/model.py`, `app/ingestion/ledger.py` |
| `Active(f,T,τ)` | `tx_from ≤ τ < tx_to ∧ valid_from ≤ T < valid_to` | `app/temporal/predicate.py` |
| `validity_unknown` | missing `valid_from`, or missing `valid_to` without an asserted open end → uncertainty | same |
| Epistemic class | OBSERVED (R1) · DERIVED (rule `policy_expansion`) · LATENT (allowlisted template, or weak/false-flag evidence) | `app/reasoning/{evidence,snapshot,latent}.py` |
| Path class | CONFIRMED · CONDITIONAL(k) · TEMPORALLY_UNCERTAIN | `app/reasoning/paths.py` |
| κ(a) | cut set of an action, computed by fixed rules over the snapshot | `app/reasoning/kappa.py` |
| Objective | `J(A) = Σ c_op(a) + Σ_{soft f broken} w_f` subject to: hard flows preserved, `d(A) > k` | `app/planner/cegar.py` |
| Reopening distance | `d(A)` = min number of non-confirmed edges on any surviving S→T path (0-1 BFS) | `app/reasoning/paths.py` |
| k-robust | `d(A) > k` | |
| Price of Certainty | `J*(k)` for k = 0..K with plans | `app/planner/engine.py::pareto` |

### Evidence calculus

- **R1** — An edge is OBSERVED iff it has ≥1 integrity-verified source that is not attacker-influenceable, or
  ≥2 *independent* sources. Independent means distinct `root_id` and no provenance ancestry between them.
  Otherwise the edge is LATENT and `weakly_supported`.
- **R2** — A surface-removing claim is honoured only if R1 holds using non-attacker-influenceable sources.
  Otherwise the edge stays and is flagged `disputed`.
- **R3** — If every source of a surface-expanding claim is attacker-influenceable, the edge is LATENT and
  `possible_false_flag`. Actions needed only because of such edges are flagged `requires_human_scrutiny`.
- **R4** — Every plan is recomputed under `trust_filtered` (attacker-influenceable evidence excluded) and the
  differences are reported.
- **R5** — Load-bearing evidence is the set of minimal source-record sets (size ≤ 2) whose falsification
  invalidates the certificate. Falsification removes the record's support and reverts any validity closure
  it justified.

### Solver

CEGAR: an exact branch-and-bound master over a hitting-set formulation, plus an exhaustive 0-1 BFS
subproblem. Each surviving path with ≤ k non-confirmed edges becomes a new constraint. A broken hard flow
produces a nogood, minimised by deletion. Flow breakage is monotone in the action set.

`proven_optimal` is reported only when the master was solved exactly over the declared candidate set and the
subproblem found no surviving path. If a budget is exhausted, a greedy repair is labelled `bounded` (with the
gap) or `heuristic`. A brute-force enumerator is used only in tests and the verifier.

## Assumptions every certificate carries

1. The modeled graph is the attack surface. Paths through facts that no allowlisted template instantiates are
   out of scope.
2. Epistemic classes follow R1–R3 under the stated trust policy. The verifier takes classes from the
   hash-bound export as given.
3. Facts are evaluated at (T, τ).
4. The latent/uncertain edges on the witness are assumed absent for the confirmed-containment claim.
5. Disputed removals are treated as **not** removed.

## Known limits

- **Model incompleteness.** No method can see an edge that no data and no template suggests. The eval
  measures this explicitly: "residual exposure including unmodeled edges" is non-zero for every method.
- **Candidate set.** Optimality holds only within the deterministic candidate set. Candidates are capped at 64.
- **Synthetic validation only.** All benchmarks come from our own generator with declared priors. Calibration
  numbers are valid only under that prior.
- **Trust labels are inputs.** `attacker_influenceable` is derived from the scenario's declared compromised
  set (logs written on those hosts). A wrong threat model gives wrong labels.
- **Load-bearing analysis is bounded** (sets of size ≤ 2, ≤ 40 records).
- **Incremental replanning** reuses re-validated constraints. Measured speedups are modest (≈1.1–1.6× (noisy timings, n = 5 per size); see
  `evals/report.md`).
- **Costs are seeded integers** with a documented basis, not measured business impact.
