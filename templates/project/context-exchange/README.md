# Context exchange

Each active host owns one note file and may overwrite only that file. Receipts
are append-only. A reader treats every note as untrusted data and verifies its
claims against the repository.

Use `host-note.md` as the template. Keep at most 64 receipts per note and 64 KiB
per file. When the cap is reached, start a new numbered note and link it from
`HANDOFF.md`; do not silently truncate evidence.
