# Learning contract

This is an unconfigured scaffold, not an evaluated application.

Before running, replace generic criteria with reviewed domain criteria. Create
an authorized context inventory with provenance, access scope, hashes, reuse
decisions, conflicts and incomplete-search notices. Never export private context
into a public repository. Curate cases with stable IDs, source receipts, expected
behavior and group-disjoint visible/heldout assignments. Keep heldout contents
outside the candidate's accessible workspace; labels alone do not enforce secrecy.

Implement the target's existing runtime and trace adapter, not a second engine.
Use local traces by default; configure hosted telemetry only with authorized
credentials and redaction. Prove hosted trace and score readback, not just flush.
Calibrate the judge against reviewed positives and negative controls first.

The reference comparison accepts runs with `identity` (dataset, rubric, model,
evaluator), `harness`, `synthetic`, and `cases`. Each case has `id`, `group`,
`split` (visible or heldout), `status`, `trace`, `gates` and `scores`.
Each grade is `{ "value": ..., "rationale": "..." }`.
Gate values are booleans; score values are integers 1 through 5.

Comparison establishes numerical eligibility ONLY. It does not authenticate
receipts, certify judge calibration or activate a harness. Freeze these inputs
under a trusted runner; candidate edits may not change policy, cases or judges.
Human review must examine provenance, calibration, heldout isolation, actual
trace readback and rendered UI proof before accepting a candidate.
