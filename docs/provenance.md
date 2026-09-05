# Provenance and exclusions

This repository is a clean public synthesis. Its current three-host contract
was reviewed on 2026-09-04 against four evidence classes:

1. current OpenAI documentation for Codex;
2. current Anthropic documentation for Claude Code;
3. current Cursor documentation;
4. public repositories listed in the external-project ledger when they
   directly informed a workflow, format, runtime, or attribution decision.

## What was generalized

- one canonical `AGENTS.md`, an import-only `.claude/CLAUDE.md`, and separate
  Claude-only `.claude/rules/` guidance, with no duplicate root compatibility
  file for Cursor;
- one canonical `.agents/skills` tree, consumed directly by Codex and Cursor
  and copied with digest verification for Claude Code;
- native MCP, hook, and subagent adapters for each host;
- planner-worker-judge routing with bounded states and receipts;
- deterministic preflight, mutation proof, handoff continuity, and claim
  reconciliation;
- security and attribution checks that run without vendor credentials.

All text, templates, and validation code in this repository were written as
generic examples. Sanitized direct dependency metadata, container and CI
declarations, extension manifests, and attribution notes from a historical
project were inspected to construct the external-source ledger. No historical
application code, fixture, project prose, receipt, or session transcript was
copied into the publication.

The clean-tree validator inventories exactly the tracked plus untracked,
non-ignored files reported by Git. When no exact repository root is available,
it uses a closed fallback ignore policy that excludes only named runtime,
credential, generated-worktree, and version-control sentinels. It never follows
links or junctions and never treats a partial inventory as a pass.

The separate reachable-history gate does not rewrite history. It scans every
ref-reachable object and path in a full clone against the digest-only marker
policy. A public zero-marker claim therefore requires a reviewed fresh history
or a separately authorized history rewrite, followed by the history gate,
inspection of the resulting commit graph, and anonymous remote content proof.
The gate strips inherited Git environment routing, disables replacement
objects, and rejects an effective legacy graft file so a process-local history
overlay cannot manufacture the clean graph being inspected.

## What was deliberately excluded

- live or expired secrets and credential-bearing command lines;
- authentication stores, chats, memories, local databases, caches, browser
  profiles, generated worktrees, and ignored runtime state;
- personal paths, private repository URLs, deployment identifiers, account
  metadata, and private naming;
- application implementations, fixtures, evidence captures, and proprietary
  operating details;
- stale commands or configuration paths superseded by current primary docs;
- enabled executable hooks, enabled MCP servers, or unreviewed plugins;
- a fabricated repository attribution where only vendor documentation or a
  package listing could be established.

The optional pre-initialized Graphite status in `scripts/check_branch_stack.py`
is one such vendor-only relationship. It is skipped in fresh repositories
because the vendor command can create Git-local metadata during setup. Its
command is cited to the
[Graphite CLI reference](https://graphite.com/docs/command-reference), while
the repository ledger deliberately makes no source-code or license claim for
the CLI because no canonical public implementation repository was established.

## Attribution method

`sources/external-projects.json` is the machine-readable repository ledger and
`docs/external-projects.md` is its human-readable view.
`sources/official-docs.json` records mutable vendor documentation separately.
`sources/historical-action-uses.json` preserves only the repository and
revision of each sanitized historical GitHub Action declaration. The validator
requires every action source and the bounded historical baseline to remain in
the external ledger, so a digest update cannot silently erase known prior use.
The ledger's methodology separates current-kit direct tools and authorities
from the bounded historical-project corpus. An external project entry states
its relationship instead of implying that a historical dependency is bundled,
installed, or recommended by this kit.

The portable skill format is attributed to
[agentskills/agentskills](https://github.com/agentskills/agentskills). The
ledger records Apache-2.0 for its code and specification and CC-BY-4.0 for its
documentation. No unrelated repository is listed as the implementation source
for a vendor-only workflow.

License labels are discovery aids, not legal advice. A public repository is
not automatically open source, and this repository's MIT license applies only
to original material here.
