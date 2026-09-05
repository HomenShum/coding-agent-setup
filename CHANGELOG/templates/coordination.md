# Coordination template changelog

## 2026-09-04 — Add bounded handoff and agent-routing templates

- Commit: uncommitted local change; publication is blocked by the current
  reachable-history privacy gate until a clean fresh history or separately
  authorized rewrite is reviewed.
- User outcome: a planner can delegate independent evidence lanes, require a
  separate judge, carry current state between hosts, and reconcile claims to
  landed artifacts without treating reports as proof.
- Source: repository planner-worker-judge, continuity, and proof contracts.
- Files: host-native agent templates, `templates/project/HANDOFF.md`,
  `ARTIFACTS.md`, `DECISIONS.md`, `COMMUNICATION.md`, `context-exchange/`, and
  agent-state fixtures.
- Verification: native format parsing, legal-route validation, forbidden-route
  rejection, transition caps, and digest-bound handoff scenarios.
- Caveats: parallel execution is appropriate only when lanes and write scopes
  are genuinely independent.
