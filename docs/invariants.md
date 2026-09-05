# Portable agent invariants

The canonical, copy-to-project contract is
[`templates/project/AGENT_INVARIANTS.md`](../templates/project/AGENT_INVARIANTS.md).
It contains all 22 reusable rules and is copied beside `AGENTS.md` by the
materialization sequence. Project-specific policy may tighten that contract,
but should not silently weaken it.

Keeping the complete list in the project template prevents the kit's prose and
the target's actual instructions from drifting into two sources of truth. The
preflight, permissions, hooks, CI, and server-side authorization enforce the
subset that can be deterministic.
