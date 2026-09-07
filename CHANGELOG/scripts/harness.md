# Harness changelog

## 2026-09-04 — Add fail-closed preflight and continuity checks

- Commit: uncommitted local change; publication is blocked by the current
  reachable-history privacy gate until a clean fresh history or separately
  authorized rewrite is reviewed.
- User outcome: reviewers can distinguish a proven change from a missing gate,
  validate loop or graph routing, and observe each preflight layer reject a
  deliberate violation.
- Source: repository invariants and the bounded planner-worker-judge contract.
- Files: `scripts/agent_preflight.py`, `scripts/prove_preflight_mutations.py`,
  `scripts/validate_agent_state.py`, `scripts/self_review_hook.py`, and harness
  fixtures.
- Verification: deterministic receipts, mutation scenarios, bounded input,
  malformed-state, concurrent-event, burst, sustained-use, and copied-project
  integration tests.
- Repairs: reject sensitive or outside preflight inputs, reject config and
  checkpoint symlinks, cap checkpoint reads after open, and serialize safe
  state-directory creation under concurrent host stops.
- Repairs: use each host's current Stop output contract; Claude Code and Codex
  receive top-level `decision` / `reason`, while Cursor receives
  `followup_message`.
- Repairs: retain the currently updating session during bounded state eviction
  so pressure cannot reset its five-nudge continuity window.
- Repairs: use one reparse-aware path guard for skill copies, setup diagnosis,
  continuity state, and publication reads; exclude generated Claude worktrees
  and private local instructions from continuity digests.
- Repairs: key Cursor stop state by its real `conversation_id`, resolve Claude
  generated-worktree events to the active Git root, and reject one-ref branch
  stacks that contain no relationship to prove.
- Repairs: require every host-switch event to name two different bounded hosts
  and one safe repository-relative `HANDOFF.md`; empty or extra-field events no
  longer pass as an audit trail.
- Repairs: bind every host-switch event to the current handoff bytes with a
  64-hex SHA-256, require an explicit project root, and reject missing, stale,
  oversized, or link-like handoff files through the shared bounded reader.
- Repairs: share one Git safety environment across preflight, history, and
  branch-stack checks; reject effective legacy grafts, ignore replacement refs,
  and place `--` before user-supplied branch names.
- Repairs: raise the still-bounded selftest ceiling from 30 to 60 seconds after
  the expanded real-Git mutation suite observably exceeded the old budget on
  Windows; a timeout remains an honest preflight failure.
- Caveats: self-review output is a prompt for inspection, not independent proof.

## 2026-09-07 — Plan additive setup for an existing Git project

- User outcome: review a finite file plan and add selected missing kit files
  while retaining local instructions, Git state and competing writers' files.
- Ownership: one placement map and plan/apply protocol in `scripts/setup_project.py`;
  fresh-project scenario tests exercise that same CLI.
- Verification: dirty and unborn Git consumers, source drift, canonical skill
  completeness, concurrent creation, bounded unsafe paths, and partial progress
  scenarios. The receipt reports unresolved setup without a readiness claim.
- Limits: no automatic merges, overwrite, rollback, host activation or global
  configuration; local stable-parent filesystem assumptions are documented.
