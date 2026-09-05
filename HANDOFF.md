# Current handoff

- Owner: repository maintainer
- Goal: maintain a public, product-neutral setup for Codex, Claude Code, and Cursor
- Current state: reviewed three-host setup kit exported into a fresh repository for authorized publication
- Canonical instructions: `AGENTS.md`
- Canonical skills: `templates/project/.agents/skills`
- Named proof receipts:
  - `python scripts/validate_repo.py` -> PASS
  - `python -m unittest discover -s tests -v` -> 184 tests passed; 2 platform-inapplicable FIFO scenarios skipped on Windows
  - `python scripts/agent_preflight.py --config templates/harness/preflight.json` -> all seven layers passed
  - `python scripts/prove_preflight_mutations.py` -> 30 tests, 0 failures, 0 errors, 1 platform-inapplicable skip
  - `python scripts/validate_repo.py --check-external` -> 183 bounded external URL checks passed
  - `python -m compileall -q scripts tests`, `git diff --check`, and `python scripts/check_claim_language.py HANDOFF.md handoffs/0001/HANDOFF.md` -> PASS
  - Visual proof -> N/A; this change has no user-interface surface
- Privacy boundary: only reviewed publishable files enter this fresh repository; prior Git objects and ignored local state are excluded
- Publication destination: `HomenShum/coding-agent-setup`
- Authorization: the repository owner authorized fresh-history publication on 2026-09-05
- Publication gate: require `python scripts/check_private_history.py` to pass on the new commit and again in a full clone of the public remote; verify public raw files anonymously
- Next reader: inspect the latest GitHub validation run and rerun the named proof before modifying or redistributing the kit
