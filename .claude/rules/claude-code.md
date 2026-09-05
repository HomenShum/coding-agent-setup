# Claude Code adapter

Treat the project-root `AGENTS.md` as canonical. Keep shared Claude settings in
`.claude/settings.json`, private overrides in `.claude/settings.local.json`, and
team MCP definitions in `.mcp.json`. Generate `.claude/skills` only from the
canonical `.agents/skills` tree with `scripts/sync_skills.py`. Keep custom
agents in `.claude/agents`. Do not add executable hooks without a documented
threat review and a disabled-by-default example.
