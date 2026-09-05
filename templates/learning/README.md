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

The version 2 reference comparison accepts runs with `version: 2`,
`policy_sha256`, `identity` (dataset, rubric, model, evaluator), `harness`,
`synthetic`, and `cases`. Each case has `id`, `group`,
`split` (visible or heldout), `status`, `trace`, `gates` and `scores`.
Each grade is `{ "value": ..., "rationale": "..." }`.
Gate values are booleans; score values are integers 1 through 5.

`policy_sha256` is the SHA-256 of the reviewed policy serialized as UTF-8 JSON
with sorted keys, compact separators, literal Unicode and nonfinite numbers
forbidden (`policy_sha256()` in the copied script). Both runs must bind that
exact policy meaning. Baseline and candidate must have distinct harness
identities. Every case is critical: any dimension decreasing on any case rejects
the candidate, even when a split's aggregate score improves. All candidate
boolean gates must pass. A trace ID prefixed `synthetic:` cannot be declared
nonsynthetic. Other trace IDs still require independent authenticity checks.

Version 1 policies and unversioned runs are deliberately rejected with
`NO_GATE`; no silent conversion is performed. Review the policy wording and the
`regression: "no-case-score-decrease"` rule, then regenerate both runs with
version 2 and the reviewed policy digest. Merely relabeling old output is not
a rerun. Digest equality detects disagreement, not authorization: the trusted
runner must protect policy and frozen inputs from candidate edits.

Comparison establishes numerical eligibility ONLY. It does not authenticate
receipts, certify judge calibration or activate a harness. Freeze these inputs
under a trusted runner; candidate edits may not change policy, cases or judges.
Human review must examine provenance, calibration, heldout isolation, actual
trace readback and rendered UI proof before accepting a candidate.
