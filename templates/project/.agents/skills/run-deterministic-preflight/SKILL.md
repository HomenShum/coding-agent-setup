---
name: run-deterministic-preflight
description: Run the configured seven-layer preflight and mutation proof before a change is presented for review.
---

# Run deterministic preflight

Read [the execution contract](references/contract.json) before starting. Validate the final receipt with its parameterized `verification.argv`, replacing `{python}`, `{skill_dir}`, and `{receipt}` with concrete local values.

Read the project preflight configuration, then run the checked-in gate. Report
the interpreter, config path, each layer result, aggregate exit code, and the
mutation-proof result.

- Exit `0` is `PASS` only when every applicable layer passes.
- Exit `1` is an observed `FAIL` and must name the failing layer.
- Exit `2` is `NO_GATE`; missing configuration or proof never passes.

Never weaken a check or update an expected value merely to turn red green.
After a repair, rerun the exact mutation that failed and the surrounding test
suite. Preserve bounded raw output as the receipt.
