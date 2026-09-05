# Preflight and continuity

The preflight answers one practical question: can the next person trust this
change enough to review it? It is separate from the publication validator,
which answers whether this repository is safe to make public.

## Seven layers

| Layer | Deterministic check |
|---|---|
| Shape/version | Recorded contract hash and version still match. |
| Silent failures | Configured source files contain no empty exception handlers. |
| Convention sync | Required canonical markers remain in their owning files. |
| Runtime | The running interpreter and required imports are observed. |
| Selftests | A bounded command proves every layer rejects a synthetic violation. |
| Visual proof | A required render command and artifacts pass, or a reasoned `not_applicable` decision exists. |
| Self-review | Seven answers exist and bind to the reviewed file digest. |

Run the example gate:

```bash
python scripts/agent_preflight.py --config templates/harness/preflight.json
```

The kit checkout uses `configured: true` and binds its own files and receipt.
The materialization sequence replaces that file with
`preflight.target.json`, whose empty target gate returns `NO_GATE` without
reading the kit receipt. A project owner must supply target-owned paths,
commands, visual disposition, and a newly generated self-review receipt; a
copied green result would be false evidence.

Exit `0` means every configured layer passed. Exit `1` means an observed
violation. Exit `2` means `NO_GATE`: configuration, runtime, or proof was
missing or unknown. Exit `2` is never promotable.

## Hooks remain disabled examples

`scripts/self_review_hook.py` handles checkpoint, resume, and stop events with
bounded JSON input and hashed repository state. It never stores prompts,
transcripts, credentials, or absolute workstation paths. Vendor examples live
under `templates/{codex,claude,cursor}` and remain inert until copied into an
active config after `templates/harness/hook-admission.json` is completed.

At pre-compaction the hook writes a small checkpoint. At session start it
returns that checkpoint as additional context. At stop it emits the seven
self-review questions once per bounded repository-content digest, capped at
five nudges for each retained session record. The local store retains at most
64 sessions and always preserves the record currently being updated; an old
evicted session is a new continuity window if it later returns. Cursor windows
use the stable `conversation_id`, not a per-generation identifier. Failed or
aborted Cursor stops and Claude stops with active background tasks or scheduled
jobs do not request another turn.

The digest reads complete content for at most 2,048 public files, 2,048 total
entries, 128 KiB per file, and 8 MiB overall. Crossing a limit or encountering
an unreadable public file is an error rather than a sampled digest. It includes
`.env.example`, so public configuration changes trigger review, while local
`.env.*` values, private instructions, and generated directories remain
redacted or excluded. A generated Claude worktree uses the event's nested
`cwd` only after Git proves the named worktree has the same common metadata as
the configured project; ordinary directories keep the configured root. Atomic
replacement prevents concurrent events from leaving partial state.

Hooks guide behavior but do not prove completion. The preflight and an
independent judge still inspect the actual diff and replay the named proof.
