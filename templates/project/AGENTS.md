# [PROJECT_NAME] instructions

Before changing files, read the complete
[portable invariants](AGENT_INVARIANTS.md). Project policy may tighten those
rules but must not silently weaken them.

## Product boundary

[One paragraph: who uses this project, the decision or job they complete, what
the system may do, and what it must never do.]

## Invariants

- [The most important truth the implementation must preserve.]
- [The authorization or data-integrity boundary.]
- [The observable rendering or API contract.]

## Run it

```bash
[INSTALL_COMMAND]
[START_COMMAND]
```

## Verification

```bash
[FAST_OFFLINE_TEST]
[FULL_TEST]
[FORMAT_OR_TYPECHECK]
```

Tests use realistic personas and cover happy, rejected, degraded, adversarial,
burst, and sustained-use paths in proportion to risk.

## Repository map

```text
[PATH]/    [RESPONSIBILITY]
[PATH]/    [RESPONSIBILITY]
```

## Change rules

- Trace the observed symptom to its earliest owned cause before editing.
- Keep the change proportional: patch, feature, or system change.
- Preserve unrelated work in a dirty worktree.
- Put credentials in environment variables or a secret manager.
- Document any new dependency, public API, configuration knob, or authority.
- Verify user-visible changes in the running product at declared viewports.
- Do not call a remote change published until its public content is observed.

## Definition of done

[Name one user journey and the exact observable proof required for promotion.]
