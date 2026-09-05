# Contributing

Keep contributions small, source-backed, and safe to copy.

1. Check the current vendor documentation for any command or key you change.
2. Update the applicable template and explanatory document together.
3. Add or update the corresponding third-party ledger entry.
4. Never commit a live credential, session export, personal absolute path, or
   private repository URL.
5. Run the offline validator and all scenario tests.
6. Run the external check when network access is available.
7. Add an append-only entry to each affected `CHANGELOG/` lane.

Pull requests should state the user problem, the governing source, the files
changed, the exact verification run, and any claim that could not be verified.
