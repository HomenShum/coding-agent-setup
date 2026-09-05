# Security policy

## Report a vulnerability

Do not open a public issue containing a credential, private path, session
transcript, or exploit detail. Use the repository's private GitHub security
advisory form instead:

<https://github.com/HomenShum/coding-agent-setup/security/advisories/new>

## Publication policy

- Live secrets never belong in command arguments, URLs, JSON, TOML, Markdown,
  screenshots, terminal captures, or git history.
- Authentication stores and session databases are excluded rather than
  redacted and copied.
- MCP examples use environment-variable names. Hooks are disabled by default.
- Project-local override files stay ignored.
- A local secret scan must pass before the first commit and again before push.
- If a credential is ever exposed, remove it from use and rotate it; deleting a
  line from the latest commit does not remove it from history or logs.

See [docs/security.md](docs/security.md) for the complete threat model and
pre-publication checklist.
