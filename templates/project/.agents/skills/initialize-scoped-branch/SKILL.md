---
name: initialize-scoped-branch
description: Initialize a narrowly scoped feature branch after checking repository state, ownership, and the exact starting revision.
---

# Initialize a scoped branch

Read [the execution contract](references/contract.json) before starting. Validate the final receipt with its parameterized `verification.argv`, replacing `{python}`, `{skill_dir}`, and `{receipt}` with concrete local values.

Use only when the user requested branch work or the repository workflow
requires it.

1. Inspect status, current branch, remotes, and the intended base without
   modifying files.
2. Stop if unrelated changes overlap the requested scope; preserve them.
3. Record the user outcome, named proof, base revision, and owned paths.
4. Create one branch using the repository naming convention. Never reset,
   delete, or switch away from uncommitted work to force a clean state.
5. Verify the new branch points at the intended base and refresh `HANDOFF.md`.

Branch creation does not authorize commit, push, pull request, or deployment.
