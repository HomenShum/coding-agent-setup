---
name: append-sourced-decision
description: Append a source-backed decision to a durable ledger without rewriting prior decisions or hiding corrections.
---

# Append a sourced decision

Read [the execution contract](references/contract.json) before starting. Validate the final receipt with its parameterized `verification.argv`, replacing `{python}`, `{skill_dir}`, and `{receipt}` with concrete local values.

Read the ledger format and the decision being corrected. Append one record
containing a stable ID, date, human owner role, decision, evidence links,
status, and `SUPERSEDES` ID when applicable.

Do not rewrite or delete older rows. Distinguish observed evidence from
assumption, and keep credentials, private paths, and session transcripts out.
Re-read the appended row and verify every local link resolves.
