#!/usr/bin/env python3
"""Fail when a digest-configured private marker is reachable anywhere in Git history."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from bounded_process import OutputLimitExceeded, run_bounded
from git_safety import clean_git_environment, effective_graft_error
from validate_repo import (
    BoundedErrors,
    MAX_PRIVATE_MARKER_WINDOWS,
    find_hashed_private_marker,
    load_private_marker_rules,
    read_text,
    redact_private_marker_diagnostics,
)


ROOT = Path(__file__).resolve().parents[1]
MAX_HISTORY_REFS = 256
MAX_HISTORY_COMMITS = 4_096
MAX_HISTORY_PATHS = 32_000
MAX_HISTORY_OBJECTS = 12_000
MAX_HISTORY_BLOBS = 8_000
MAX_HISTORY_INVENTORY_BYTES = 8_388_608
MAX_HISTORY_OBJECT_BYTES = 1_048_576
MAX_HISTORY_TOTAL_BYTES = 33_554_432
MAX_HISTORY_SECONDS = 240
OBJECT_ID = re.compile(rb"[0-9a-f]{40,64}\Z")


def _clean_environment() -> dict[str, str]:
    return dict(clean_git_environment())


def _git(
    root: Path,
    arguments: list[str],
    output_limit: int,
    deadline: float,
) -> tuple[int, bytes]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise subprocess.TimeoutExpired(arguments, MAX_HISTORY_SECONDS)
    completed = run_bounded(
        ["git", "-C", str(root), *arguments],
        cwd=root,
        timeout_seconds=min(10.0, remaining),
        output_limit=output_limit,
        env=_clean_environment(),
    )
    return completed.returncode, completed.output


def _scan_text(
    value: str,
    rules: tuple[tuple[int, str], ...],
    deadline: float,
) -> tuple[bool, bool]:
    # The clean-tree budget bounds one value here, not all historical revisions.
    # Whole-history work remains bounded by bytes, inventory counts and deadline.
    if time.monotonic() >= deadline:
        raise subprocess.TimeoutExpired("private marker scan", MAX_HISTORY_SECONDS)
    matched, _, exceeded = find_hashed_private_marker(
        value, rules, MAX_PRIVATE_MARKER_WINDOWS
    )
    if time.monotonic() >= deadline:
        raise subprocess.TimeoutExpired("private marker scan", MAX_HISTORY_SECONDS)
    return matched, exceeded


def validate_reachable_history(
    root: Path,
    rules: tuple[tuple[int, str], ...],
) -> list[str]:
    """Scan all ref-reachable object payloads and names within fixed resource budgets."""

    errors = BoundedErrors()
    if not rules:
        errors.append("private marker policy contains no usable rules")
        return list(errors)
    root = Path(os.path.abspath(root))
    deadline = time.monotonic() + MAX_HISTORY_SECONDS
    try:
        code, raw_root = _git(root, ["rev-parse", "--show-toplevel"], 4_096, deadline)
        if code != 0:
            return ["reachable-history gate requires a Git repository"]
        try:
            reported_root = Path(os.fsdecode(raw_root).strip()).resolve(strict=True)
            exact_root = root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return ["reachable-history gate could not establish the repository root"]
        if reported_root != exact_root:
            return ["reachable-history gate must run at the exact repository root"]
        graft_error = effective_graft_error(exact_root, repository_required=True)
        if graft_error:
            return [f"reachable-history gate refused: {graft_error}"]
        code, shallow = _git(
            exact_root,
            ["rev-parse", "--is-shallow-repository"],
            64,
            deadline,
        )
        if code != 0 or shallow.strip() not in {b"true", b"false"}:
            return ["reachable-history gate could not establish clone depth"]
        if shallow.strip() == b"true":
            return ["reachable-history gate refuses a shallow checkout"]

        code, raw_refs = _git(
            exact_root,
            ["for-each-ref", "--format=%(refname)"],
            MAX_HISTORY_INVENTORY_BYTES,
            deadline,
        )
        if code != 0:
            return ["reachable-history ref inventory failed"]
        refs = [line for line in raw_refs.decode("utf-8", errors="replace").splitlines() if line]
        if len(refs) > MAX_HISTORY_REFS:
            return [f"reachable-history ref cap exceeded: more than {MAX_HISTORY_REFS}"]

        for ref in refs:
            matched, exceeded = _scan_text(ref, rules, deadline)
            if exceeded:
                return [
                    "reachable-history private marker scan exceeded its per-value bounded window budget"
                ]
            if matched:
                reference_id = hashlib.sha256(ref.encode("utf-8")).hexdigest()[:12]
                errors.append(
                    f"private-source marker present in reachable history reference: id={reference_id}"
                )

        code, raw_commits = _git(
            exact_root,
            ["rev-list", "--all"],
            MAX_HISTORY_INVENTORY_BYTES,
            deadline,
        )
        if code != 0:
            return ["reachable-history commit inventory failed"]
        commits = [line for line in raw_commits.splitlines() if line]
        if any(OBJECT_ID.fullmatch(commit) is None for commit in commits):
            return ["reachable-history commit inventory contained an invalid object id"]
        if len(commits) > MAX_HISTORY_COMMITS:
            return [
                f"reachable-history commit cap exceeded: more than {MAX_HISTORY_COMMITS}"
            ]

        code, raw_paths = _git(
            exact_root,
            [
                "log",
                "--all",
                "--format=",
                "--name-only",
                "-z",
                "--no-renames",
                "--diff-merges=separate",
            ],
            MAX_HISTORY_INVENTORY_BYTES,
            deadline,
        )
        if code != 0:
            return ["reachable-history path inventory failed"]
        paths_seen = 0
        for raw_path in raw_paths.split(b"\0"):
            if not raw_path:
                continue
            paths_seen += 1
            if paths_seen > MAX_HISTORY_PATHS:
                return [
                    f"reachable-history path cap exceeded: more than {MAX_HISTORY_PATHS}"
                ]
            path_text = raw_path.decode("utf-8", errors="replace")
            matched, exceeded = _scan_text(path_text, rules, deadline)
            if exceeded:
                return [
                    "reachable-history private marker scan exceeded its per-value bounded window budget"
                ]
            if matched:
                path_id = hashlib.sha256(raw_path).hexdigest()[:12]
                errors.append(
                    f"private-source marker present in reachable history path: id={path_id}"
                )

        code, raw_objects = _git(
            exact_root,
            ["rev-list", "--objects", "--all"],
            MAX_HISTORY_INVENTORY_BYTES,
            deadline,
        )
        if code != 0:
            return ["reachable-history object inventory failed"]
        object_ids: list[bytes] = []
        seen: set[bytes] = set()
        for raw_line in raw_objects.splitlines():
            object_id, separator, raw_path = raw_line.partition(b" ")
            if OBJECT_ID.fullmatch(object_id) is None:
                return ["reachable-history object inventory contained an invalid object id"]
            if object_id not in seen:
                if len(object_ids) >= MAX_HISTORY_OBJECTS:
                    return [
                        f"reachable-history object cap exceeded: more than {MAX_HISTORY_OBJECTS}"
                    ]
                seen.add(object_id)
                object_ids.append(object_id)
            if separator:
                path_text = raw_path.decode("utf-8", errors="replace")
                matched, exceeded = _scan_text(path_text, rules, deadline)
                if exceeded:
                    return [
                        "reachable-history private marker scan exceeded its per-value bounded window budget"
                    ]
                if matched:
                    path_id = hashlib.sha256(raw_path).hexdigest()[:12]
                    errors.append(
                        f"private-source marker present in reachable history path: id={path_id}"
                    )

        blob_count = 0
        total_bytes = 0
        for raw_object_id in object_ids:
            object_id = raw_object_id.decode("ascii")
            code, raw_type = _git(
                exact_root,
                ["cat-file", "-t", object_id],
                64,
                deadline,
            )
            if code != 0:
                errors.append("reachable-history object type lookup failed")
                continue
            object_type = raw_type.strip()
            if object_type == b"tree":
                continue
            if object_type == b"blob":
                blob_count += 1
                if blob_count > MAX_HISTORY_BLOBS:
                    return [
                        f"reachable-history blob cap exceeded: more than {MAX_HISTORY_BLOBS}"
                    ]
            elif object_type not in {b"commit", b"tag"}:
                errors.append("reachable-history inventory contained an unsupported object type")
                continue
            try:
                code, content = _git(
                    exact_root,
                    ["cat-file", object_type.decode("ascii"), object_id],
                    MAX_HISTORY_OBJECT_BYTES,
                    deadline,
                )
            except OutputLimitExceeded:
                errors.append(
                    f"reachable-history object exceeds {MAX_HISTORY_OBJECT_BYTES} bytes"
                )
                continue
            if code != 0:
                errors.append("reachable-history object read failed")
                continue
            total_bytes += len(content)
            if total_bytes > MAX_HISTORY_TOTAL_BYTES:
                return [
                    f"reachable-history byte cap exceeded: more than {MAX_HISTORY_TOTAL_BYTES}"
                ]
            content_text = content.decode("utf-8", errors="replace")
            matched, exceeded = _scan_text(content_text, rules, deadline)
            if exceeded:
                return [
                    "reachable-history private marker scan exceeded its per-value bounded window budget"
                ]
            if matched:
                object_id_digest = hashlib.sha256(raw_object_id).hexdigest()[:12]
                errors.append(
                    "private-source marker present in reachable history object: "
                    f"id={object_id_digest}"
                )
    except OutputLimitExceeded:
        errors.append("reachable-history Git output exceeded its cap")
    except subprocess.TimeoutExpired:
        errors.append(
            f"reachable-history scan exceeded its {MAX_HISTORY_SECONDS}-second aggregate budget"
        )
    except OSError as exc:
        errors.append(f"reachable-history scan failed: {type(exc).__name__}")
    return sorted(set(errors))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    marker_errors = BoundedErrors()
    try:
        policy = read_text(args.root / "sources" / "private-marker-hashes.json")
        rules = load_private_marker_rules(policy, marker_errors)
        marker_errors.extend(validate_reachable_history(args.root, rules))
        safe_errors = redact_private_marker_diagnostics(marker_errors, rules)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        safe_errors = [f"reachable-history policy unavailable: {type(exc).__name__}"]
    if safe_errors:
        for error in safe_errors:
            print(f"ERROR: {error}")
        return 1
    print("PASS: bounded reachable-history marker validation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
