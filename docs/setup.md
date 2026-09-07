# Setup and configuration

The human goal is one repository that behaves consistently in three coding
hosts. Shared behavior lives in `AGENTS.md` and `.agents/skills`; settings,
MCP, hooks, and subagents stay in each host's native format. The capability
paths below were rechecked against primary vendor documentation on 2026-09-04.

## 1. Choose the operating environment

| Environment | Recommendation |
|---|---|
| macOS or Linux | Use the native installers and your normal shell. |
| Windows, native | Use PowerShell and verify all three commands are on `PATH`. |
| Windows, Linux-first toolchain | Use WSL2 and keep the repository in the Linux filesystem. |
| Managed workstation | Confirm allowed installers, authentication, hooks, and tool permissions with the administrator. |

Codex and Claude Code document native Windows and WSL paths. Cursor supplies
CLI installers for Windows and POSIX shells. An instruction file cannot grant
OS access, so select the environment before copying permission examples.
Native Windows and WSL use different home directories, so their Codex config,
authentication, and session files are separate by default. If the same person
intentionally wants both environments to share those files, follow the
[opt-in procedure to share config, auth, and sessions with WSL](https://learn.chatgpt.com/docs/windows/windows-app#share-config-auth-and-sessions-with-wsl)
instead of copying either home directory wholesale.
Claude Code supports native shell tools, including PowerShell on Windows, but
this kit's read-only worker and judge deliberately allow neither shell. They
identify commands for the parent to replay so read-only evidence collection
does not depend on inherited command permissions.

Before installation, verify Git and Python 3.11 or newer:

```bash
git --version
python --version
```

The kit uses `tomllib`, which makes 3.11 the honest minimum. Shell commands
below use `python`; substitute the verified `python3` or `py -3` invocation as
needed. Claude hooks use executable-plus-args form: on Windows set `command` to
`py` and prepend `-3` to each args array, because `py -3` is not one executable
name. Codex and Cursor hook strings are shell-form and may use `py -3`. The
setup doctor checks Git and the running Python version without opening any
credential store.

## 2. Install and authenticate

Choose any graphical hosts needed for the project before installing terminal
commands:

1. **ChatGPT desktop app:** use the official
   [desktop quickstart](https://learn.chatgpt.com/docs/app), install ChatGPT for
   the operating system, and sign in. On Windows, Codex defaults to the native
   Windows agent environment, so keep that mode's repository on the Windows
   filesystem. For a repository inside WSL, choose WSL as the agent environment
   in Settings, restart ChatGPT, and then open the Linux path. The dedicated
   [Windows page](https://learn.chatgpt.com/docs/windows/windows-app) documents
   that switch as well as the Microsoft Store and `winget` lanes. Open the
   project folder and choose Codex after the environment is set. The Linux app
   is a preview with a narrower distribution and architecture matrix; verify
   the current supported combinations in the
   [ChatGPT Linux app guide](https://learn.chatgpt.com/docs/linux/linux-app)
   before choosing that lane.
2. **Claude Code Desktop:** install Claude from the official
   [desktop quickstart](https://code.claude.com/docs/en/desktop-quickstart),
   sign in, and open the Code tab. Choose **Local** for a native Windows or
   macOS filesystem. If the repository is inside WSL, choose its WSL
   distribution instead; opening that Linux path through Windows can degrade
   file watching and performance. Follow the dedicated
   [Desktop WSL guide](https://code.claude.com/docs/en/desktop-wsl).
   The desktop includes Claude Code; install the terminal CLI separately only
   when you need the `claude` command. The
   [platform comparison](https://code.claude.com/docs/en/platforms) distinguishes
   desktop, terminal, IDE, and web surfaces. Claude Desktop for Linux is a beta
   limited to the distributions and architectures in the current
   [Linux guide](https://code.claude.com/docs/en/desktop-linux); check that
   matrix rather than assuming every graphical Linux environment is supported.
3. **Cursor desktop:** install from the official
   [download page](https://cursor.com/download), open the app, sign in, and
   open the repository. Cursor documents desktop builds for macOS, Windows,
   and Linux in its [quickstart](https://cursor.com/docs/get-started/quickstart).
   The browser-led desktop installer is separate from the optional `agent` CLI
   below. For a repository in WSL, install Cursor's first-party WSL extension,
   enter the distribution, run `cd /path/to/project && cursor .`, and verify the
   status bar says `WSL: [DISTRIBUTION]`. Do not open the project from a Windows
   Explorer or Recent-items path rooted at `\\wsl.localhost\[DISTRIBUTION]`;
   that can create a Windows-local workspace whose agent tools run on the wrong
   host. The extension identifier is `anysphere.remote-wsl`; this follows
   [Cursor staff guidance](https://forum.cursor.com/t/agent-tools-fail-on-wsl-workspace-opened-via-wsl-localhost-path-resolves-to-c-home-glob-times-out-shell-intermittent-cursor-3-9-16/165471/5),
   which is support guidance rather than formal product documentation.

The vendor CLI quickstarts use one-line commands that download a script and
execute it immediately. For a public copy-paste kit, separate those two
decisions: save each response in a new temporary directory, inspect the
complete files, and run only the exact copies you reviewed. These bootstrap
scripts can download additional artifacts, so use them only on a network and
workstation where you trust that vendor. Remove the `Cursor` entry from the
maps and the final execution loop when you want desktop only and do not need
the optional Agent CLI.

Windows PowerShell (type the confirmation only after reviewing all three files):

```powershell
$ErrorActionPreference = 'Stop'
$InstallerRoot = Join-Path ([IO.Path]::GetTempPath()) (
  'coding-host-installers-' + [guid]::NewGuid().ToString('N')
)
New-Item -ItemType Directory -Path $InstallerRoot | Out-Null
$Installers = [ordered]@{
  Codex = @{
    Uri = 'https://chatgpt.com/codex/install.ps1'
    Path = Join-Path $InstallerRoot 'codex-install.ps1'
  }
  ClaudeCode = @{
    Uri = 'https://claude.ai/install.ps1'
    Path = Join-Path $InstallerRoot 'claude-install.ps1'
  }
  Cursor = @{
    Uri = 'https://cursor.com/install?win32=true'
    Path = Join-Path $InstallerRoot 'cursor-install.ps1'
  }
}
$PowerShellRunner = (Get-Process -Id $PID).Path
try {
  foreach ($Name in $Installers.Keys) {
    Invoke-WebRequest -Uri $Installers[$Name].Uri -OutFile $Installers[$Name].Path
    Write-Host "`n===== ${Name}: $($Installers[$Name].Uri) ====="
    Get-Content -Raw -LiteralPath $Installers[$Name].Path
  }
  $Approval = Read-Host 'Type RUN REVIEWED INSTALLERS to execute these saved files'
  if ($Approval -cne 'RUN REVIEWED INSTALLERS') {
    throw 'Install cancelled; no downloaded script was executed'
  }
  foreach ($Name in $Installers.Keys) {
    & $PowerShellRunner -NoProfile -ExecutionPolicy Bypass -File $Installers[$Name].Path
    if ($LASTEXITCODE -ne 0) { throw "$Name installer failed with exit $LASTEXITCODE" }
  }
} finally {
  if (Test-Path -LiteralPath $InstallerRoot -PathType Container) {
    Remove-Item -Recurse -Force -LiteralPath $InstallerRoot
  }
}
Write-Host 'Installers finished. Close this PowerShell window and open a new terminal before command, version, or authentication checks.'
```

Each installer ran in a child PowerShell. A child can update the persistent
user `PATH`, but it cannot update the already-running parent process. Stop at
the message above and use a newly opened terminal for every command below;
otherwise a correct installation can look missing.

macOS, WSL2, or a Linux environment supported by every selected CLI (type the
confirmation only after reviewing all three files):

This is not a promise that every POSIX-like distribution is supported. On
Alpine or another musl-based Linux, Anthropic currently requires `libgcc`,
`libstdc++`, and `ripgrep`; verify those packages and each other selected
vendor's current platform matrix before running the shared recipe.

```bash
set -eu
command -v curl >/dev/null || {
  printf '%s\n' 'curl is required to download the reviewed installer files.' >&2
  exit 1
}
command -v bash >/dev/null || {
  printf '%s\n' 'bash is required by the Claude and Cursor installer files.' >&2
  exit 1
}
installer_root="$(mktemp -d)"
cleanup_installers() { rm -rf -- "$installer_root"; }
trap cleanup_installers EXIT HUP INT TERM
curl -fsSL https://chatgpt.com/codex/install.sh -o "$installer_root/codex-install.sh"
curl -fsSL https://claude.ai/install.sh -o "$installer_root/claude-install.sh"
curl -fsSL https://cursor.com/install -o "$installer_root/cursor-install.sh"
for installer in "$installer_root"/*.sh; do
  printf '\n===== %s =====\n' "$installer"
  cat -- "$installer"
done
printf '\nType RUN REVIEWED INSTALLERS to execute these saved files: '
IFS= read -r approval
[ "$approval" = 'RUN REVIEWED INSTALLERS' ] || {
  printf '%s\n' 'Install cancelled; no downloaded script was executed' >&2
  exit 1
}
sh "$installer_root/codex-install.sh"
bash "$installer_root/claude-install.sh"
bash "$installer_root/cursor-install.sh"
```

The Cursor script above installs the optional Cursor CLI (`agent`), not the
desktop editor. Claude and Cursor may place their commands in `~/.local/bin`.
Open a new terminal after installation. If that shell still does not include
the shared install directory, enable it for the current session without
appending a duplicate profile entry, then check only the commands selected for
this workstation:

```bash
selected_commands='codex claude agent'  # remove agent for a desktop-only Cursor lane
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) [ -d "$HOME/.local/bin" ] && export PATH="$HOME/.local/bin:$PATH" ;;
esac
for command_name in $selected_commands; do
  command -v "$command_name" >/dev/null || {
    printf '%s\n' "$command_name is unavailable; verify its install, add ~/.local/bin to this shell's PATH once, and reopen the terminal." >&2
    exit 1
  }
done
```

Persist the same PATH entry once in the startup file used by your shell only
if it is not already present. The vendor installation references own this
location; this kit does not edit shell profiles automatically. If you omit the
optional Cursor installer, also remove `agent` from `selected_commands`.

Launch each installed terminal host interactively and use its supported sign-in
flow. Desktop-only users instead complete the app sign-in and folder selection
above:

```bash
codex
claude
agent  # optional Agent CLI
```

For Claude Code, make the repository root the primary working directory:

```bash
cd /path/to/project
claude
```

Open `/status` and verify the root `.claude/settings.json` is listed under
**Setting sources**. Claude reads shared project settings from the session's
primary working directory rather than walking ancestors for this file. `/cd`
can change which project settings load, so recheck the source list after using
it and before relying on root permission or hook policy.

Verify the actual installation:

```bash
codex --version
claude --version
agent --version  # optional Agent CLI
```

Then verify authentication rather than treating an installed but signed-out
binary as ready:

```bash
codex login status
claude auth status
agent status     # optional Agent CLI
```

These status commands can display an authentication method, account, email, or
workspace identifier. Read the result locally; do not paste raw status output
into a public issue, test receipt, or setup repository. A nonzero or signed-out
result means return to the interactive `codex login`, `claude auth login`, or
`agent login` flow before running a host-native smoke test.

Current Claude Code documents `claude doctor` as a read-only diagnostic for the
installation, settings, and environment; it does not start an interactive
session. MCP discovery and authentication are checked from an interactive
session with `/mcp`. Do not confuse either surface with this kit's later
`scripts/setup_doctor.py`, which only parses committed setup shape and never
starts an MCP server.

Do not pin this kit to versions observed on one workstation. A project that
requires a version should declare and test that requirement explicitly.

The public installer URLs currently redirect to vendor download hosts. The
source ledger records both the entrypoints and their redirect targets, and the
live checker refuses redirects outside its explicit public-host allowlist.
Anthropic also documents a native Windows CMD entrypoint at
`https://claude.ai/install.cmd`; the PowerShell sequence above is the maintained
Windows recipe in this kit.

Official references: [ChatGPT desktop app](https://learn.chatgpt.com/docs/app),
[ChatGPT desktop app for Windows](https://learn.chatgpt.com/docs/windows/windows-app),
[Codex CLI](https://learn.chatgpt.com/docs/codex/cli),
[Codex WSL](https://learn.chatgpt.com/docs/windows/wsl),
[Codex authentication](https://learn.chatgpt.com/docs/auth?surface=cli),
[Claude Code Desktop](https://code.claude.com/docs/en/desktop-quickstart),
[Claude Desktop for Linux](https://code.claude.com/docs/en/desktop-linux),
[Claude Code platforms](https://code.claude.com/docs/en/platforms),
[Claude Code installation](https://code.claude.com/docs/en/installation),
[Claude Code installation troubleshooting](https://code.claude.com/docs/en/troubleshoot-install),
[Claude Code CLI reference](https://code.claude.com/docs/en/cli-reference),
[Cursor desktop download](https://cursor.com/download),
[Cursor desktop quickstart](https://cursor.com/docs/get-started/quickstart),
[Cursor CLI installation](https://cursor.com/docs/cli/installation), and
[Cursor CLI parameters](https://cursor.com/docs/cli/reference/parameters).

## 3. Separate shared and host-native scope

| Purpose | Codex | Claude Code | Cursor |
|---|---|---|---|
| Personal instructions | `~/.codex/AGENTS.md` | `~/.claude/CLAUDE.md` | Synced **Customize → Rules → User Rules**, or local `~/.cursor/rules/*.mdc`; both guide Agent (Chat), not Tab or Inline Edit |
| Personal settings | `~/.codex/config.toml` | `~/.claude/settings.json` | Editor settings use the UI; Agent CLI uses `~/.cursor/cli-config.json` (Windows: `$env:USERPROFILE\.cursor\cli-config.json`) |
| Shared project instructions | Root and nested `AGENTS.md` | `.claude/CLAUDE.md` contains only `@../AGENTS.md`; Claude-only rules use `.claude/rules/` | Root and nested `AGENTS.md`; no root `CLAUDE.md` duplicate |
| Project skills | `.agents/skills` | `.claude/skills` checked copy | `.agents/skills` or `.cursor/skills` |
| Project subagents | `.codex/agents/*.toml` | `.claude/agents/*.md` | `.cursor/agents/*.md` |
| Project MCP | `.codex/config.toml` | `.mcp.json` | `.cursor/mcp.json` |
| Project hooks | `.codex/hooks.json` | `hooks` in `.claude/settings.json` | `.cursor/hooks.json` |
| Project/session permissions | policy keys in `.codex/config.toml` | shared `permissions` in `.claude/settings.json` | `.cursor/permissions.json` for desktop/local Agent; `.cursor/cli.json` for Agent CLI |
| Agent sandbox | Codex-owned sandbox policy | Claude permission and sandbox controls | `.cursor/sandbox.json` for desktop/local Agent; separate CLI policy for Agent CLI |
| Private override | keep outside version control | `.claude/settings.local.json` or `CLAUDE.local.md` | user-owned settings outside the shared template |

Copy and edit; never overwrite a user's existing configuration blindly:

- `templates/global/WORKING_AGREEMENTS.md` is an optional personal contract.
  Install it as a file for Codex or Claude Code, or copy reviewed clauses into
  Cursor User Rules in the UI. For a machine-local, non-synced Cursor rule,
  copy the complete, frontmatter-bearing
  `templates/cursor/working-agreements.mdc` to
  `~/.cursor/rules/working-agreements.mdc` (Windows:
  `%USERPROFILE%\.cursor\rules\working-agreements.mdc`) without overwriting an
  existing rule. Plain `.md` files in this directory are ignored. UI User
  Rules sync with the signed-in Cursor account; the `.mdc` file remains on that
  machine. Both apply to Agent (Chat), not Cursor Tab or Inline Edit.
- `templates/project/AGENTS.md` owns shared project behavior.
- `templates/project/.claude/CLAUDE.md` contains only the shared import.
  `templates/project/.claude/rules/claude-code.md` owns Claude-only guidance.
  The project template intentionally omits root `CLAUDE.md` so Cursor does not
  load `AGENTS.md` twice.
- `templates/codex/`, `templates/claude/`, and `templates/cursor/` contain
  host adapters, not interchangeable settings.

Two optional local templates are deliberately not part of fresh-project
materialization:

- compare `templates/codex/config.toml` with `~/.codex/config.toml` and merge
  reviewed keys by hand; never overwrite an existing personal config or copy
  credential values into it;
- copy `templates/claude/settings.local.json.example` to the target project's
  `.claude/settings.local.json` only when a private project override is needed.
  The target `.gitignore` excludes that destination. Claude's separate
  `CLAUDE.local.md` private instruction file is also excluded and is never
  materialized from this kit.
- compare `templates/cursor/cli-config.json.example` with the existing global
  Agent CLI config and merge reviewed keys; do not overwrite CLI-managed or
  personal settings. For repository-specific Agent CLI permissions only, copy
  `templates/cursor/cli.json.example` to `.cursor/cli.json` and replace the
  empty allowlist deliberately. Deny rules take precedence. These files govern
  the `agent` CLI, not the Cursor desktop editor's settings UI.
- for Cursor's desktop/local Agent, review
  `templates/cursor/permissions.json.example` before copying it to
  `.cursor/permissions.json`, and review `templates/cursor/sandbox.json.example`
  before copying it to `.cursor/sandbox.json`. User and project permission
  lists combine and apply only with a
  [Run Mode](https://cursor.com/docs/agent/security/run-modes) enabled. Project sandbox values
  have higher priority, but extra paths are unioned and restrictive network or
  boolean values win; team and built-in restrictions remain stronger. Neither
  permission rules nor the sandbox are a security boundary; keep secrets
  outside the workspace and use OS isolation for hostile code.

All optional policy examples start without enabled external execution. Keep secret values in
environment variables or a secret manager, and re-run the setup doctor after
merging.

Official references: [Codex configuration](https://learn.chatgpt.com/docs/config-file/config-basic),
[Codex `AGENTS.md`](https://learn.chatgpt.com/docs/agent-configuration/agents-md),
[Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents),
[Codex hooks](https://learn.chatgpt.com/docs/hooks),
[Claude Code memory](https://code.claude.com/docs/en/memory),
[Claude Code subagents](https://code.claude.com/docs/en/sub-agents),
[Claude Code tools](https://code.claude.com/docs/en/tools-reference), and
[Cursor rules](https://cursor.com/docs/rules),
[Cursor personal-rule locations](https://cursor.com/help/customization/rules),
[Cursor desktop/local Agent permissions](https://cursor.com/docs/reference/permissions),
[Cursor sandbox configuration](https://cursor.com/docs/reference/sandbox),
[Cursor CLI configuration](https://cursor.com/docs/cli/reference/configuration), and
[Cursor CLI permissions](https://cursor.com/docs/cli/reference/permissions).

## 4. Bootstrap a repository

Create only the surfaces the project needs:

```text
project/
├── .gitignore
├── AGENTS.md
├── AGENT_INVARIANTS.md
├── .agents/
│   └── skills/
├── .codex/
│   ├── config.toml
│   └── agents/
├── .claude/
│   ├── CLAUDE.md
│   ├── settings.json
│   ├── agents/
│   ├── rules/
│   └── skills/
├── .cursor/
│   ├── mcp.json
│   └── agents/
└── .mcp.json
```

Replace every `[BRACKETED_FIELD]`, keep commands runnable from the project
root, and describe the real verification command. Nested instruction files
should add only policy owned by that subtree.

Fresh and existing Git projects use the same bounded placement map in
`scripts/setup_project.py`. Run it from this kit, naming the exact project root.
The default only reports `MISSING`, `IDENTICAL`, `CONFLICT`, or `BLOCKED` for
known kit destinations; it does not scan unrelated project files or create
Python caches. A fresh `git init` without a first commit is supported.

### Review before adding files

Use an existing physical project path, or create a fresh directory and run
`git init` there first. Keep the plan and progress receipt in a separate
existing directory outside both the kit and project. The following commands
are identical on Windows, macOS, Linux, and WSL; use your Python 3.11+ command
(`python`, `python3`, or `py -3`) and real paths:

```text
python /path/to/coding-agent-setup/scripts/setup_project.py --target /path/to/project
python /path/to/coding-agent-setup/scripts/setup_project.py plan --target /path/to/project --out /path/to/review/setup-plan.json
python /path/to/coding-agent-setup/scripts/setup_project.py apply --target /path/to/project --plan /path/to/review/setup-plan.json --include AGENT_INVARIANTS.md --receipt /path/to/review/setup-progress.jsonl
```

Read the plan before applying. Repeat `--include` for each reviewed missing
file. For a fresh project, or when **every missing destination** has been
reviewed, replace the include arguments with `--all-missing`. The same map
supplies native adapters, operational helpers, learning templates, and the
unconfigured target harness. Hook examples are not copied; MCP examples remain
disabled. No host session, provider, global setting, or project command starts.

Existing differing instructions, ignore rules and configurations require a
deliberate manual merge. They are never overwritten or automatically merged.
Claude skill mirrors are eligible only when the complete corresponding
canonical skill tree matches, including extra and missing files; reviewed
missing canonical additions can complete that tree in the same application.

The plan binds the kit bytes and Git target identity. A changed template,
branch or HEAD requires a fresh plan. An identical repeat is a no-op; a racing
writer is preserved. Receipt files are exclusively created and JSONL progress
is flushed after each operation. On a partial I/O or receipt failure, stop and
inspect the durable receipt prefix plus stdout's failure report: already
created or partial files remain. There is no automatic rollback. Re-plan with
a new external receipt name after resolving the failure. Incomplete or
conflicting setup reports unresolved items; even complete copying reports
`UNCONFIGURED`, never application readiness.

File creation uses directory-relative exclusive operations and rejects linked
components. Use a local filesystem with stable parent directories under your
control. This is not protection against an actor relocating an already opened
POSIX directory or editing a file after creation, nor an atomic crash recovery
transaction. Unsupported filesystem operations fail rather than fall back to
an overwrite-capable copy.

### Check a fresh copied scaffold

After reviewing the copied files, run the structural doctor and generic
mutation proof. For an existing project, review its existing scripts before
executing them; copying selected files did not validate those scripts.

```bash
set -eu
PYTHON=${PYTHON:-python3}
PROJECT_ROOT="/path/to/project"
"$PYTHON" "$PROJECT_ROOT/scripts/setup_doctor.py" --project-root "$PROJECT_ROOT" --skip-binaries
if "$PYTHON" "$PROJECT_ROOT/scripts/agent_preflight.py" --root "$PROJECT_ROOT" --config templates/harness/preflight.json --json; then
  echo "Expected NO_GATE for an unconfigured fresh scaffold" >&2
  exit 1
else
  test "$?" -eq 2
fi
"$PYTHON" "$PROJECT_ROOT/scripts/prove_preflight_mutations.py"
```

Windows PowerShell:

```powershell
$ErrorActionPreference = 'Stop'
$PythonCommand = Get-Command python -ErrorAction SilentlyContinue
$PythonPrefix = @()
if ($null -eq $PythonCommand) {
  $PythonCommand = Get-Command py -ErrorAction Stop
  $PythonPrefix = @('-3')
}
$PythonExe = $PythonCommand.Source
$ProjectRoot = (Resolve-Path 'D:\path\to\project').Path
& $PythonExe @PythonPrefix -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or newer is required' }
& $PythonExe @PythonPrefix (Join-Path $ProjectRoot 'scripts/setup_doctor.py') --project-root $ProjectRoot --skip-binaries
if ($LASTEXITCODE -ne 0) { throw 'Setup diagnosis failed' }
& $PythonExe @PythonPrefix (Join-Path $ProjectRoot 'scripts/sync_skills.py') check --project-root $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw 'Skill verification failed' }
& $PythonExe @PythonPrefix (Join-Path $ProjectRoot 'scripts/agent_preflight.py') --root $ProjectRoot --config templates/harness/preflight.json --json
if ($LASTEXITCODE -ne 2) { throw 'Expected target preflight to report NO_GATE before configuration' }
& $PythonExe @PythonPrefix (Join-Path $ProjectRoot 'scripts/prove_preflight_mutations.py')
if ($LASTEXITCODE -ne 0) { throw 'Preflight mutation proof failed' }
```

The copied target intentionally exits `2` with `NO_GATE`. That is success for
materialization, not promotion: replace the placeholder with target-owned
paths, commands, visual disposition, and a fresh review receipt before expecting
exit `0`. The mutation runner proves the generic harness fails closed; it does
not certify the new project's implementation.

The project copy also installs coordination templates; fill only the ones the
team actually uses:

| Target path | Job |
|---|---|
| `HANDOFF.md` | Current owner, state, proof, risk, and next action for another host |
| `ARTIFACTS.md` | Replayable proof registry |
| `DECISIONS.md` | Append-only decisions and `SUPERSEDES` corrections |
| `COMMUNICATION.md` | Project-owned channel and receipt conventions |
| `context-exchange/` | One bounded, untrusted note per active host |
| `.planning/placement.md` | One evidence-backed decision about the owning seam |
| `.planning/generation-matrix.json` | Persona, duration, and failure-state scenario coverage |

## 5. Install the canonical skills

Copy `templates/project/.agents/skills` into the project's `.agents/skills`.
Codex and Cursor discover that tree directly. Generate Claude Code's project
copy and verify its digest:

```bash
python scripts/sync_skills.py sync --project-root /path/to/project
python scripts/sync_skills.py check --project-root /path/to/project
```

Run `sync` after changing the canonical tree. A divergent Claude copy is
preserved by default; inspect it, then use `--force` only when replacement is
the intended resolution. A host-only extra directory is reported and preserved
until an owner migrates or removes it explicitly, while `check` fails so the
tree cannot be called synchronized. Whole-directory symlinks are not used
because they are unreliable across native Windows and restricted filesystems.

The portable layout follows the public
[Agent Skills specification](https://github.com/agentskills/agentskills).
Host discovery details remain defined by [Codex skills](https://learn.chatgpt.com/docs/build-skills),
[Claude Code skills](https://code.claude.com/docs/en/skills), and
[Cursor skills](https://cursor.com/docs/skills).

## 6. Add native agents, MCP, and hooks

Copy only the capabilities needed by the current workflow:

- Codex agent templates go to `.codex/agents`; its project MCP belongs in
  `.codex/config.toml`. The distributed server entry has `enabled = false`.
- Claude Code agent templates go to `.claude/agents`; project MCP belongs in
  `.mcp.json`. The materialized file is empty; merge the reviewed server from
  `templates/project/.mcp.json.example` only when needed.
- Cursor agent templates go to `.cursor/agents`; project MCP belongs in
  `.cursor/mcp.json`. The materialized file is empty; merge the reviewed server
  from `templates/cursor/mcp.json.example` only when needed.

The fresh-project copy installs `templates/project/.gitignore`, which excludes
`.agent-local/`, the generated `.claude/skills/` mirror and
`.claude/worktrees/` checkouts, Claude's private local settings and instruction
file, and `.env` variants while retaining `.env.example`. When migrating an
existing project, merge those rules into its ignore file before adding local
values, enabling continuity hooks, starting a generated worktree, or
regenerating skill mirrors. See Anthropic's [worktree](https://code.claude.com/docs/en/worktrees)
and [memory](https://code.claude.com/docs/en/memory) guidance.

The hook files ending in `.example` and the Claude hook snippet are inert in
this repository. Complete `templates/harness/hook-admission.json`, review the
event names and exit semantics for the chosen host, then explicitly copy or
merge the example. For Codex, open `/hooks` after activation, compare the
discovered command hash with the reviewed file, and approve it; command changes
require review again and untrusted non-managed hooks are skipped. Cursor project
hooks run only in trusted workspaces and fail open on process errors by default,
so an exit-1 reminder is not an enforcement boundary. See
[Skills, plugins, hooks, and subagents](skills-plugins-hooks.md).

## 7. Diagnose the resulting project

```bash
python scripts/setup_doctor.py --project-root /path/to/project
```

The bootstrap uses `--skip-binaries` so a valid desktop-only setup does not
fail because an optional terminal command is absent. The doctor checks all
three CLI commands by default, required discovery paths,
the `@../AGENTS.md` import, and parsable JSON/TOML. It reports only presence and
validity. It parses the committed config files but does not open host
credential stores or print config values. Optional project Cursor CLI,
permission, and sandbox files are parsed when present. It does not prove MCP
connectivity or that a policy has the intended runtime effect.
Use `--skip-binaries` when validating a prepared fixture. For Cursor desktop
without the optional Agent CLI, verify Codex and Claude binaries separately,
then inspect only Cursor's repository adapters:

```bash
python scripts/setup_doctor.py --project-root /path/to/project --hosts codex,claude
python scripts/setup_doctor.py --project-root /path/to/project --hosts cursor --skip-binaries
```

For Claude Code Desktop without the separate `claude` terminal command, verify
the other installed terminal hosts separately, then inspect Claude's project
adapters without a binary assertion:

```bash
python scripts/setup_doctor.py --project-root /path/to/project --hosts codex
python scripts/setup_doctor.py --project-root /path/to/project --hosts claude --skip-binaries
```

Then open that same folder in Claude Desktop, start a local Code session, open
`/mcp`, and confirm the resolved server list contains no unexpected personal or
Desktop override. Ask the session to cite one exact rule from the imported
`AGENTS.md`; this observes app-side discovery that the structural doctor cannot.

For the ChatGPT desktop app without a separate `codex` terminal command, parse
only Codex's repository adapters, then observe the app-side contract:

```bash
python scripts/setup_doctor.py --project-root /path/to/project --hosts codex --skip-binaries
```

Open the same folder in the app using the intended Local or WSL environment,
open `/mcp`, confirm no unexpected user server overrides the reviewed project
definition, and ask the session to cite one exact rule from `AGENTS.md`.

## 8. Run the fail-closed preflight

```bash
python scripts/agent_preflight.py --config templates/harness/preflight.json
python scripts/prove_preflight_mutations.py
```

Exit `0` means every configured layer passed, `1` means a known violation was
observed, and `2` means `NO_GATE`. Missing proof never becomes a pass. See
[Preflight and continuity](preflight-and-continuity.md).

## 9. Migrate an existing split setup

1. Inventory instructions, settings, MCP, hooks, skills, plugins, agents, and
   ignored local state.
2. Exclude credentials, sessions, caches, databases, generated worktrees,
   private paths, and machine registries.
3. Merge shared team rules into `AGENTS.md`.
4. Keep `.claude/CLAUDE.md` as only the real `@../AGENTS.md` import; omit root
   `CLAUDE.md` and put Claude-only guidance in `.claude/rules/`.
5. Move reusable skills to `.agents/skills`, sync the Claude copy, and remove
   duplicate hand-edited sources only after their digests match.
6. Keep settings, MCP, hooks, and agent definitions host-native.
7. Move secret values to environment variables or a secret manager.
8. Run the doctor, preflight, offline validator, and scenario suite.

## 10. Definition of done

A newcomer can clone the repository, identify every destination, reproduce the
Claude skill copy, parse every template, run all offline checks without
credentials, observe a deliberate preflight mutation fail, and understand
what must be reviewed before enabling a network tool or executable hook.
