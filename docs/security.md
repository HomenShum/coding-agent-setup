# Security and publication checklist

The main risk is not a parse error. It is a working local setup quietly
containing credentials, sessions, private paths, or executable trust decisions
that become public when copied.

## Threat model

| Asset | Common failure | Control |
|---|---|---|
| API and OAuth credentials | Token committed in config, URL, shell argument, or log | Environment-variable name only; secret manager; pre-push scan; rotate on exposure |
| Private source | Worktree or home-directory content copied into the kit | Explicit allowlist and content/filename scan |
| Agent sessions | Transcript, cache, database, or memory copied as setup | Exclude runtime state entirely |
| Workstation identity | Absolute paths, usernames, tenant names, or hostnames | Portable placeholders and path scan |
| Tool authority | Broad MCP, hook, or subagent silently enabled | Narrow scope, explicit review, disabled examples |
| Generated skill copy | Claude mirror diverges from the canonical skill | Digest check and refusal to overwrite by default |
| Supply chain | Unpinned or unattributed extension changes | Canonical source, revision, license, and access-date ledger |
| False completion | CLI says success but the promised artifact is missing | Fail-closed preflight and direct observation |

## Before enabling a host adapter

- Parse the matching host-native format; do not translate settings by eye.
- Review MCP commands, arguments, environment-variable names, timeouts, and
  remote data boundaries.
- Keep reusable subagents bounded and avoid unnecessary model pins.
- Treat every hook as executable code. Review its input, exit semantics,
  filesystem/network effects, concurrency, and rollback.
- Complete `templates/harness/hook-admission.json` before copying any hook
  sample to an active path.
- Run `scripts/setup_doctor.py` without opening host credential stores or
  printing values from the committed config files it parses.

## Before the first commit

- Build the repository from an explicit file allowlist.
- Never recursively copy personal `.codex`, `.claude`, `.cursor`, browser,
  worktree, cache, database, or environment directories.
- Search both content and filenames for secret patterns, personal absolute
  paths, and private-source markers. The validator permits only explicit
  documentation placeholders such as `C:\path\...` and
  `\\server\share\...`; replace every concrete drive-root, home-directory,
  or UNC location before publication.
- Ignore `.agent-local/`, `.claude/worktrees/`, `.claude/settings.local.json`,
  and `CLAUDE.local.md`; they are runtime or private workstation inputs, not
  publication inputs. Anthropic documents the generated worktree and private
  memory paths in its [worktree](https://code.claude.com/docs/en/worktrees) and
  [memory](https://code.claude.com/docs/en/memory) guidance.
- Keep the repository text-only: every regular publication file must be UTF-8,
  no larger than 1 MiB, and within the validator's 2,000-file and 32 MiB total
  read caps.
- Parse every JSON, TOML, JSON example, hook snippet, and skill metadata file.
- Resolve relative Markdown links.
- Ensure every deliberately cited GitHub repository appears in both attribution
  ledgers.
- Review Git author identity and the exact staged diff.

Run:

```bash
python scripts/sync_skills.py check --project-root /path/to/project
python scripts/agent_preflight.py --config templates/harness/preflight.json
python scripts/prove_preflight_mutations.py
python scripts/validate_repo.py
python -m unittest discover -s tests -v
git diff --check
```

The offline validator certifies the current publication tree. The separate
`scripts/check_private_history.py` gate checks every ref-reachable commit, tag,
blob, and repository path with explicit ref, commit, object, blob, byte,
output, and aggregate-time caps; its diagnostics expose only redacted object
identifiers. Run it from a full clone, never a shallow checkout. If a
previously published history contains a blocked private-source marker,
zero-marker publication requires either a reviewed fresh history or a
separately authorized history rewrite, followed by this history gate and an
anonymous remote-content check.

Git can present a process-local history through environment variables,
replacement refs, or the legacy `info/grafts` file. The history, preflight, and
branch-stack tools strip inherited `GIT_*` values, force replacement objects
off, and reject an effective graft file before trusting ancestry. Do not bypass
that failure; remove the local rewrite mechanism and rerun from the intended
full clone.

## Before every push

- Inspect `git status`, staged diff, and exact files that will leave the
  machine.
- Confirm examples contain variable names, never values.
- Confirm Claude shared settings and the Cursor CLI permission examples still
  deny nested project environment and secret paths; a root-only pattern is
  insufficient for a monorepo. Confirm Cursor's desktop Auto-review block
  instructions still surface secret access for approval, and its sandbox
  example still adds no filesystem paths and defaults network access to deny.
  These controls do not replace OS isolation for hostile commands.
- Treat MCP listings, terminal output, hook state, and screenshots as
  sensitive until sanitized.
- Confirm hook examples are still inert unless their activation is an explicit
  reviewed change.
- Re-run offline checks on every supported CI operating system.
- Run `python scripts/validate_repo.py --check-external` when citations change
  or on a scheduled trusted runner.

## After publishing

Fetch raw public content rather than trusting a push exit code. Verify the
default branch contains the expected README, security policy, machine-readable
source ledgers, and validator. Confirm visibility through the hosting API. A
successful transport command does not prove what an anonymous reader sees.

## If a credential is exposed

1. Revoke or rotate it immediately at its issuer.
2. Check access logs and reduce the replacement credential's scope.
3. Remove it from all reachable commits and artifacts through the host's
   documented incident process.
4. Invalidate caches and rebuild affected artifacts.
5. Record the incident without reproducing the secret.

Deleting the latest line is not containment: earlier commits, logs, CI output,
screenshots, and indexing systems may retain it.
