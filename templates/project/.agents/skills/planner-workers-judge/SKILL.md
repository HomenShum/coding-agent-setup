---
name: planner-workers-judge
description: Orchestrate bounded evidence workers and a fresh adversarial judge when independent review materially improves a complex task.
---

# Planner, workers, judge

Read [the execution contract](references/contract.json) before starting. Validate the final receipt with its parameterized `verification.argv`, replacing `{python}`, `{skill_dir}`, and `{receipt}` with concrete local values.

Use this for three or more independent evidence lenses or a consequential
completion claim. Keep ordinary sequential work in one loop.

1. Write numbered, checkable claims `C1..Cn` with exact paths or observations.
2. Give each worker one lens, a read-only policy, a file/output bound, and the
   same instruction to label facts `MEASURED`, `INFERRED`, or `UNVERIFIED`.
3. Start independent workers together when the host supports it; cap them at
   five. Wait for every receipt before judging.
4. Give a fresh judge the claims, raw diff, receipts, and replay commands. Ask
   it to refute, not summarize.
5. Record `CONFIRMED`, `REFUTED`, or `WEAKENED` per claim, repair only in-scope
   failures, rerun the exact proof, and stop after three cycles on one cause.

Workers never deliver to the user and never inherit mutation authority merely
because the planner has it. Use the project's host-native agent adapters; do
not assume that one vendor's agent format is portable to another host.
