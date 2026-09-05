---
name: capture-ui-before-after
description: Capture comparable before-and-after UI evidence at the same route, viewport, data, theme, and interaction state.
---

# Capture UI before and after

Read [the execution contract](references/contract.json) before starting. Validate the final receipt with its parameterized `verification.argv`, replacing `{python}`, `{skill_dir}`, and `{receipt}` with concrete local values.

Before editing, capture the reachable current interface and record route,
viewport, theme, session class, fixture, trigger, console, and network state.
Box only the intended change regions and name out-of-scope neighbors.

After editing, replay the identical state and capture after pixels plus empty,
loading, error, populated, overflow, and responsive states promised by the
contract. Compare neighboring regions for drift. DOM proves semantics; pixels
prove appearance; neither alone proves the other.
