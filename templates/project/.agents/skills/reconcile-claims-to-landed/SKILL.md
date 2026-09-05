---
name: reconcile-claims-to-landed
description: Reconcile claimed work with repository, review, deployment, and artifact state without trusting status prose.
---

# Reconcile claims to landed state

Read [the execution contract](references/contract.json) before starting. Validate the final receipt with its parameterized `verification.argv`, replacing `{python}`, `{skill_dir}`, and `{receipt}` with concrete local values.

List each claimed outcome, then observe the corresponding branch, commit,
review, deployment, artifact, or live content signal. Classify it `PLANNED`,
`IMPLEMENTED`, or `PROVEN`; never promote from a report alone.

Return missing receipts, stale claims, conflicting owners, and the single next
action for each gap. Keep the sweep read-only unless the request explicitly
includes repairs. A successful push or CI log does not prove live content.
