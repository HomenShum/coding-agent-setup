# Artifact registry

This public registry contains only reproducible, non-sensitive setup evidence.
Private transcripts, local histories, browser profiles, and project receipts
do not belong here.

| Artifact | Claim | Replay | Status | Retention |
|---|---|---|---|---|
| Outcome continuity | Hash-linked records preserve frozen goals, failures and attempt limits across host switches; HTML and ASCII derive from one source | `python -m unittest discover -s tests -p test_outcome_review.py -v` | Local integrity; not authenticated approval | Keep contracts; target records remain private |
| Enterprise profile | Incomplete region/access proof stays NO_GATE; prohibited declared transfers reject | `python -m unittest discover -s tests -p test_deployment_profile.py -v` | Offline consistency only | Keep generic fixtures; customer profiles remain private |
| Application bootstrap contract | Context reuse, data, tracing, calibrated judging and UI proof have one portable workflow; synthetic comparisons never activate harnesses | `python -m unittest discover -s tests -p test_bootstrap_learning.py -v` | Local reference only; real target integration unverified | Keep with repository |
| Publication validation | Public files are bounded, parseable, linked, attributed, and secret-scanned | `python scripts/validate_repo.py` | Maintained | Keep with repository |
| Setup scenarios | Template parsing, synchronization, state, hooks, and bounded failure paths behave as documented | `python -m unittest discover -s tests -v` | Maintained | Keep with repository |
| Fresh-project materialization | A copied project passes skill sync, native config parsing, and setup diagnosis, then honestly reports `NO_GATE` until target-owned proof is configured | `python -m unittest discover -s tests -p test_agent_stack_scenarios.py -v` | Maintained | Keep with repository |
| Host-native smoke | Installed Codex, Claude Code, and Cursor commands can each discover the copied project surfaces | Launch each host and record a harmless project-scoped invocation | Manual / UNVERIFIED here | Record per workstation; never publish credentials or session data |
| Preflight mutations | Every preflight layer rejects its synthetic violation | `python scripts/prove_preflight_mutations.py` | Maintained | Regenerate after gate changes |
| Agent-state examples | LOOP and GRAPH examples obey routing, cap, and current-handoff digest rules | `python scripts/validate_agent_state.py templates/harness/agent-state-graph.json --project-root .` | Maintained | Keep with contract version |
| Reachable-history privacy | A deleted blocked marker cannot remain in any reachable ref, path, commit, tag, or blob, and process-local replace refs or grafts cannot hide it | `python scripts/check_private_history.py` from a full clone | Required before publication | Keep with repository |
| Git ancestry integrity | Preflight and branch-stack gates ignore replacement refs, reject effective legacy grafts, and disambiguate ref arguments | Git mutation scenarios in `tests/test_history_scenarios.py`, `tests/test_preflight_mutations.py`, and `tests/test_agent_stack_scenarios.py` | Maintained | Keep with repository |
| Source health | Every catalogued vendor page and external repository answers a bounded HTTPS check | `python scripts/validate_repo.py --check-external` | Point-in-time | Re-run after source changes and on schedule |

Project copies should append their own artifact rows with an owner, source
digest, proof command, result, and retention decision.

Offline kit checks parse native files but do not prove that an installed host
discovers an agent, starts an MCP server, or authenticates successfully. Those
claims require the separate host-native smoke receipt above.
