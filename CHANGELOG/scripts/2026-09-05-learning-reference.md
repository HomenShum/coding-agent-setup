## 2026-09-05 — Honest numerical comparison

- Commit: candidate
- User outcome: Bootstrap non-overwriting learning contracts and reject invalid or regressing candidate runs.
- Source: Infrastructure failures must not become grades; eligibility must not become activation.
- Files: scripts/bootstrap_learning.py, tests/test_bootstrap_learning.py
- Verification: Scenario tests cover hard gates, corrupt evidence, non-overwrite and bounded case accumulation; synthetic demo explicitly reports no activation.
- Caveats: Comparison does not authenticate provenance, calibration, heldout secrecy or human approval.
