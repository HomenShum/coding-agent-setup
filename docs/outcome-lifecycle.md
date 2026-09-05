# From a trigger to a measured outcome

A builder changes a judge prompt, then switches coding tools. The next agent
must rescore the same saved outputs, preserve the failed cases and ask the same
reviewer; it must not start a new experiment with easier cases. One frozen
outcome contract and append-only record carry that work between hosts.

## Declare before implementation

Copy `templates/harness/outcome-contract.json` into the target's private working
area. Declare the current and candidate code, model, prompt, tools, retrieval,
corpus, dataset, rubric, runtime and deployment profile. Include the exact goal,
target state, cases, expected before/after improvement, invariants, human owner,
approval requirements, attempt budget and stop criteria. Use `DISCOVERY` and
`UNMEASURED` for unknowns. Discover first; never manufacture a baseline.

```bash
python scripts/outcome_review.py check --input outcome.json
python scripts/outcome_review.py route --trigger JUDGE_CHANGED
python scripts/outcome_review.py init --input outcome.json --ledger events.jsonl
python scripts/outcome_review.py append --input event.json --ledger events.jsonl --expected-head PREVIOUS_SHA256
python scripts/outcome_review.py render --ledger events.jsonl --format ascii
python scripts/outcome_review.py render --ledger events.jsonl --format html
```

The parent directory must already exist. Capture command stdout to your chosen
artifact path using the target's normal artifact writer. Rendering is escaped,
offline and derived from the same record. HTML and terminal views never fetch
links, run scripts or interpret evidence references as commands.

Events contain `type`, `actor`, `summary`, `next_action`, `failed_gates` and
`evidence` reference lists. The append operation binds the prior head and frozen
contract, records the timestamp, refuses concurrent/stale writers and caps the
ledger at 500 records / 4 MB. Do not delete a lock from another running process.
A crashed partial tail is `NO_GATE`; retain it and use an explicit reviewed
recovery, not silent truncation. Filesystem owners can rewrite files and hashes:
this is corruption detection and local ordering, not a signature or WORM store.

A host-switch event cannot clear failures. An explicit `GATE_PASSED` event names
the gates and replayable evidence references it resolves. References and actor
names still require independent verification. Recording human review does not
authenticate that human, grant permissions or activate a candidate. Candidate
creation is capped across handoffs; the target runner must additionally enforce
the declared wall-clock budget, cancellation, permissions and resource limits.

Target amendments are explanatory events, never edits to the old contract.
Initialize a new linked experiment for a changed target or acceptance policy.
Keep prior failures in view until the new owner explicitly dispositions them.

## Route only the affected work

| Trigger | Smallest required work |
|---|---|
| New feature | Profile, source/case curation, baseline, implementation, evaluation, review |
| Judge change | Rescore frozen outputs and recalibrate against reviewed labels |
| Pipeline or retriever change | Affected execution and one-component ablation, then regression |
| Corpus/spec change | Freshness/applicability and affected cases |
| Human annotation | New dataset identity, calibration, comparable reruns |
| Failed gate | Exact case + trace + source, bounded recovery, same-case rerun |
| Host switch | Verify handoff; preserve goals, identities, failures, budget and approvals |
| Deployment change | Separate data, inference, telemetry, operator and artifact boundaries |
| Documentation only | Verify it is truly non-behavioral; links/contracts, no automatic model run |

Use `bootstrap-evidence-app` with the existing planner/worker/judge, decision,
handoff and proof-packet skills. Hook examples remain fast, inert and bounded:
they request review, never perform expensive research or authorize deployment.
Where no host-native hook exists, invoke the route command explicitly or from
reviewed CI. A local lesson is a proposed convention until its owner accepts it.

## Profile, benchmark and trajectory

Choose deterministic retrieval, agentic search, workflow chain, durable job or
sandbox multi-turn based on the actual pipeline. Record trusted server-derived
fields, tools, expected trace topology, source scopes and human checkpoints.
Do not add an autonomous search loop to a known exact lookup.

Retrieval cases need frozen corpus and retriever identities, positive passages,
hard negatives, relevance judgments, required answer nuggets, provenance and
group-disjoint splits. Generated cases remain proposals until deterministic
source validation, independent evaluator review and domain-owner sampling are
complete. Never use model-generated gold as independently reviewed truth.

`outcome_review.py trajectory --input search.json` measures bounded search rounds,
exact repeated queries, unique documents and known-positive recall. Each round
declares query, query origin, retriever, corpus snapshot, trace, stop reason,
completeness and returned document IDs. It does not claim semantic repetition,
citation support or stopping quality from those counters. Target evaluators must
grade those separately and record latency, cost, retries and returned model.

Human review packets should contain the goal, output, atomic required nuggets,
supporting excerpts, missing evidence, output-judge and trajectory verdicts, and
the exact trace references. Cluster similar failures; do not make reviewers read
every raw search turn. Domain experts review domain truth; engineers review
runtime and infrastructure failures. Reviewed labels change dataset versions.

Current-run recovery and future harness improvement are separate. Recovery fixes
the failed work within the existing authority and budget. Improvement proposes a
new bounded component, freezes all other identities, runs baseline/candidate and
protected holdout cases, compares per-case critical gates plus quality/cost/time,
and requests independent acceptance. Neither route may alter authorization,
gold labels, tenant rules or promotion policy to make its result pass.
