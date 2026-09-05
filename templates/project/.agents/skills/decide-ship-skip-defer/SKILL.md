---
name: decide-ship-skip-defer
description: Decide whether a proposed feature should ship, be skipped, or be deferred using a concrete user outcome and proof contract.
---

# Decide ship, skip, or defer

Read [the execution contract](references/contract.json) before starting. Validate the final receipt with its parameterized `verification.argv`, replacing `{python}`, `{skill_dir}`, and `{receipt}` with concrete local values.

Name one user, one job, the smallest API or interaction contract, and one
observable success metric. Compare the proposal with existing capability and
require an observed failure before replacing anything.

Return exactly one recommendation:

- `SHIP`: the user outcome, scope, proof, owner, and rollback are concrete.
- `SKIP`: existing capability already satisfies the outcome or value is below cost.
- `DEFER`: a named dependency or evidence gap prevents an honest decision.

Do not turn `DEFER` into an unbounded research backlog. State the single
observation that would reopen the decision.
