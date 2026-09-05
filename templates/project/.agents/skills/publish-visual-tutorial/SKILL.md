---
name: publish-visual-tutorial
description: Produce a source-backed visual tutorial and verify every recorded scene before any authorized publication.
---

# Publish a visual tutorial

Read [the execution contract](references/contract.json) before starting. Validate the final receipt with its parameterized `verification.argv`, replacing `{python}`, `{skill_dir}`, and `{receipt}` with concrete local values.

Define the learner, task, starting state, and final observable outcome. Capture
the real workflow with deterministic inputs. Before recording, verify each
scene's route, content, console state, and viewport; never reconstruct a
before-state after editing.

Create a concise tutorial, transcript, and artifact receipt linking every
claim to a scene or command. Inspect exported pixels and playback. Publication
is an external action: prepare locally unless the user's own words authorize
the destination and audience.
