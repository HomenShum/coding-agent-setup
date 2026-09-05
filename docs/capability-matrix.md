# Host capability matrix

One project contract can guide all three hosts, but their configuration files
are not interchangeable. Unless a row says otherwise, these paths describe
local desktop, IDE, and CLI sessions. This matrix was rechecked against the
vendors' primary documentation on 2026-09-04.

| Capability | Codex | Claude Code | Cursor |
|---|---|---|---|
| Project instructions | Root and nested `AGENTS.md` | Import-only `.claude/CLAUDE.md` plus Claude-only `.claude/rules/` | Root and nested `AGENTS.md` |
| Project skills | `.agents/skills` | `.claude/skills` | `.agents/skills` or `.cursor/skills` |
| Project subagents | `.codex/agents/*.toml` | `.claude/agents/*.md` | `.cursor/agents/*.md` |
| Project MCP | `.codex/config.toml` | `.mcp.json` | `.cursor/mcp.json` |
| Project hooks | `.codex/hooks.json` in a trusted project | `hooks` in `.claude/settings.json` | `.cursor/hooks.json` |
| Permission policy | policy keys in `.codex/config.toml` | shared `permissions` in `.claude/settings.json` | `.cursor/permissions.json` (desktop/local Agent); `.cursor/cli.json` (Agent CLI) |
| Sandbox policy | Codex sandbox settings | Claude permission and sandbox controls | `.cursor/sandbox.json` (desktop/local Agent); CLI policy remains separate |
| Parallel workers | Supported; bounded by Codex agent settings | Supported through subagents | Supported through foreground/background tasks |

For reusable agents, omit Codex's TOML `model` key so the parent setting is
inherited; Claude Code and Cursor Markdown frontmatter may use
`model: inherit`. A requested worker or judge model can be unavailable or
replaced by account or administrator policy, so verification must depend on
receipts and observed checks rather than a model name.

Claude Code does not natively load `AGENTS.md`, and its built-in Explore and
Plan agents omit `CLAUDE.md`. The templates therefore use an import-only
`.claude/CLAUDE.md`, put Claude-only guidance in `.claude/rules/`, and give
custom worker/judge definitions the critical filesystem and evidence rules
directly. Cursor loads the root `AGENTS.md`; omitting root `CLAUDE.md` prevents
the same shared contract from entering Cursor's context twice.

The Codex and Cursor worker templates are filesystem-read-only defaults, not a
complete tool boundary. Codex can inherit parent MCP configuration and live
permission overrides; Cursor subagents inherit all parent MCP tools. Inspect and
narrow the effective parent tools before delegating proof work. Cursor Cloud
subagents are a different surface: they use team MCP configuration at
`cursor.com/agents`, not the local session's `.cursor/mcp.json`; see
[Cursor cloud subagents](https://cursor.com/docs/subagents#cloud-subagents).

Cursor and Codex read the canonical `.agents/skills` tree directly. Claude
Code uses `.claude/skills`; run `scripts/sync_skills.py` to copy and verify a
project mirror. Tracked whole-directory symlinks are intentionally avoided so
the same kit works on native Windows and restricted filesystems.

Cursor's desktop/local Agent permission lists combine across user and project
scope and apply only when a Run Mode is enabled. Project sandbox values have
higher priority, but extra paths are unioned and restrictive network or boolean
values win; team and built-in restrictions remain stronger. The optional Agent
CLI uses its own configuration. These policy files steer tool use but are not a
security boundary, so hostile code still needs OS-level isolation and secrets
outside the workspace.

Primary references: [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents),
[Codex hooks](https://learn.chatgpt.com/docs/hooks),
[Claude Code subagents](https://code.claude.com/docs/en/sub-agents),
[Claude Code skills](https://code.claude.com/docs/en/skills),
[Claude Code hooks](https://code.claude.com/docs/en/hooks),
[Cursor rules](https://cursor.com/docs/rules),
[Cursor `CLAUDE.md` compatibility](https://cursor.com/help/customization/rules),
[Cursor skills](https://cursor.com/docs/skills),
[Cursor subagents](https://cursor.com/docs/subagents),
[Cursor hooks](https://cursor.com/docs/hooks),
[Cursor desktop/local Agent permissions](https://cursor.com/docs/reference/permissions),
[Cursor sandbox configuration](https://cursor.com/docs/reference/sandbox),
[Cursor CLI configuration](https://cursor.com/docs/cli/reference/configuration),
[Cursor CLI permissions](https://cursor.com/docs/cli/reference/permissions), and
[Cursor MCP](https://cursor.com/docs/mcp).
