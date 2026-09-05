# Setup guide changelog

## 2026-09-04 — Support one contract across three native hosts

- Commit: uncommitted local change; publication is blocked by the current
  reachable-history privacy gate until a clean fresh history or separately
  authorized rewrite is reviewed.
- User outcome: a newcomer can materialize a fresh Codex, Claude Code, and
  Cursor project, synchronize the Claude skill copy, diagnose placement, and
  trace each product claim to current primary documentation.
- Source: current OpenAI, Anthropic, Cursor, and Agent Skills references in the
  machine-readable ledgers.
- Files: `README.md`, `docs/`, `AGENTS.md`, `.claude/CLAUDE.md`, `.gitignore`, source
  catalogs, and CI.
- Verification: offline validator, scenario suite, preflight mutation proof,
  copied-project preflight, and a separate bounded external-link job.
- Repair: replaced the deprecated Claude-to-Codex MCP bridge command with
  OpenAI's maintained Claude Code plugin workflow and catalogued the official
  deprecation notice.
- Repair: removed the bare reverse MCP registration because its editing tools
  and client-owned confirmations do not establish a bounded review surface;
  cross-host return now uses a separate read-only session receipt.
- Repair: made the README's short path explicitly invoke the complete
  materialization sequence before any copied script is used.
- Repair: declared and diagnosed the real Git plus Python 3.11 prerequisites,
  and aligned both preflight and CI with the standard library the scripts use.
- Repair: let the Windows bootstrap select either `python.exe` or the `py -3`
  launcher while keeping executable and prefix arguments separate.
- Repair: distinguish Cursor's `agent` CLI installer from its desktop editor,
  document the POSIX PATH location, and add bounded personal and project CLI
  permission examples from the current configuration references.
- Repair: make Windows users reopen a terminal after child-process installers,
  recover `~/.local/bin` for every selected POSIX command, and probe `curl` and
  `bash` before downloading installer files.
- Repair: add explicit ChatGPT, Claude, and Cursor desktop-only diagnosis,
  qualify the two Linux graphical lanes, and require Cursor WSL projects to be
  opened from the distribution with the remote-host indicator visible.
- Repair: replace a stale `claude doctor` warning with its current read-only
  diagnostic contract and route MCP verification through an interactive
  `/mcp` inspection.
- Repair: add app-side remote-MCP save, restart, authentication, effective-list,
  and harmless read-only checks for all three graphical hosts.
- Repair: add the previously omitted historical deterministic prose-checker
  repository to both attribution ledgers while stating that this kit's claim
  checker is independently authored.
- Caveats: hook and MCP examples remain inert until a user reviews and copies
  them into an active project. Current-tree validation does not certify or
  rewrite an existing remote history.

## 2026-09-05 — Point readers to the new public repository

- User outcome: clone-path examples, the private vulnerability-report link, and the maintainer handoff identify the new three-host setup repository.
- Verification: local link and attribution validation must pass; public content and private vulnerability-reporting availability are checked after repository creation.

## 2026-08-23 — Publish one cross-client setup path

- Commit: `79508f0`
- User outcome: a newcomer can configure Codex and Claude Code around one
  shared project contract without copying private machine state.
- Source: current OpenAI and Anthropic installation, settings, instruction,
  MCP, skills, plugins, and hooks documentation.
- Files: `README.md`, `docs/`, `AGENTS.md`, `.claude/CLAUDE.md`, and source ledgers.
- Verification: offline validator, 11-scenario suite, and 129 bounded external
  links passed. After the initial push, GitHub reported `PUBLIC` with `main` as
  default; anonymous raw fetches returned HTTP 200 for the README title signal
  and a 111-project machine ledger at remote commit `79508f0`.
- Caveats: vendor documentation is mutable; access dates are recorded.
