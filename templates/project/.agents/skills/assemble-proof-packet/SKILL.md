---
name: assemble-proof-packet
description: Assemble a reviewable handoff packet from raw diff, tests, artifacts, risks, and replay commands after implementation.
---

# Assemble a proof packet

Read [the execution contract](references/contract.json) before starting. Validate the final receipt with its parameterized `verification.argv`, replacing `{python}`, `{skill_dir}`, and `{receipt}` with concrete local values.

Start from the original request. Include the user outcome, exact scope, raw
diff summary, numbered claims, replay commands and observed results, artifact
links, residual risks, rollback, and current handoff digest.

Do not include credentials, transcripts, private paths, or unverifiable
success language. Mark skipped or inaccessible checks explicitly. Re-run local
links and the named proof before handing the packet to a fresh judge.
