# Configuration template changelog

## 2026-09-04 — Add native adapters for every supported host

- Commit: uncommitted local change; publication is blocked by the current
  reachable-history privacy gate until a clean fresh history or separately
  authorized rewrite is reviewed.
- User outcome: teams can copy host-native MCP, subagent, and disabled hook
  examples without translating schemas or committing credential values.
- Source: current Codex, Claude Code, and Cursor configuration documentation.
- Files: `templates/codex/`, `templates/claude/`, `templates/cursor/`, and
  `templates/harness/hook-admission.json`.
- Verification: JSON, TOML, snippet, path, and secret scans plus setup-doctor
  scenarios and a fresh-project materialization preflight.
- Repair: aligned the canonical project verification heading with the
  fail-closed convention rule after an independent clean-copy test exposed the
  mismatch.
- Repair: documented Claude Code's native PowerShell support, then removed
  both shell tools from agents advertised as read-only; the parent now replays
  named commands while interactive sessions may use their native shell.
- Repair: added copy-by-default ignore rules for the generated Claude skill
  mirror and worktrees, local continuity-hook state, both private Claude
  override paths, and environment files while retaining `.env.example`.
- Repair: replaced POSIX command substitution in Codex `commandWindows` hook
  examples with a native Git-root resolver and proved it from a nested Windows
  directory under a repository path containing spaces.
- Repair: cover every current Codex and Claude SessionStart source, document
  Codex hash trust/re-review, and expose the parent-override limit on Codex
  subagent sandbox defaults.
- Repair: add separate Cursor Agent CLI personal and project permission
  examples; both parse, keep allowlists empty, preserve deny precedence, and do
  not masquerade as desktop-editor settings.
- Repair: add separate opt-in Cursor desktop/local Agent permission and sandbox
  examples with no allowed tools, explicit secret-access block instructions,
  no additional filesystem paths, and default-deny networking; neither is
  described as a security boundary.
- Repair: document a parseable native-Windows Codex MCP path using TOML-safe
  forward slashes so ordinary backslashes cannot become invalid escapes.
- Caveats: examples become executable only after explicit review and copying
  into an active host path.

## 2026-08-23 — Add copy-safe configuration examples

- Commit: `79508f0`
- User outcome: a team can start from parsed, permission-gated examples and
  supply credentials by environment-variable name. Codex MCP examples are
  disabled; Claude project MCP remains subject to each user's approval.
- Source: current vendor configuration, MCP, skills, and memory documentation.
- Files: `templates/`.
- Verification: JSON/TOML parsing and repository secret scan.
- Caveats: every project must choose its own permission policy.
