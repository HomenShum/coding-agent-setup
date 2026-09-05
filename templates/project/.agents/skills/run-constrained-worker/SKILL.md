---
name: run-constrained-worker
description: Run one worker through a bounded harness with explicit inputs, write scope, timeout, output cap, and receipt schema.
---

# Run a constrained worker

Read [the execution contract](references/contract.json) before starting. Validate the final receipt with its parameterized `verification.argv`, replacing `{python}`, `{skill_dir}`, and `{receipt}` with concrete local values.

Declare the worker's one job, allowed inputs, exact write scope, timeout,
maximum output, retry budget, and receipt schema before starting it. Default to
read-only and no recursive delegation.

Capture the returned status and raw evidence. A timeout, invalid receipt, or
unavailable tool is a failure or `UNVERIFIED`, never a successful empty result.
Retry only when the mechanism is understood and the same authority still
applies. Isolate a failed worker so other receipts remain valid.
