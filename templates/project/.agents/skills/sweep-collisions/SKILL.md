---
name: sweep-collisions
description: Check repository history, open work, automation, and available work trackers for overlapping changes before implementation.
---

# Sweep collisions

Read [the execution contract](references/contract.json) before starting. Validate the final receipt with its parameterized `verification.argv`, replacing `{python}`, `{skill_dir}`, and `{receipt}` with concrete local values.

Before editing a contested seam, search the repository, recent branches or
reviews available in scope, and deployment or scheduled automation that can
write the same surface.

Return a receipt with the queried sources, exact search terms, time boundary,
overlapping owners, conflicting contracts, and `CLEAR`, `COORDINATE`, or
`BLOCKED`. Label unavailable sources `UNVERIFIED`; absence of access is not a
clear result.

Use connectors only when already authorized. Never broaden a repository task
into messages, tickets, or remote changes without explicit authority.
