# Planner, workers, judge, and graph protocol

The human defines the outcome and authority. The planner keeps the decision
context small, workers gather bounded evidence, and a fresh judge tries to
refute the planner's numbered claims. Host-specific files only adapt this
protocol to a vendor's configuration format.

## Planner-workers-judge

1. The planner writes `C1..Cn`; each claim is one checkable sentence with an
   exact path, symbol, commit, or observable state.
2. Independent workers receive one lens each and the same mutation policy.
   They return `MEASURED`, `INFERRED`, or `UNVERIFIED` findings with citations
   plus a surprises list. Filesystem-read-only work is the default; inherited
   tools are a separate gate.
3. The planner waits for all receipts, then gives the claims and raw evidence
   to one fresh judge.
4. The judge returns `CONFIRMED`, `REFUTED`, or `WEAKENED` per claim. It attacks
   the claims; it does not summarize the work.
5. The planner folds corrections, reruns the named proof, and records the final
   disposition.

Use parallel workers only when their inputs and write scopes are independent.
The public default is at most five workers. A worker report is a claim, not a
delivery receipt.

## LOOP and GRAPH

`LOOP` is the default for work that one planner can complete and verify. Use
`GRAPH` only when `why_graph` names at least two current reasons: distinct
specialties, fan-out/fan-in, different toolsets, auditable routing, isolated
failure, or a dedicated reviewer.

```text
LOOP:  human -> planner -> gate -> human
                 ^-----------'

GRAPH: human -> planner -> worker(s) -> planner -> gate -> judge -> human
                                                 ^        |
                                                 +--------+
```

In GRAPH mode, `planner -> human` and `gate -> human` cannot deliver. Only a
judge `PASS` reaches the human. Other dispositions are `REVISE`, `REPLAN`,
`HITL`, and `BLOCKED`. The default caps are twelve transitions and five
workers; subscription hosts do not expose a portable per-session dollar meter.

Validate a state receipt with:

```bash
python scripts/validate_agent_state.py templates/harness/agent-state-graph.json \
  --project-root .
```

## Write scopes

| Role | May write |
|---|---|
| human | outcome, authority, mode, caps |
| planner | current node, route, handoff reference, events |
| worker | append-only receipts |
| gate | deterministic verdict |
| judge | disposition and corrections |
| recovery | isolated failure record |

Every host switch appends a handoff event that points to an immutable snapshot,
not the mutable root `HANDOFF.md`. Before switching, refresh the root handoff,
copy its exact bytes to a unique path such as
`handoffs/0001/HANDOFF.md`, hash that snapshot, and append the event. A later
switch uses a new numbered directory. The state cap limits one active receipt
to sixty-four event snapshots; archive or replace the whole state before
removing its referenced snapshots. This does not create a new source of truth
or transfer authority from the human.

A host-switch event has exactly five fields: `type` is `host-switch`; `from`
and `to` are different bounded host identifiers; `handoff` is a
repository-relative, non-sensitive path whose filename is `HANDOFF.md`; and
`handoff_sha256` is the 64-hex digest of that immutable file's current bytes.
No two events may reuse one path. An eventful state requires `--project-root`;
validation reads every referenced regular file through the shared byte cap
without following symbolic links or junctions, then compares its digest.
Missing files, stale or reused snapshots, unknown fields, absolute paths,
parent traversal, Git metadata, host-private directories, and empty event
objects fail validation.
