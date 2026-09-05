---
name: review-change-stack
description: Review a dependent branch or pull-request stack in dependency order with one receipt per change and a stack-level verdict.
---

# Review a change stack

Read [the execution contract](references/contract.json) before starting. Validate the final receipt with its parameterized `verification.argv`, replacing `{python}`, `{skill_dir}`, and `{receipt}` with concrete local values.

Resolve the actual base and dependency order first. For each change, inspect
its diff against the immediate parent, run the relevant proof, and record
correctness, security, migration, test, and rollback findings.

Do not let a green child hide a broken parent. Mark each item `PASS`, `REVISE`,
or `BLOCKED`, then check cross-change contracts and produce one stack verdict.
If an optional stack CLI is unavailable, use Git ancestry and label provider
metadata `UNVERIFIED` instead of inventing it.
