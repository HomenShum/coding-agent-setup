# Skills, plugins, hooks, and subagents

These extensions solve different human problems. Keeping their boundaries
separate prevents duplicated instructions and surprising execution.

| Extension | Human situation | Technical boundary |
|---|---|---|
| Skill | A repeatable job needs a reusable playbook. | On-demand instructions and supporting resources. |
| Subagent | One bounded lane needs separate context or tools. | Host-native role definition and lifecycle. |
| Plugin | A maintained package distributes extensions. | Vendor-specific manifest and supply-chain boundary. |
| Hook | A lifecycle event must trigger deterministic code. | Executable automation with the user's authority. |
| MCP server | The agent must call another process or service. | Protocol, authentication, data, and action boundary. |

## One canonical skill tree

The reviewed project source is `.agents/skills/<name>/SKILL.md`:

- Codex discovers `.agents/skills`;
- Cursor discovers `.agents/skills` or `.cursor/skills`;
- Claude Code discovers `.claude/skills`.

Codex and Cursor therefore use the canonical tree directly. Claude Code gets
a deterministic project copy:

```bash
python scripts/sync_skills.py sync --project-root /path/to/project
python scripts/sync_skills.py check --project-root /path/to/project
```

The tool bounds skill and file counts, rejects symlinks, verifies content
digests, and preserves divergent targets unless `--force` is explicit. `check`
also fails on a host-only extra skill. `sync` and `remove` report that extra as
`preserved-extra:<name>` and never delete it implicitly; migrate or remove it
only after an owner decides which source is canonical. Use `remove` only when
the generated copy still matches the canonical source.

