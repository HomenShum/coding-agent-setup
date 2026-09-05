---
name: verify-coverage-claims
description: Verify cross-artifact coverage claims by tracing every claimed item to source, implementation, test, and proof receipts.
---

# Verify coverage claims

Read [the execution contract](references/contract.json) before starting. Validate the final receipt with its parameterized `verification.argv`, replacing `{python}`, `{skill_dir}`, and `{receipt}` with concrete local values.

Turn the coverage statement into a finite item list. For each item locate the
governing source, implementation, realistic test, and observed proof. Mark
each link `MEASURED`, `INFERRED`, or `UNVERIFIED`.

Report missing items, duplicate counting, stale artifacts, and scope changes.
Do not infer full coverage from a percentage, a green suite, or sampled rows.
The denominator and exclusions must be explicit and replayable.
