---
name: example-proof
description: Verify a completed change against raw artifacts and one named user outcome. Use after substantive implementation or when another agent claims completion.
---

# Example proof skill

Read [the execution contract](references/contract.json) before starting. Validate the final receipt with its parameterized `verification.argv`, replacing `{python}`, `{skill_dir}`, and `{receipt}` with concrete local values.

## Inputs

- the user's requested outcome;
- the exact files or remote surface in scope;
- the claimed verification commands;
- one named observable proof.

## Workflow

1. Restate the claim in falsifiable terms.
2. Inspect the raw diff or artifact rather than relying on a summary.
3. Re-run the narrow verification from a clean state.
4. Exercise one realistic failure or degraded path.
5. Compare the observation with the named proof.
6. Return the five-field contract receipt. Use `PASS` only when the proof was
   observed, `BLOCKED` for a named external impediment, and `UNVERIFIED` when
   evidence is absent or contradictory.

## Boundaries

- Do not edit while judging.
- Do not expose credentials or private identifiers in evidence.
- A lower-layer check cannot prove a higher-layer claim.
- Stop when the named proof is observed or concretely falsified.
