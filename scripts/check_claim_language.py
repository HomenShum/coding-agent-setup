#!/usr/bin/env python3
"""Reject unqualified completion language in bounded handoff artifacts."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys

from path_safety import read_regular_file_bounded


MAX_FILES = 64
MAX_FILE_BYTES = 131_072
CLAIM = re.compile(r"\b(done|complete|completed|deployed|live|proven|shipped|verified)\b", re.I)
EVIDENCE = re.compile(r"\b(evidence|proof|receipt|replay|observation|unverified)\b", re.I)


def check(path: Path) -> list[str]:
    candidate = Path(os.path.abspath(path))
    content = read_regular_file_bounded(
        candidate,
        MAX_FILE_BYTES,
        boundary=Path(candidate.anchor),
        label="claim input",
    )
    lines = content.decode("utf-8").splitlines()
    errors: list[str] = []
    for index, line in enumerate(lines):
        if not CLAIM.search(line):
            continue
        context = " ".join(lines[max(0, index - 1) : min(len(lines), index + 2)])
        if not EVIDENCE.search(context):
            errors.append(f"{path}:{index + 1}: completion claim has no nearby evidence label")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args()
    if len(args.paths) > MAX_FILES:
        print(f"ERROR: path cap exceeded: {len(args.paths)} > {MAX_FILES}")
        return 2
    errors: list[str] = []
    try:
        for path in sorted(args.paths):
            errors.extend(check(path))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        return 1
    print("PASS: completion claims are evidence-qualified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
