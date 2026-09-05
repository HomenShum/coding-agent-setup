## 2026-09-05 — Keep new scenarios portable across physical filesystem roots

- Commit: candidate
- User outcome: Run the learning, outcome-ledger and deployment-profile scenarios on macOS as well as Windows and Linux.
- Evidence: Prior public CI failed when a bootstrap fixture used the operating system's linked temporary-directory alias.
- Fix: Create test-owned temporary directories beneath the resolved physical temporary root, following the existing suite convention. Production path guards remain unchanged.
- Twin search: Seven unqualified temporary-directory constructors in the three new scenario files; all corrected. Other test modules already specify a physical root.
- Verification: Focused tests locally; hosted macOS result must be observed separately.
