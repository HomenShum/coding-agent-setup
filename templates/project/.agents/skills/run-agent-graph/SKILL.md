---
name: run-agent-graph
description: Run a typed LOOP or GRAPH workflow when routing, worker isolation, and judge-only delivery need an auditable state receipt.
---

# Run an agent graph

Read [the execution contract](references/contract.json) before starting. Validate the final receipt with its parameterized `verification.argv`, replacing `{python}`, `{skill_dir}`, and `{receipt}` with concrete local values.

Default to `LOOP`. Promote to `GRAPH` only when `why_graph` records at least
two current reasons: distinct specialties, fan-out/fan-in, different toolsets,
auditable routing, isolated failure, or a dedicated reviewer.

- Initialize a versioned state with caps no greater than twelve transitions,
  five workers, and sixty-four receipts.
- Enforce role write scopes. Workers append receipts only; the judge writes the
  disposition; the human owns outcome and authority.
- In GRAPH mode, forbid planner or gate delivery to the human. Only judge
  `PASS` may deliver; otherwise use `REVISE`, `REPLAN`, `HITL`, or `BLOCKED`.
- Append host switches as exact `type`, `from`, `to`, repository-relative
  `handoff`, and `handoff_sha256` events. Each event must use a distinct,
  immutable, non-link `handoffs/<sequence>/HANDOFF.md` snapshot inside the
  project root; the digest binds that snapshot's current bytes.
- Run the state validator with an explicit `--project-root` before treating an
  eventful graph as complete.

Do not use a graph to make a simple loop look sophisticated.