The layout follows the public
[Agent Skills repository](https://github.com/agentskills/agentskills). Its
code and specification are Apache-2.0; its documentation is CC-BY-4.0. The
host discovery paths remain governed by [Codex skills](https://learn.chatgpt.com/docs/build-skills),
[Claude Code skills](https://code.claude.com/docs/en/skills), and
[Cursor skills](https://cursor.com/docs/skills).

The reusable examples are indexed in `sources/skills.json`. Each skill keeps a
short `SKILL.md`, `agents/openai.yaml` discovery metadata, and a machine-readable
`references/contract.json`. The contract names the trigger, required input
references, refusal boundary, canonical receipt fields, and shared validation
command. Validate a concrete receipt with:

```bash
python scripts/validate_skill_receipt.py \
  --contract .agents/skills/<name>/references/contract.json \
  --receipt /path/to/receipt.json
```

A contract's `verification.argv` is a complete parameterized invocation. Replace
`{python}` with the verified Python 3.11+ executable, `{skill_dir}` with the
skill directory, and `{receipt}` with the concrete receipt path; do not drop
the `--contract` or `--receipt` arguments.

A parsed receipt proves only that the required references and evidence fields
exist. The skill's named scenario proof must still be replayed; prose alone is
not a gate.

To author another portable skill, copy `templates/skill/` into
`.agents/skills/<name>/`, then update the folder name, frontmatter name and
description, `$name` in `agents/openai.yaml`, and the trigger, inputs, refusal,
and skill name in `references/contract.json`. Run a concrete receipt through
the shared validator before synchronizing the Claude mirror.

## Use native subagents

The same worker role has three adapters:

| Host | Project path | Format |
|---|---|---|
| Codex | `.codex/agents/*.toml` | TOML |
| Claude Code | `.claude/agents/*.md` | Markdown with frontmatter |
| Cursor | `.cursor/agents/*.md` | Markdown with frontmatter |

Templates under `templates/{codex,claude,cursor}/agents` define a
filesystem-read-only evidence worker and a separate adversarial judge. Keep a reusable worker on
the parent's current model unless the project has tested a supported model
contract. Bound the task, tools, transitions, and write scope. A worker report
is a claim; the planner must inspect the referenced evidence.

The Claude Code read-only templates allow only `Read`, `Glob`, and `Grep`.
They name commands for the parent to replay rather than receiving Bash or
PowerShell access. This follows Claude Code's documented tool allowlist; do not
reintroduce shell tools while calling the role read-only. Codex and Cursor use
their own filesystem-write restriction, but neither setting alone removes every
inherited tool. Codex custom agents inherit omitted `mcp_servers` and a live
parent permission override can supersede their sandbox default. Cursor
subagents inherit every parent MCP tool even when `readonly: true` blocks file
edits and state-changing shell commands. Before delegating a proof role, inspect
the effective parent tool list, remove or disable write-capable and external MCP
tools, and record that review in the delegation receipt. Otherwise do not invoke
those tools and keep the result `UNVERIFIED`.

Official references: [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents),
[Claude Code subagents](https://code.claude.com/docs/en/sub-agents), and
[Cursor subagents](https://cursor.com/docs/subagents).

## Plugins are supply-chain inputs

Before installing a plugin:

1. verify its publisher and canonical repository;
2. inspect its manifest, permissions, MCP servers, hooks, and update behavior;
3. record the reviewed release or commit when possible;
4. test it in a disposable repository;
5. document disable, uninstall, and local-state cleanup.

A marketplace listing is not a blanket trust signal. Each deliberately used
repository belongs in the [external-project ledger](external-projects.md), and
each bundled component retains its own license.

## Hooks are code, not prose

Codex and Claude Code use PascalCase lifecycle event names; Cursor's project
hooks use camelCase names. Their configuration and exit semantics remain
host-specific. Current references are [Codex hooks](https://learn.chatgpt.com/docs/hooks),
[Claude Code hooks](https://code.claude.com/docs/en/hooks), and
[Cursor hooks](https://cursor.com/docs/hooks).

This repository activates no hook. Samples are deliberately named:

- `templates/codex/hooks.json.example`;
- `templates/claude/hooks.snippet.json`;
- `templates/cursor/hooks.json.example`.

Claude's command hook separates one executable from its arguments. If Windows
uses the Python launcher, change `command` to `py` and prepend `-3` to each
`args` array; never put `py -3` in `command`. Codex and Cursor samples use a
shell command string instead.

Claude's `SessionStart` matcher includes both current `fork` and legacy
`resume` sources so `/fork` or `/branch` sessions receive continuity context
across supported client generations.

Codex's `commandWindows` samples use a quote-free PowerShell command launched by
the native `cmd.exe` hook runner. PowerShell resolves the Git root into a value
and changes directory with `-LiteralPath`, so spaces and shell metacharacters in
the path are never reparsed as command text. The form also avoids the current
Windows launcher defect for hook strings containing embedded double quotes. A
scenario launches the command from a nested directory in a repository whose
path contains spaces and `&`; native Codex discovery remains `UNVERIFIED` until
the operator performs the smoke below. Activate the inert example only after
`/hooks` shows the reviewed command and a real start/compact/stop smoke succeeds.
See the current
[Codex hook guidance](https://learn.chatgpt.com/docs/hooks) and tracked
[Windows hook issue](https://github.com/openai/codex/issues/38168).

Before copying or merging one, complete
`templates/harness/hook-admission.json` and record:

- trigger, matcher, and exact input schema;
- command, working directory, and untrusted fields;
- timeout, exit-code meaning, and output cap;
- filesystem, network, and process side effects;
- rollback and state-cleanup steps;
- adversarial filename, malformed input, concurrent event, burst, and sustained
  scenarios.

After activating a Codex hook, open `/hooks`, review its discovered source and
command hash, and approve it only if they match the admitted example. Codex
skips untrusted non-managed hooks; any command change creates a new hash that
must be reviewed again. Never treat “the file exists” as proof it executed.

Cursor runs project hooks only in a trusted workspace, and hook-process errors
fail open by default. Treat an exit-1 continuity result as a visible diagnostic,
not an enforced stop; keep the independent preflight as the promotion gate.
The sample keys state by Cursor's stable conversation identifier and suppresses
follow-up turns after failed or aborted runs. Cursor Cloud Agents do not run
`sessionStart` or `sessionEnd`; this sample's continuity start event is for
local desktop, Agent CLI, and self-hosted use. Cloud workflows must run the
independent preflight explicitly instead of claiming that start-hook proof.

The example `scripts/self_review_hook.py` stores only bounded hashed state
under `.agent-local/`; it does not store prompts, transcripts, credentials, or
absolute workstation paths. Its digest is complete within declared entry,
file, and byte caps and errors instead of returning a partial sample. Hooks can
remind an agent to review work, but only the preflight and independent judge can
certify the named proof.

## Promotion proof

A reusable extension is ready only when a realistic user can invoke it from
every intended host, refusal and degraded paths are visible, sources and
licenses are recorded, no secret appears in configuration, and removal returns
the project to its previous behavior. This kit's offline tests do not certify
that host-native invocation; record that manual smoke proof in the target
project's artifact registry.
