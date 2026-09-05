#!/usr/bin/env python3
"""Run the deliberate seven-layer preflight mutation proof."""

from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAX_PROOF_TESTS = 64


def _test_ids(suite: unittest.TestSuite) -> list[str]:
    identifiers: list[str] = []
    stack: list[unittest.TestSuite | unittest.TestCase] = [suite]
    while stack:
        current = stack.pop()
        if isinstance(current, unittest.TestSuite):
            stack.extend(reversed(list(current)))
        else:
            identifiers.append(current.id())
        if len(identifiers) + len(stack) > MAX_PROOF_TESTS:
            raise ValueError(f"proof suite exceeds {MAX_PROOF_TESTS} tests")
    return sorted(identifiers)


def main() -> int:
    suite = unittest.defaultTestLoader.discover(
        str(ROOT / "tests"),
        pattern="test_preflight_mutations.py",
    )
    identifiers = _test_ids(suite)
    transcript = io.StringIO()
    result = unittest.TextTestRunner(stream=transcript, verbosity=2).run(suite)
    payload = {
        "ok": result.wasSuccessful(),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "tests": identifiers,
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
