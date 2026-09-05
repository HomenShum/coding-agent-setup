# Troubleshooting

Start with the failing layer: command installation, instruction discovery,
settings precedence, skill synchronization, subagent discovery, MCP startup,
hook execution, deterministic gates, or the external system a tool calls.
Changing prompt wording cannot repair a missing process or denied credential.

## Run the setup doctor first

```bash
python scripts/setup_doctor.py --project-root /path/to/project
python scripts/setup_doctor.py --project-root /path/to/project --json
```

Exit `0` is ready, `1` is malformed configuration, and `2` means required
paths or commands are missing. The doctor parses committed config syntax but
does not open host credential stores or print config values. When present, it
also parses `.cursor/cli.json`, `.cursor/permissions.json`, and
`.cursor/sandbox.json`. `--skip-binaries`
is appropriate for a fixture or for a desktop-only validation, because the
doctor cannot inspect an app binary. A Cursor desktop-only operator can check
installed terminal hosts with `--hosts codex,claude`, then check Cursor's
repository adapters with `--hosts cursor --skip-binaries`. A Claude Desktop-only
operator can check another installed terminal host with `--hosts codex`, then
check Claude's repository adapters with `--hosts claude --skip-binaries`.
For the app-side check, open the same folder in Claude Desktop, inspect `/mcp`
for unexpected overrides, and ask the session to cite one exact imported
`AGENTS.md` rule.

A ChatGPT desktop-only operator can run
`python scripts/setup_doctor.py --project-root /path/to/project --hosts codex --skip-binaries`,
open that exact folder in the intended Local or WSL environment, inspect `/mcp`,
and ask the session to cite one exact `AGENTS.md` rule. This separates structural
placement from app-side discovery without requiring a terminal CLI.

