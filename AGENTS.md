# Repository instructions

This repository is a public, vendor-neutral setup kit for OpenAI Codex,
Anthropic Claude Code, and Cursor. It contains documentation, inert
configuration examples, portable skills, and validation code. It does not
contain credentials, session transcripts, private project source, or
machine-specific configuration.

## Sources of truth

- `README.md` is the shortest supported path for a new user.
- `docs/setup.md` owns installation, file placement, and configuration scope.
- `docs/mcp-and-agent-bridges.md` owns MCP and cross-agent setup.
- `docs/skills-plugins-hooks.md` owns reusable workflow extensions.
- `docs/capability-matrix.md` owns the current three-host path mapping.
- `docs/preflight-and-continuity.md` owns deterministic gate and hook-state
  behavior.
- `sources/external-projects.json` is the machine-readable third-party ledger.
- `sources/official-docs.json` is the machine-readable vendor-document ledger.
- `sources/host-capabilities.json` and `sources/skills.json` are the
  machine-readable host and canonical-skill catalogs.
- `templates/` contains examples only. No example may contain a working token,
  private hostname, personal absolute path, destructive default, or
  automatically active hook.

## Change rules

- Check current OpenAI, Anthropic, and Cursor documentation before changing a
  host command, path, event, or configuration key. Record the access date.
- Add every deliberately used or recommended GitHub repository to
  `sources/external-projects.json` and `docs/external-projects.md`.
- Keep `AGENTS.md` canonical. Claude imports it from `.claude/CLAUDE.md` with
  `@../AGENTS.md`; no root `CLAUDE.md` exists for Cursor to load a second copy.
  Put Claude-only guidance in `.claude/rules/`.
- Keep project skills canonical at `.agents/skills`. Codex and Cursor consume
  that tree directly; Claude Code receives a checked `.claude/skills` copy
  through `scripts/sync_skills.py`.
- Keep MCP, hooks, and subagents host-native. Shared behavior does not justify
  translating one host's configuration into another host's file.
- Put credentials in environment variables or an external secret store. Never
  place them in command arguments, MCP URLs, committed JSON, or TOML.
- Hooks execute code with the user's authority. Examples must be disabled by
  default and must explain their trigger, inputs, side effects, and rollback.
- Preserve the distinction between guidance and enforcement: instruction files
  guide a model; permissions, hooks, CI, and server-side authorization enforce
  policy.
- Update the relevant append-only `CHANGELOG/` lane for substantive changes.

## Verification

Run from the repository root:

```bash
python scripts/validate_repo.py
python -m unittest discover -s tests -v
python scripts/agent_preflight.py --config templates/harness/preflight.json
python scripts/prove_preflight_mutations.py
python scripts/validate_repo.py --check-external
git diff --check
```

The external check requires network access. Offline validation and scenario
tests must pass without credentials or network access.

## Completion bar

A change is complete only when a new user can identify every destination,
reproduce the Claude skill mirror, parse the templates, resolve all local
links, trace external sources, observe a deliberate preflight mutation fail,
and pass the scenario suite. A green command is evidence for that command
only; do not call remote content published until the public repository is
fetched and the promised files are observed.
