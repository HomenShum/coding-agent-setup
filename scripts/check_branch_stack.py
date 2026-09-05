#!/usr/bin/env python3
"""Check a bounded Git branch stack, with optional pre-initialized Graphite status."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from bounded_process import run_bounded
from git_safety import clean_git_environment, effective_graft_error
from path_safety import is_link_like


MAX_BRANCHES = 32
MAX_REF_CHARS = 1_024
MAX_OUTPUT_BYTES = 65_536
GRAPHITE_INITIALIZATION_MARKER = ".graphite_repo_config"


def graphite_command(executable: str) -> list[str]:
    """Build a direct command, including Windows npm wrapper handling."""

    arguments = [executable, "log", "short", "--no-interactive"]
    if os.name != "nt" or Path(executable).suffix.lower() not in {".cmd", ".bat"}:
        return arguments
    command_processor = os.environ.get("COMSPEC") or shutil.which("cmd.exe")
    if not command_processor:
        raise FileNotFoundError("Windows command processor is unavailable")
    return [command_processor, "/d", "/s", "/c", subprocess.list2cmdline(arguments)]


def graphite_initialized(root: Path) -> bool:
    """Return true only when this repository already has Graphite-owned metadata."""

    code, output = run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], root
    )
    lines = output.splitlines()
    if code != 0 or len(lines) != 1 or not lines[0]:
        return False
    common = Path(lines[0])
    if not common.is_absolute() or is_link_like(common) or not common.is_dir():
        return False
    marker = common / GRAPHITE_INITIALIZATION_MARKER
    return marker.is_file() and not is_link_like(marker)


def run(args: list[str], root: Path) -> tuple[int, str]:
    result = run_bounded(
        args,
        cwd=root,
        timeout_seconds=10,
        output_limit=MAX_OUTPUT_BYTES,
        env=clean_git_environment(),
    )
    output = result.output.decode("utf-8", "replace")
    return result.returncode, output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("branches", nargs="+")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--observe-graphite", action="store_true")
    args = parser.parse_args()
    if len(args.branches) < 2:
        print("ERROR: at least two branch refs are required")
        return 2
    if len(args.branches) > MAX_BRANCHES:
        print(f"ERROR: branch cap exceeded: {len(args.branches)} > {MAX_BRANCHES}")
        return 2
    invalid_ref = next(
        (
            branch
            for branch in args.branches
            if not branch or len(branch) > MAX_REF_CHARS or "\x00" in branch
        ),
        None,
    )
    if invalid_ref is not None:
        print(json.dumps({"ok": False, "error": "branch ref is empty or exceeds its cap"}, sort_keys=True))
        return 2
    root = Path(os.path.abspath(args.project_root))
    if is_link_like(root) or not root.is_dir():
        print(json.dumps({"ok": False, "error": "project root must be an existing non-link directory"}, sort_keys=True))
        return 2
    graft_error = effective_graft_error(root, repository_required=True)
    if graft_error:
        print(json.dumps({"ok": False, "error": graft_error}, sort_keys=True))
        return 1
    observations: list[dict[str, object]] = []
    try:
        for parent, child in zip(args.branches, args.branches[1:]):
            code, output = run(
                ["git", "merge-base", "--is-ancestor", "--", parent, child],
                root,
            )
            observations.append(
                {"parent": parent, "child": child, "is_ancestor": code == 0, "detail": output[:512]}
            )
        graphite: dict[str, object] = {"requested": args.observe_graphite, "available": False}
        graphite_executable = shutil.which("gt") if args.observe_graphite else None
        if graphite_executable:
            graphite = {"requested": True, "available": True, "initialized": False}
            if graphite_initialized(root):
                try:
                    code, output = run(graphite_command(graphite_executable), root)
                    graphite = {
                        "requested": True,
                        "available": True,
                        "initialized": True,
                        "ok": code == 0,
                        "sample": output[:4096],
                    }
                except (OSError, subprocess.SubprocessError) as exc:
                    graphite = {
                        "requested": True,
                        "available": True,
                        "initialized": True,
                        "ok": False,
                        "error": type(exc).__name__,
                    }
        payload = {"ok": all(bool(item["is_ancestor"]) for item in observations), "ancestry": observations, "graphite": graphite}
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload["ok"] else 1
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
