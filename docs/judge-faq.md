# Judge FAQ — short, honest answers

**In one sentence?**
Disabling the alerted account feels safe but often isn't. GHOSTTRACE finds the path that survives, prices how much
certainty you can buy, and hands you a certificate anyone can check.

**What is actually new here?**
None of the building blocks are new: attack graphs, min-cut planning, bitemporal data, CEGAR, truth maintenance,
proof checking. The combination is what's new:
1. **Price of Certainty.** We treat unverified edges as a robustness budget (reopening distance `d`). Then we show
   the cost of each extra level of assurance (3 → 10 → 14 in the demo), instead of a single "fix".
2. **Assumption-explicit certificates.** Each plan is bound to a snapshot hash and lists its assumptions and the
   evidence records that would break it if false. A separate stdlib-only verifier re-derives it.
3. **Attacker-aware evidence rules wired into planning.** Logs from compromised hosts can't remove attack surface
   (R2), and planted evidence can't silently drive a disruptive action (R3, R4).
4. **"Knowable then vs known now"** for attack paths and ownership.

**Where is the AI?**
In three places, and it is never trusted with a verdict:
- the model advisor *proposes* plans, and each one is simulated and certified; the demo shows rejected and accepted
  proposals with the reason;
- the red team *nominates* hidden edges, which are accepted only if a graph precondition holds;
- the agents *summarise and explain*.

Run it with `GT_LLM_PROVIDER=anthropic` (Claude Opus 5.5). The design point is that an LLM is useful for proposing
under uncertainty and dangerous for deciding. The graph and the verifier decide.

**Why FalkorDB?**
It sits in the live path: bitemporal as-of queries, bounded multi-hop path enumeration with a counterfactual
overlay, template preconditions, ownership and dependency traversal, memory retrieval by graph relevance, and durable
task leases via atomic compare-and-set. See `docs/why-falkordb.md` for the actual queries. Along the way we found and
documented two FalkorDB 4.22.0 bugs with workarounds: a multi-edge index planner issue, and an AOF crash-loop.

**Does it work on real data?**
Not demonstrated. All evaluation is on synthetic graphs with synthetic priors, and we say so everywhere. The
ingestion format is documented, so a real environment would need an exporter into it.

**Aren't your baselines strawmen?**
They're simple, and we built the generator too. That's a real limitation. What does not depend on the baselines:
- 0 soundness violations over 900 certificates;
- the verifier killing every non-equivalent mutation;
- the solver matching brute force;
- calibration (d=1 plans reopen ≈30% of the time under a 0.3 prior, as they should).

**Why should I believe the "optimal" claims?**
They are scoped to the declared candidate set, checked against brute force in tests, and re-checked by the
independent verifier for small instances.

**What happens if a latent edge turns out to be true?**
The k=0 plan reopens, which the certificate tells you up front: its witness path and its "verify these edges first"
list. A k≥1 plan survives any single wrong assumption. That trade-off is the curve.

**Is it production ready?**
The production profile has:
- OIDC with roles and per-workspace access;
- HTTPS;
- a password-protected, non-exposed database with persistence and recovery;
- worker replicas, shared rate limits, and approvals with four-eyes and verifier re-check;
- CI with a soundness gate.

It has been verified locally with a test signing key, not against a specific commercial IdP. It never executes
containment actions; approval only records a human decision.

**What does it not solve?**
Paths through facts nobody recorded and no template suggests. Correctness of the declared threat model, which drives
the "attacker-influenceable" labels. Real business costs, since ours are seeded integers.
