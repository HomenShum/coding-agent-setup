# Codex + Claude Code + Cursor setup

> **Canonical repository:** continue at
> [codex-claude-cursor-setup](https://github.com/HomenShum/codex-claude-cursor-setup).
> The original `codex-claude-code-setup` repository was renamed in place and
> now includes this kit plus the latest Cursor scope corrections. This separate
> repository is retained as the intermediate publication and history source.
> Read the [subscriber migration guide](https://github.com/HomenShum/codex-claude-cursor-setup/blob/main/docs/repository-migration.md)
> before updating an old clone; do not merge the original pre-rewrite ancestry.

A public, copy-safe setup for using OpenAI Codex, Anthropic Claude Code, and
Cursor in the same repository. One `AGENTS.md` owns the shared project
contract; small host-native adapters provide MCP, hooks, subagents, and skill
discovery without pretending the hosts use one configuration format.

## What is included

For application implementation beyond workstation setup, start with the
[one-prompt application bootstrap](docs/one-prompt-bootstrap.md): context reuse,
data curation, tracing, calibrated evaluation, UI proof and harness qualification.

The [outcome lifecycle](docs/outcome-lifecycle.md) carries frozen versions and
failures across hosts; [enterprise profiles](docs/enterprise-deployment.md)
separate data, inference, telemetry and operator-access requirements.

- current install paths for Windows, macOS, Linux, and WSL;
- one canonical project contract and one canonical `.agents/skills` tree;
- native MCP, hook, and subagent examples for all three hosts;
- a deterministic preflight, setup doctor, skill synchronizer, and scenario
  tests;
- bounded planner-worker-judge and continuity templates;
- machine-readable official-document and external-project ledgers;
- offline validation, secret scanning, and an independent live-link job.

All executable hook samples are disabled examples. Copy one into an active
host configuration only after reviewing its command, input, side effects, and
rollback.

## Five-minute setup

### 0. Verify prerequisites

Install Git and Python 3.11 or newer before copying the kit. The validator and
setup doctor use Python's `tomllib`, and hook examples resolve repository roots
with Git.

```bash
git --version
python --version
```

The examples spell the interpreter as `python`. Shell commands may substitute
the verified `python3` or `py -3` invocation. Claude's hook is exec-form, so a
Windows launcher must use `"command": "py"` and prepend `"-3"` to each `args`
array; `"command": "py -3"` is not an executable name. Codex and Cursor hook
samples are shell-form and may use `py -3`. `scripts/setup_doctor.py` reports
Git and the running interpreter floor alongside the three host binaries.

### 1. Install the hosts

Use the complete [download, inspect, and run recipes](docs/setup.md#2-install-and-authenticate).
They save each vendor script to a new temporary directory, show the complete
contents, require an explicit confirmation, and remove the temporary copy after
the installers finish. The reviewed entrypoints are:

| Terminal host | Windows PowerShell | macOS, Linux, or WSL |
|---|---|---|
| Codex | `https://chatgpt.com/codex/install.ps1` | `https://chatgpt.com/codex/install.sh` |
| Claude Code | `https://claude.ai/install.ps1` | `https://claude.ai/install.sh` |
| Cursor Agent CLI (optional) | `https://cursor.com/install?win32=true` | `https://cursor.com/install` |

An installer is executable code and can fetch additional artifacts. Review its
current contents and vendor source before each use; a previous review does not
authenticate a changed response.

The graphical lanes are separate from those terminal installers:

- install the [ChatGPT desktop app](https://learn.chatgpt.com/docs/app) and sign
  in. On Windows, its Codex agent defaults to native Windows, so keep that
  mode's repository on the Windows filesystem. For a repository inside WSL,
  select WSL as the agent environment in Settings, restart the app, and only
  then open the Linux path; see the
  [Windows app guide](https://learn.chatgpt.com/docs/windows/windows-app). The
  Linux app is a preview; verify the current distribution and architecture
  matrix in the [Linux app guide](https://learn.chatgpt.com/docs/linux/linux-app);
- install Claude and sign in. For a native filesystem, open the Code tab,
  select **Local**, and choose the project folder. For a repository inside the
  WSL filesystem, select its WSL distribution instead of Local so file watching
  and path handling stay inside Linux. See the
  [Claude Code Desktop quickstart](https://code.claude.com/docs/en/desktop-quickstart)
  and [WSL setup](https://code.claude.com/docs/en/desktop-wsl). The Linux desktop
  app is a beta limited to the combinations in its
  [Linux guide](https://code.claude.com/docs/en/desktop-linux);
- install Cursor from its official [download page](https://cursor.com/download),
  sign in, and open the repository. For a WSL project, install Cursor's
  `anysphere.remote-wsl` extension, enter the distribution, launch the folder
  with `cursor .`, and verify the status bar says `WSL: [DISTRIBUTION]`. Do not
  open it from a Windows Explorer or Recent-items path rooted at
  `\\wsl.localhost\[DISTRIBUTION]`, which can put agent tools on the wrong host;
  see the [documented WSL lane](docs/setup.md#2-install-and-authenticate).

Claude Code Desktop includes its graphical coding surface but does not install
the `claude` terminal command. The Cursor endpoint in the table installs only
the optional `agent` CLI. Install either CLI when terminal commands or its CLI
smoke tests are part of your workflow; on POSIX systems, follow the detailed
recipe's general `~/.local/bin` PATH check before treating a missing host
command as an installation failure. On Windows, the reviewed installers run in
child PowerShell processes; close that window and open a new terminal before
version, launch, or authentication checks so it receives the updated user
`PATH`.

Launch each installed CLI once and complete its supported sign-in flow. For a
desktop-only lane, use the corresponding sign-in and folder selection above:

```bash
codex
claude
# Optional CLI:
agent
```

Start Claude from the repository root, not a nested directory:

```bash
cd /path/to/project
claude
```

In Claude, open `/status` and verify the root `.claude/settings.json` appears
under **Setting sources**. Project settings are tied to the session's primary
working directory rather than searched through every ancestor; after `/cd`,
recheck the source list before relying on root permission or hook policy.

Verify the installed commands:

```bash
codex --version
claude --version
agent --version  # only when the optional Agent CLI is installed
codex login status
claude auth status
agent status     # only when the optional Agent CLI is installed
```

The three status commands can reveal account or workspace identifiers. Inspect
them locally and record only a redacted pass/fail receipt.

Current Claude Code documents `claude doctor` as a read-only installation,
settings, and environment diagnostic that does not start an interactive
session. Use `/mcp` in an interactive session for MCP discovery and
authentication. This kit's `scripts/setup_doctor.py` is a separate,
non-executing structural check.

Primary references: [ChatGPT desktop app](https://learn.chatgpt.com/docs/app),
[Codex CLI authentication](https://learn.chatgpt.com/docs/auth?surface=cli),
[Claude Code Desktop](https://code.claude.com/docs/en/desktop-quickstart),
[Claude Code platforms](https://code.claude.com/docs/en/platforms),
[Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference),
[Claude installation troubleshooting](https://code.claude.com/docs/en/troubleshoot-install),
[Cursor desktop quickstart](https://cursor.com/docs/get-started/quickstart), and
[Cursor Agent CLI parameters](https://cursor.com/docs/cli/reference/parameters).

### 2. Install one shared contract

Copy and adapt `templates/project/AGENTS.md` at the project root. Claude Code
receives the same contract from `.claude/CLAUDE.md`, whose only content is the
real `@../AGENTS.md` import. Do not add a root `CLAUDE.md`: Cursor already
loads `AGENTS.md`, so a root compatibility file would load the contract twice.
Put Claude-only rules under `.claude/rules/`.

For a fresh or existing Git repository, use the
[reviewable setup plan](docs/setup.md#4-bootstrap-a-repository) before continuing.
It reports missing, identical, conflicting and blocked destinations without
writing. Apply only reviewed missing files; existing instructions and configs
remain manual merge work. Fresh setup uses the same map for helpers, native
adapters, disabled MCP examples and unconfigured harness. Copying them does
not activate a host or prove your application ready.

```text
your-project/
├── .gitignore                    # generated mirror/worktrees, local settings, env, hook state
├── AGENTS.md
├── AGENT_INVARIANTS.md           # complete portable behavioral contract
├── .agents/skills/              # canonical project skills
├── .codex/
│   ├── config.toml
│   └── agents/
├── .claude/
│   ├── settings.json
│   ├── CLAUDE.md                # import-only: @../AGENTS.md
│   ├── agents/
│   ├── rules/claude-code.md      # Claude-only
│   └── skills/                  # generated checked copy
├── .cursor/
│   ├── mcp.json
│   └── agents/
└── .mcp.json
```

Review every bracketed field and permission. Do not overwrite existing
personal or project settings blindly.

Optional local-only examples are routed explicitly: manually merge
`templates/codex/config.toml` into `~/.codex/config.toml`, and copy
`templates/claude/settings.local.json.example` to
`.claude/settings.local.json` only for a private project override. The latter
destination and Claude's separate `CLAUDE.local.md` private instruction file
are ignored; neither optional template belongs in the automatic materialization
path. For Cursor's `agent` CLI, merge the reviewed
`templates/cursor/cli-config.json.example` keys into the personal
`~/.cursor/cli-config.json`; copy `templates/cursor/cli.json.example` to the
target `.cursor/cli.json` only when the project needs an explicit CLI permission
policy. Both Cursor examples start with an empty allowlist. Generated
`.claude/worktrees/` checkouts are ignored as well.

Cursor's desktop/local Agent uses different files from the optional CLI. Review
`templates/cursor/permissions.json.example` before copying it to
`.cursor/permissions.json`, and review `templates/cursor/sandbox.json.example`
before copying it to `.cursor/sandbox.json`. Permission lists combine across
user and project scope. Project sandbox settings have higher priority, but
extra paths are unioned and restrictive network or boolean values win; team and
built-in limits remain stronger. The permission file applies only when a Run
Mode is enabled. These controls reduce accidental authority but are not a
security boundary.

### 3. Synchronize project skills

Codex and Cursor consume `.agents/skills` directly. Claude Code uses a checked
copy at `.claude/skills`:

```bash
python scripts/sync_skills.py sync --project-root /path/to/project
python scripts/sync_skills.py check --project-root /path/to/project
```

The synchronizer refuses to overwrite a divergent Claude copy unless the
operator explicitly supplies `--force`. It also reports and preserves any
host-only extra while `check` remains failed, so drift cannot masquerade as a
canonical copy. The skill format is based on the public
[Agent Skills specification](https://github.com/agentskills/agentskills).

### 4. Add only the native adapters you need

Copy reviewed examples to their host-owned locations:

| Capability | Codex | Claude Code | Cursor |
|---|---|---|---|
| MCP | `.codex/config.toml` | `.mcp.json` | `.cursor/mcp.json` |
| Subagents | `.codex/agents/*.toml` | `.claude/agents/*.md` | `.cursor/agents/*.md` |
| Hooks | `.codex/hooks.json` | `hooks` in `.claude/settings.json` | `.cursor/hooks.json` |
| Permission policy | policy keys in `.codex/config.toml` | shared `permissions` in `.claude/settings.json` | `.cursor/permissions.json` (desktop/local Agent); `.cursor/cli.json` (Agent CLI) |
| Sandbox | host policy in `.codex/config.toml` | Claude permission and sandbox controls | `.cursor/sandbox.json` (desktop/local Agent) |

The materialized Claude Code and Cursor MCP files are empty; Codex's example
server is disabled. Hook files remain examples outside active paths. Add one
reviewed capability for one concrete user job. See
[MCP and agent bridges](docs/mcp-and-agent-bridges.md) and
[Skills, plugins, hooks, and subagents](docs/skills-plugins-hooks.md).

### 5. Diagnose and prove the setup

From the materialized target project, run its copied operational checks:

```bash
cd /path/to/project
python scripts/setup_doctor.py --project-root . --skip-binaries
python scripts/agent_preflight.py --config templates/harness/preflight.json
python scripts/prove_preflight_mutations.py
```

A fresh target is expected to return exit `2` / `NO_GATE`: it has no honest
project-specific paths, scenario commands, visual decision, or digest-bound
review receipt yet. Configure those before treating exit `0` as a promotion
gate. The setup kit's own checkout has a separate configured preflight and can
pass without lending that receipt to the target.

To validate this setup kit itself, return to its checkout and run:

```bash
python scripts/validate_repo.py
python -m unittest discover -s tests -v
python scripts/check_private_history.py  # requires a full, clean publication history
```

The structural setup-doctor command above skips binaries so it also fits a
Cursor desktop-only workstation. Run it without `--skip-binaries` when all
three CLIs are installed, or use `--hosts codex,claude` plus a separate
`--hosts cursor --skip-binaries` check. The doctor does not open credential
stores, print config values, or prove an MCP server can connect.
The same structural lane works for a ChatGPT desktop-only workstation with
`--hosts codex --skip-binaries`; then open the same folder in the intended app
environment, inspect `/mcp`, and ask the session to cite one exact `AGENTS.md`
rule. A Claude Desktop-only lane uses `--hosts claude --skip-binaries` plus the
same `/mcp` and imported-rule checks.
Preflight fails closed when a required gate is missing. Repository validation,
tests, and the reachable-history marker gate run offline; use
`python scripts/validate_repo.py --check-external` only when network access is
intended.

## Repository map

| Path | Purpose |
|---|---|
| [`docs/setup.md`](docs/setup.md) | installation, placement, synchronization, and migration |
| [`docs/capability-matrix.md`](docs/capability-matrix.md) | current three-host capability mapping |
| [`docs/agent-stack.md`](docs/agent-stack.md) | bounded planner, workers, gate, and judge protocol |
| [`docs/mcp-and-agent-bridges.md`](docs/mcp-and-agent-bridges.md) | native MCP setup and bounded cross-host review |
| [`docs/proof-workflow.md`](docs/proof-workflow.md) | observable proof and promotion workflow |
| [`docs/preflight-and-continuity.md`](docs/preflight-and-continuity.md) | seven preflight layers and disabled hook samples |
| [`docs/skills-plugins-hooks.md`](docs/skills-plugins-hooks.md) | reusable extension and subagent boundaries |
| [`docs/security.md`](docs/security.md) | credential, permission, hook, and publication checks |
| [`docs/external-projects.md`](docs/external-projects.md) | human-readable attribution ledger |
| [`sources/`](sources/) | machine-readable citations and capability catalogs |
| [`templates/`](templates/) | copy-and-adapt examples; none are active in this repository |

## Design boundary

This repository is a setup kit, not an export of a workstation. Sanitized
dependency and attribution metadata informed the historical source ledger;
authentication files, application code or prose, session transcripts, memories,
caches, local project registries, private repository identities, and
machine-specific paths are never copied into the publication.
Third-party projects retain their own licenses; citation does not relicense
their content.

## License

Original documentation, templates, and validation code are available under
the [MIT License](LICENSE). External projects remain under the licenses
recorded in the attribution ledger.
