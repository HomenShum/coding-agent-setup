## 2026-09-05 — Keep full history review within the right budget boundaries

- Commit: candidate
- User outcome: A release maintainer can review cumulative clean revisions without mistaking a clean-tree work budget for the size of the entire history.
- Source: The provenance guide requires every reachable object and path; no old revisions may be skipped.
- Before, captured before the scanner edit: `python scripts/check_private_history.py` exited 1 with `ERROR: reachable-history private marker scan exceeded its bounded window budget`.
- Intended change: Keep the existing hash-window cap per inspected value and retain aggregate byte, inventory, object and elapsed-time limits for the complete history. Check the deadline around CPU scanning as well as Git commands.
- Before scenario capture: `python -m unittest discover -s tests -p test_history_scaling.py -v` ran four scenarios; three failed (cumulative clean history, a removed late obfuscated marker masked by the exhausted budget, and a CPU scan finishing after its deadline). The existing resource-bound scenario passed.
- Scope: No new dependencies, public APIs, configuration knobs, caches or numeric limit increases. The digest-only normalization/hash helper and full-history traversal remain unchanged.
- Twin check: The other aggregate uses of the clean-tree window budget are working-tree scanning and diagnostic redaction in `validate_repo.py`; neither traverses cumulative Git history, so both remain unchanged.
- After, same release command and reachable commit graph (`c2c91408ab5c2c395f60d2001854063bc4eec3c3`): `PASS: bounded reachable-history marker validation`, scanner exit 0, elapsed 95.065 seconds on Windows (unchanged 240-second aggregate cap).
- Scenario verification: The original four-scenario suite passed after the scanner edit. A final rerun strengthened the historical marker to full-width uppercase plus punctuation and passed all four scenarios in 21.851 seconds. Existing `test_history_scenarios.py` passed all 10 scenarios in 49.682 seconds, including deleted and merge-only historical paths, replacement refs, grafts, shallow-clone refusal and resource caps.
- Additional checks: `python scripts/validate_repo.py` and scoped `git diff --check` passed. No remote was changed; full public-history proof must be rerun after the release commit is created.