On Windows, if a freshly installed command is missing, close the installer
PowerShell and open a new terminal before diagnosing the installation. The
vendor installers can update the persistent user `PATH`, but their child
process cannot update the already-running parent shell. On POSIX systems,
check `~/.local/bin` for every selected host command, not just `agent`; see the
PATH recovery block in [Setup](setup.md#2-install-and-authenticate).

The kit requires Python 3.11 or newer and Git. Shell commands may use the
verified `python3` or `py -3` invocation. In Claude's exec-form hook, use
`command: py` with `-3` as the first argument—never `command: py -3`. The
doctor reports the running Python floor and Git availability even when
host-binary checks are skipped.

## Cursor opens a WSL project on Windows instead of Linux

The user wants Cursor's agent tools and terminal to execute inside the Linux
distribution. Opening the project through a Windows Explorer or Recent-items
path can create a Windows-local workspace even when the files live in WSL.

Install Cursor's `anysphere.remote-wsl` extension, enter the distribution, run
`cd /path/to/project && cursor .`, and verify the status bar says
`WSL: [DISTRIBUTION]` before testing tools. Do not rely on a path rooted at
`\\wsl.localhost\[DISTRIBUTION]` as proof of a remote workspace. This recovery
flow follows the
[Cursor staff guidance](https://forum.cursor.com/t/agent-tools-fail-on-wsl-workspace-opened-via-wsl-localhost-path-resolves-to-c-home-glob-times-out-shell-intermittent-cursor-3-9-16/165471/5)
catalogued in the source ledger.

## Project instructions are ignored

- Confirm the host opened the intended repository root.
- Codex reads the `AGENTS.md` chain from root toward the current directory.
- Cursor reads root and nested `AGENTS.md` rules. Do not add a root
  `CLAUDE.md`, because Cursor would load that compatibility file too and could
  receive the shared contract twice.
- Claude imports the shared contract through the exact `@../AGENTS.md` line in
  `.claude/CLAUDE.md`. Put Claude-only project rules in
  `.claude/rules/claude-code.md`; a prose mention is not an import.
- Keep shared rules in `AGENTS.md`; use host files only for real host-specific
  differences.
- For Claude permission or hook policy, start `claude` at the repository root,
  open `/status`, and verify `.claude/settings.json` under **Setting sources**.
  Recheck after `/cd`; project settings follow the primary working directory
  instead of an ancestor search.
- Instructions guide behavior. Use permissions, hooks, CI, and server-side
  authorization when a rule must be enforced.

See [Codex `AGENTS.md`](https://learn.chatgpt.com/docs/agent-configuration/agents-md),
[Claude Code memory](https://code.claude.com/docs/en/memory), and
[Cursor rules](https://cursor.com/docs/rules).

## A skill works in only one host

Verify the canonical tree exists, then regenerate and check Claude Code's
copy:

```bash
python scripts/sync_skills.py manifest --project-root /path/to/project
python scripts/sync_skills.py sync --project-root /path/to/project
python scripts/sync_skills.py check --project-root /path/to/project
```

Codex and Cursor read `.agents/skills`; Claude Code reads `.claude/skills`.
If `sync` reports a divergent target, inspect both copies before using
`--force`. A symlink is rejected because it is not a portable project copy.

## A subagent is missing or behaves differently

Confirm the definition is in the host's own path and format:

- Codex: `.codex/agents/*.toml`;
- Claude Code: `.claude/agents/*.md`;
- Cursor: `.cursor/agents/*.md`.

Avoid a hard-coded reusable model unless the project explicitly tests it.
Claude Code's built-in Explore and Plan agents do not load `CLAUDE.md`, so use
the project custom worker or judge when the shared contract is material to the
task. Recheck [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents),
[Claude Code subagents](https://code.claude.com/docs/en/sub-agents), and
[Cursor subagents](https://cursor.com/docs/subagents).

## An MCP server is missing or fails to start

```bash
codex mcp list
claude mcp list
agent mcp list
```

Then run the server command directly from the same working directory. Check
the executable, arguments, environment-variable names, startup timeout, and
project trust. For Cursor, inspect `.cursor/mcp.json` against the current
[Cursor MCP guide](https://cursor.com/docs/mcp).

For app-only lanes, save the native file, fully restart the app, reopen the same
trusted folder, and inspect the effective server in the UI or `/mcp`. Complete
OAuth when prompted, then call one documented read-only health or schema tool.
In Codex use the app MCP settings and `/mcp`; in Claude Desktop use the Code tab
and `/mcp`; in Cursor use **Customize → Tools & MCP** plus MCP logs. A server
listed in a file is not yet proof of startup, authentication, or tool access.

Do not paste a raw MCP listing into an issue; arguments and headers may contain
credentials.

## A hook does not run

First confirm the sample was intentionally activated. Files ending in
`.example` and the Claude snippet are inert. Then check:

- the host-specific event spelling and configuration location;
- the command's working directory and Python availability;
- JSON input size, timeout, exit code, and output shape;
- permissions for `.agent-local/`;
- for Codex, whether `/hooks` shows the exact reviewed command hash as trusted;
- whether the host fails open or blocks on the observed exit status.

Use the matching primary reference: [Codex hooks](https://learn.chatgpt.com/docs/hooks),
[Claude Code hooks](https://code.claude.com/docs/en/hooks), or
[Cursor hooks](https://cursor.com/docs/hooks). Never diagnose a hook by
enabling a permission-bypass mode.

## Preflight returns `NO_GATE`

`NO_GATE` means required configuration, runtime evidence, a receipt, or visual
disposition is missing or unknown. Read the ordered layer results, repair the
first missing gate, and rerun:

```bash
python scripts/agent_preflight.py --config templates/harness/preflight.json
python scripts/prove_preflight_mutations.py
```

Do not convert exit `2` into promotion success. A fresh-project materialization
test may assert that the placeholder returns exactly `2`, but the target remains
incomplete until its own seven layers pass. The fail-closed result is the
control.

## Cross-host review loops or hangs

Disable one bridge direction. A host called as a reviewer must not invoke the
calling host again. Give the reviewer a bounded artifact and require the
caller to verify the response against raw evidence.

## A push succeeded but public content is stale

Inspect repository visibility and the default branch through the hosting API,
then fetch raw `README.md` and one exact source-ledger signal. A successful Git
push proves transport, not what an anonymous reader receives.
