# Validator changelog

- 2026-09-04: bind current-kit Git/Python prerequisites and every human ledger
  relationship, license, and access date to the machine-readable source catalog.
- 2026-09-04: reject concrete Windows drive-root paths written with either
  separator while preserving only the documented generic placeholders.

## 2026-09-04 — Validate the complete host and source contract

- Commit: uncommitted local change; publication is blocked by the current
  reachable-history privacy gate until a clean fresh history or separately
  authorized rewrite is reviewed.
- User outcome: maintainers can detect host-capability drift, skill-catalog
  drift, invalid example formats, private-source markers, and missing current
  citations before publication.
- Source: the repository capability matrix, private-marker policy, and current
  primary vendor documents.
- Files: `scripts/validate_repo.py`, scenario tests, source catalogs, and CI.
- Verification: normal, malformed, adversarial, concurrent, burst, sustained,
  and mutation scenarios run locally without credentials on Windows; the same
  suite is configured for Windows, macOS, and Linux CI after publication.
- Repairs: count empty directories toward the traversal cap, detect digest-only
  blocked markers across punctuation/whitespace/format characters, and fail
  when a copy-by-default MCP or hook template becomes active.
- Repairs: cap aggregate publication reads at 32 MiB and validate every
  canonical skill contract plus the standalone authoring scaffold. Require
  both kit and materialized-project ignores to cover generated worktrees and
  private Claude override paths.
- Repairs: share a symlink/junction-aware path-chain guard with the operational
  scripts so NTFS reparse points cannot turn a repository scan into an outside
  read.
- Repairs: scan concrete Windows drive-root and UNC paths while retaining only
  explicit documentation placeholders.
- Repairs: add a full-clone reachable-history gate with independent ref,
  commit, path, object, blob, byte, output, marker-window, and aggregate-time
  caps; a marker added and deleted in a later commit still blocks publication
  without echoing its text. Exhaustive changed-path enumeration prevents a
  reused blob from hiding a second historical filename.
- Repairs: run all Git proof commands with a clean `GIT_*` environment, disable
  replacement objects, and fail closed when the effective Git metadata exposes
  a legacy graft file. Real replace-ref and graft scenarios prove that neither
  history nor ancestry can be rewritten for one process and accepted as truth.
- Repairs: parse and constrain Cursor desktop/local Agent permission and
  sandbox examples independently from the optional Agent CLI policy.
- Repairs: make the setup doctor parse every optional project Cursor policy
  file when present, without making a desktop or CLI policy mandatory.
- Repairs: bind the human attribution view to the exact machine-ledger digest
  and enforce category, evidence, confidence, optional-note, revision, and
  official-source semantics with adversarial mutation tests.
- Repairs: strip credential-bearing headers on cross-origin redirects and give
  every live-source child the remaining aggregate deadline without overstating
  the timeout it received.
- Caveats: content scans reduce risk but do not replace review of the staged
  diff.

## 2026-09-05 — Prepare fresh-history publication

- User outcome: the public setup kit starts with reviewed files and no inherited Git objects.
- Changes: align the self-repository attribution exemption with the publication destination; allow fifteen bounded minutes for the multi-platform offline CI job after the measured local scenario suite exceeded five minutes on its own.
- Verification: offline validation, scenario tests, preflight, and a fresh-history scan must pass before upload; public raw content and a full remote clone are checked afterward.

## 2026-08-23 — Add bounded publication checks

- Commit: `79508f0`
- User outcome: a maintainer can detect secrets, private paths, broken local
  links, invalid templates, missing attribution—including non-URL GitHub
  Actions references—and stale external sources.
- Source: observed publication and agent-tool failure modes.
- Files: `scripts/validate_repo.py`, `tests/test_setup_scenarios.py`, and CI.
- Verification: scenario tests cover normal, adversarial, degraded, concurrent,
  burst, and sustained-use behavior. Every regular publication file is scanned
  as bounded UTF-8 input, including uncommon credential-file extensions.
- Caveats: pattern scans supplement review; they cannot prove no secret exists.
