# MCP and agent bridges

MCP gives a coding host a bounded external capability. The person configuring
the project is deciding what data may leave the workstation and what actions a
tool may perform, so add one server for one current workflow rather than
enabling a broad catalog.

## Native project locations

| Host | Project MCP location | Inert starting point | Opt-in server example |
|---|---|---|---|
| Codex | `.codex/config.toml` | `templates/codex/project.config.toml` with `enabled = false` | same file, enabled only after review |
| Claude Code | `.mcp.json` | `templates/project/.mcp.json` | `templates/project/.mcp.json.example` |
| Cursor | `.cursor/mcp.json` | `templates/cursor/mcp.json` | `templates/cursor/mcp.json.example` |

The configuration formats and environment interpolation rules differ. Adapt
the matching template; do not copy one host's object into another host's file.

Primary references: [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli),
[Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference),
[Claude Code MCP](https://code.claude.com/docs/en/mcp), and
[Cursor MCP](https://cursor.com/docs/mcp).

## One local server, three clients

Assume a reviewed project server exposes either a Python module or a script
entrypoint. The examples leave that project-owned name bracketed:

```bash
python3 -m [PROJECT_MCP_MODULE]
# or
python3 /absolute/path/to/project/[PROJECT_MCP_ENTRYPOINT]
```

Every opt-in template intentionally uses `[PYTHON_EXECUTABLE]` instead of
guessing the workstation launcher. Before enabling the server, use one exact
exec form:

- macOS, Linux, or WSL: replace the executable placeholder with `python3` and
  leave the module or script arguments unchanged;
- Windows with the Python launcher: `command = "py"` and prepend `-3` to the
  argument array;
- any platform with a verified absolute interpreter: use that executable and
  do not add the Windows launcher selector.

Never put `py -3` into one `command` string. A host launches `command` as an
executable and passes `args` separately.

TOML basic strings treat backslashes as escapes. A native Windows absolute path
must therefore use forward slashes, doubled backslashes, or a single-quoted
literal string. This exact form is parseable and avoids accidental `\U` or `\p`
escapes:

```toml
[mcp_servers.project_tools]
command = "C:/Users/[WINDOWS_USER]/project/.venv/Scripts/python.exe"
args = ["-m", "[PROJECT_MCP_MODULE]"]
cwd = "C:/Users/[WINDOWS_USER]/project"
enabled = false
```

For a shared Codex project, adapt `templates/codex/project.config.toml` into
the trusted repository's `.codex/config.toml`. Replace
`[ABSOLUTE_PROJECT_ROOT]` with the reviewed absolute checkout path: Codex passes
`cwd` directly to the server process, so it is not relative to the config file.
Its servers remain disabled until reviewed, every placeholder is replaced, and
the server is explicitly enabled.

`codex mcp add` writes the user's `~/.codex/config.toml`; it has no project
scope flag or `cwd` flag. That registration is stable only when the module is
installed into the selected interpreter or the saved command is an absolute,
reviewed launcher that does not depend on the caller's working directory.

The starting `templates/project/.mcp.json` has no server. After review, merge
the definition from `templates/project/.mcp.json.example`; each interactive
local user can then approve the project definition. Replace `[PROJECT_SLUG]` in each server ID with
a short repository-specific slug so a personal or Desktop server cannot
silently collide with it. The script argument starts with
`${CLAUDE_PROJECT_DIR:-.}`: the default makes the JSON parse before Claude adds
`CLAUDE_PROJECT_DIR` to the spawned server environment. Replace
`[PROJECT_MCP_ENTRYPOINT]` with a repository-relative script path. Environment placeholders name variables;
they never contain values. For a PATH-installed entrypoint instead, remove the
script argument and set `command` to that reviewed executable.

Claude Code Desktop and the standalone CLI can resolve the same server name to
different definitions. In a local Desktop Code session,
`claude_desktop_config.json` wins over same-named project `.mcp.json` and user
`~/.claude.json` entries; a user-scope stdio entry can also outrank project
scope in the local Code tab's embedded CLI. Standalone CLI precedence is
different. Use collision-free project IDs, open `/mcp` in the Desktop session
to inspect the loaded command or URL, then run `claude mcp get
YOUR_PROJECT_SERVER_ID` from the project in the standalone CLI and compare the
resolved definition before invoking a tool.

That interactive approval does not protect `claude -p`, Agent SDK, or cloud
sessions: those surfaces cannot stop for the same prompt and may load committed
project servers without asking. Review `.mcp.json` before a headless job checks
out or runs the repository. When a job must exclude project MCP, pass an
operator-owned reviewed config outside the checkout with both flags:

```bash
claude --mcp-config /absolute/path/to/reviewed-mcp.json \
  --strict-mcp-config -p "Describe the requested bounded task"
```

`--strict-mcp-config` limits that run to the explicitly supplied MCP
configuration; an empty reviewed file creates an MCP-free lane.

For Cursor, copy the empty `templates/cursor/mcp.json` first. After review,
merge `templates/cursor/mcp.json.example` into `.cursor/mcp.json`. Its server
example anchors `[PROJECT_MCP_ENTRYPOINT]` to `${workspaceFolder}` and uses
`${env:EXAMPLE_API_KEY}` interpolation. Keep the variable in the launching
environment or a secret manager.

## Remote HTTP servers

Prefer an authenticated remote HTTP endpoint when the provider operates the
server. For a personal Codex server, the CLI writes user scope and can name a
bearer-token environment variable without storing its value. Treat the command
as interactive: after saving an HTTP server, Codex performs OAuth discovery and
may open a browser login. Use the inert reviewed TOML path below when staging
must have no authentication side effect:

```bash
codex mcp add project-remote \
  --url https://mcp.example.invalid/mcp \
  --bearer-token-env-var EXAMPLE_MCP_TOKEN
```

For project scope, do not run that command. Merge the disabled
`project-remote` table from `templates/codex/project.config.toml` into the
trusted project's `.codex/config.toml`, then enable it only after review.
For an OAuth server, remove `bearer_token_env_var`, keep the configured ID
`project-remote`, then authenticate after review:

```bash
codex mcp login project-remote
codex mcp list
```

The configured TOML identifier is `project-remote`; use that exact identifier
for login. Bearer-token and OAuth examples are alternatives, not cumulative
credential sources.

For a desktop-only Codex lane, add the reviewed server URL and identifier in
the app's MCP settings instead of relying on a missing CLI. Save, restart the
app if the server does not appear, open `/mcp` in the same project, and complete
the provider's browser authentication when prompted. Confirm the resolved URL
and tool list before the first read-only call. See the
[Codex app MCP guide](https://learn.chatgpt.com/docs/extend/mcp?surface=app).

Claude Code can create a shared OAuth-capable HTTP entry directly:

```bash
claude mcp add --transport http --scope project \
  YOUR_PROJECT_REMOTE https://mcp.example.invalid/mcp
claude mcp list
```

Use a repository-specific value for `YOUR_PROJECT_REMOTE`. For a bearer-token server, merge `[PROJECT_SLUG]-remote-token` from
`templates/project/.mcp.json.example`; `${EXAMPLE_MCP_TOKEN}` is expanded from
the launching environment. Do not pass the token value through `--header` in a
copy-paste command or commit the expanded value.

In Claude Code Desktop, merge the collision-free definition into the trusted
project's `.mcp.json`, fully restart the app, reopen that project in the Code
tab, and use `/mcp` to inspect the effective server and complete OAuth when the
provider offers it. A CLI `claude mcp add` command configures the terminal lane;
it is not a substitute for observing the Desktop session's effective config.

For Cursor, merge `project-remote-token` from
`templates/cursor/mcp.json.example` into `.cursor/mcp.json`. Cursor expands
`${env:EXAMPLE_MCP_TOKEN}` in the header. For OAuth instead, omit the entire
`headers` object, keep only the remote `url`, and authenticate after review:

```bash
agent mcp login project-remote-token
agent mcp list
```

For a Cursor desktop-only lane, restart Cursor after saving `.cursor/mcp.json`,
open **Customize → Tools & MCP**, enable the reviewed server, and follow its
OAuth prompt when present. Inspect the MCP logs and run one harmless read-only
tool. The `agent mcp` commands above are only for the optional Agent CLI lane.

Never place a bearer token in a URL, command argument, example JSON, or TOML.

For Codex, `startup_timeout_sec` is the server's startup budget; it does not
extend the initial optional-server catalog grace. Keep nonessential servers
optional. For a capability the session cannot safely start without, set
`required = true` after validating its failure behavior. If an optional server
legitimately needs more discovery time, review and set the top-level
`mcp_optional_startup_grace_ms` explicitly instead of assuming the startup
timeout changes it.

## Prefer native subagents for local delegation

All three hosts have project subagent surfaces. Use the adapter matching the
active host:

- `.codex/agents/*.toml`;
- `.claude/agents/*.md`;
- `.cursor/agents/*.md`.

The templates define one evidence worker and one adversarial judge. Keep their
task and write scope bounded, omit reusable model pins, and treat every report
as a claim until the caller verifies the raw diff, log, artifact, or rendered
state. See [Agent stack](agent-stack.md) and the vendors' current
[Codex subagent](https://learn.chatgpt.com/docs/agent-configuration/subagents),
[Claude Code subagent](https://code.claude.com/docs/en/sub-agents), and
[Cursor subagent](https://cursor.com/docs/subagents) documentation.

## Optional cross-host review

When Claude Code needs a Codex review, use OpenAI's maintained Claude Code
plugin. The older `codex mcp-server` bridge is deprecated and is not part of
this setup. In an interactive Claude Code session:

```text
/plugin marketplace add openai/codex-plugin-cc
/plugin install codex@openai-codex
/reload-plugins
/codex:setup
/codex:review --background
/codex:status
/codex:result TASK_ID
```

The background command returns a task identifier. Check its state with
`/codex:status`, then retrieve and inspect the completed receipt with
`/codex:result TASK_ID`; starting background work alone is not a review result.

The plugin requires Node.js 18.18 or newer and an authenticated Codex CLI. See
the [official plugin repository](https://github.com/openai/codex-plugin-cc) and
OpenAI's [`mcp-server` deprecation notice](https://learn.chatgpt.com/docs/mcp-server).

This kit does not bundle the reverse Codex-to-Claude MCP route. Raw
`claude mcp serve` exposes Claude Code tools that can include editing, while
the MCP client owns confirmation behavior; a bare server registration is not a
read-only review boundary. Anthropic documents that responsibility in its
[Claude Code MCP-server guide](https://code.claude.com/docs/en/mcp#use-claude-code-as-an-mcp-server).
For a Claude opinion, run a separate Claude Code session with the checked
read-only agent template and transfer its bounded receipt to Codex. A future
reverse adapter must enforce its tool allowlist, approval boundary, recursion
guard, timeout, output cap, and negative write/spawn scenarios before this kit
can present it as executable.

Enable one reviewed direction per workflow. The caller owns the final decision
and must replay the named proof. Two hosts recursively delegating “completion”
to each other is not independent verification.

## Server admission checklist

Before enabling a server, record:

- owner, canonical source, reviewed revision, and license;
- exact user job and minimum tools required;
- data sent off-machine and retention implications;
- authentication and least-privilege scope;
- startup and tool timeouts, response-size limits, and error semantics;
- URL validation before any server-side fetch;
- disable and uninstall procedure;
- happy, denied, timeout, malformed-response, burst, and sustained-use
  scenarios.

A tool failure must remain a failure. Do not translate a timeout or upstream
error into a successful status or invented score.

## Diagnostics

```bash
codex mcp list
claude mcp list
agent mcp list
python scripts/setup_doctor.py --project-root /path/to/project
```

After enabling a Codex server, start Codex from the trusted project, open `/mcp`,
confirm the expected server and authentication state, then invoke one
documented read-only health or schema tool. A list entry proves configuration
discovery; the harmless tool call proves startup, transport, authentication,
and result parsing. Apply the equivalent active-server inspection and harmless
read-only call in Claude Code and Cursor before granting write tools.

Desktop-only operators use the same observable standard without pretending a
missing CLI exists: open the trusted folder, inspect the app's effective MCP
list, finish authentication, restart after configuration changes, and invoke
one documented read-only health or schema tool. Configuration presence alone
does not prove connection or authorization.

Inspect Cursor's CLI result and active UI status using the current
[Cursor CLI reference](https://cursor.com/docs/cli/reference/parameters) and
[Cursor MCP guide](https://cursor.com/docs/mcp). Treat all diagnostic output as
potentially secret-bearing; sanitize arguments, headers, and paths before
sharing a capture. A green setup-doctor result proves required paths and
configuration parsing; it does not establish server startup, authentication,
tool authorization, or connectivity.
