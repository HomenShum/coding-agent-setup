# Portable agent invariants

These rules describe the human situation before the mechanism: a person asks
an agent to change a real system, and the system must make success falsifiable.
Project-specific policy may be stricter, but should not weaken these rules.

1. **No artifact, no claim.** Completion needs a receipt another person can replay.
2. **Capture the before first.** A before-state created after an edit is not evidence.
3. **Fail closed.** A missing or unknown gate is `NO_GATE`, never a pass.
4. **Append decisions.** Correct a ledger with a `SUPERSEDES` entry; keep history.
5. **Label certainty.** Work is `PLANNED`, `IMPLEMENTED`, or `PROVEN`; facts are `MEASURED`, `ASSUMED`, `INFERRED`, or `UNVERIFIED`.
6. **Reuse before replace.** Replacement requires a concrete observed failure.
7. **Probe before trust.** Run a command once before recommending it, and inspect inherited tools before treating a filesystem-read-only worker as isolated.
8. **Keep secrets out of artifacts.** Record variable names or fingerprints, never values.
9. **Mutation-test gates.** Every gate must be observed rejecting a known violation.
10. **Zero forbidden states outrank green tests.** Sweep for combinations tests may miss.
11. **Check collisions before implementation.** Record overlapping work and precedent.
12. **Inspect automation before publishing.** Deployment and scheduled jobs are actors too.
13. **Change shape and version together.** A public schema change without a version change fails.
14. **Expose every caught failure.** A handler must emit a bounded diagnostic.
15. **Verify the runtime at entry.** Record the interpreter and required imports.
16. **Synchronize conventions before writing.** Confirm the canonical source and installed copies.
17. **State cache-key exclusions.** Name what a cache key does not capture.
18. **Verify rendering before recording it.** Deterministic layout checks precede media claims.
19. **Turn repeated review comments into gates.** Repetition means the control is missing.
20. **Refresh the handoff before yielding.** A new host needs current state, ownership, and proof.
21. **Turn repeated workflows into skills.** A reusable workflow needs a verifier and refusal path.
22. **Make communication policy explicit.** Put channel/thread conventions in a project-owned template.

Instruction files explain these invariants. The preflight, permissions, hooks,
CI, and server-side authorization enforce the subset that can be deterministic.
