#!/usr/bin/env python3
"""Shared fail-closed controls for Git graph reads."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Mapping

from bounded_process import OutputLimitExceeded, run_bounded
from path_safety import is_link_like


MAX_GIT_METADATA_BYTES = 4_096
MAX_GIT_METADATA_SECONDS = 5


def clean_git_environment() -> Mapping[str, str]:
    """Ignore inherited Git routing and disable replacement objects."""

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    environment["GIT_NO_REPLACE_OBJECTS"] = "1"
    return environment


def effective_graft_error(
    root: Path,
    *,
    repository_required: bool,
) -> str | None:
    """Reject an effective legacy graft path before reading Git ancestry."""

    root = Path(os.path.abspath(root))
    try:
        completed = run_bounded(
            [
                "git",
                "-C",
                str(root),
                "rev-parse",
                "--path-format=absolute",
                "--git-path",
                "info/grafts",
            ],
            cwd=root,
            timeout_seconds=MAX_GIT_METADATA_SECONDS,
            output_limit=MAX_GIT_METADATA_BYTES,
            env=clean_git_environment(),
        )
    except OutputLimitExceeded:
        return "effective Git graft-path lookup exceeded its output cap"
    except subprocess.TimeoutExpired:
        return "effective Git graft-path lookup exceeded its time budget"
    except (OSError, ValueError) as exc:
        return f"effective Git graft-path lookup failed: {type(exc).__name__}"
    if completed.returncode != 0:
        if repository_required:
            return "effective Git graft path could not be established"
        return None

    try:
        decoded = os.fsdecode(completed.output).strip()
    except (TypeError, UnicodeError):
        return "effective Git graft path could not be decoded"
    lines = decoded.splitlines()
    if len(lines) != 1 or not lines[0]:
        return "effective Git graft path was ambiguous"
    graft_path = Path(lines[0])
    if (
        not graft_path.is_absolute()
        or graft_path.name != "grafts"
        or graft_path.parent.name != "info"
    ):
        return "effective Git graft path was not repository-owned"

    metadata_root = graft_path.parent.parent
    try:
        if is_link_like(metadata_root) or not metadata_root.is_dir():
            return "effective Git metadata root is unavailable or link-like"
        if is_link_like(graft_path.parent):
            return "effective Git graft parent is link-like"
        try:
            os.lstat(graft_path)
        except FileNotFoundError:
            return None
        except OSError as exc:
            return f"effective Git graft path could not be inspected: {type(exc).__name__}"
        if is_link_like(graft_path):
            return "effective Git graft path is link-like"
    except OSError as exc:
        return f"effective Git graft path could not be inspected: {type(exc).__name__}"
    return "effective Git graft path is present"
