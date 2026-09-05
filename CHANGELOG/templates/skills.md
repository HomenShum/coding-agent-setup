# Skill template changelog

## 2026-09-04 — Establish one portable canonical skill tree

- Commit: uncommitted local change; publication is blocked by the current
  reachable-history privacy gate until a clean fresh history or separately
  authorized rewrite is reviewed.
- User outcome: Codex and Cursor can consume the canonical project skills
  directly while Claude Code receives a digest-checked copy with visible drift
  and removal behavior.
- Source: Agent Skills plus current host-specific skill documentation.
- Files: `templates/project/.agents/skills/`, `sources/skills.json`, and
  `scripts/sync_skills.py`.
- Verification: manifest parity, fresh copy, idempotent copy, divergence
  refusal, explicit replacement, safe removal, extra-target detection,
  nested-symlink rejection, bounded skill/file/directory discovery, sixteen
  parsed execution contracts, and valid/invalid receipt scenarios.
- Repair: make every advertised receipt-validator invocation complete and
  parameterized with explicit contract and receipt arguments, then execute the
  advertised argv in a scenario.
- Caveats: project-specific skills still require their own source and license
  review.
