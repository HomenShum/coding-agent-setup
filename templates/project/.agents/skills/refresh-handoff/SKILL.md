---
name: refresh-handoff
description: Refresh a bounded cross-host handoff before yielding, compacting, or switching agents so the next context can resume safely.
---

# Refresh handoff

Read [the execution contract](references/contract.json) before starting. Validate the final receipt with its parameterized `verification.argv`, replacing `{python}`, `{skill_dir}`, and `{receipt}` with concrete local values.

Read the current request, working tree, existing handoff, and latest proof.
Update only the root handoff fields: owner role, user outcome, current state,
host, tree digest, named proof, last result, changed files, unverified claims,
and one next action. Before a host switch, copy those exact bytes to a new
immutable `handoffs/<sequence>/HANDOFF.md`, hash the snapshot, and append that
path and digest to the state event. Never reuse or edit an earlier event path.

Never paste prompts, transcripts, credentials, private paths, or a full diff.
Verify the digest and every referenced local file. Keep at most the active
state's sixty-four snapshots. A stale, reused, or missing handoff is `NO_GATE`
when continuity is required.
