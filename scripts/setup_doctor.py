#!/usr/bin/env python3
"""Check three-host setup shape without opening host credential stores."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import tomllib

from path_safety import read_regular_file_bounded, reject_linked_path


MAX_CONFIG_BYTES = 1_048_576
MINIMUM_PYTHON = (3, 11)
HOST_BINARIES = {"codex": "codex", "claude": "claude", "cursor": "agent"}
HOST_PATHS = {
    "codex": ((".codex/config.toml", "file"), (".codex/agents", "directory")),
    "claude": (
        (".claude/CLAUDE.md", "file"),
        (".mcp.json", "file"),
        (".claude/settings.json", "file"),
        (".claude/agents", "directory"),
        (".claude/rules/claude-code.md", "file"),
        (".claude/skills", "directory"),
    ),
    "cursor": ((".cursor/mcp.json", "file"), (".cursor/agents", "directory")),
}
PROJECT_JSON_CONFIGS = (
    ".mcp.json",
    ".cursor/mcp.json",
    ".cursor/cli.json",
    ".cursor/permissions.json",
    ".cursor/sandbox.json",
    ".claude/settings.json",
)


def path_status(root: Path, relative: str, expected: str) -> str:
    path = root / relative
    try:
        reject_linked_path(path, root, label="setup")
    except (OSError, ValueError):
        return "invalid"
    if not path.exists():
        return "missing"
    if expected == "file":
        return "present" if path.is_file() else "invalid"
    return "present" if path.is_dir() else "invalid"


def read_config(root: Path, relative: str) -> str:
    if path_status(root, relative, "file") != "present":
        raise ValueError("config is not a regular non-symlink file")
    path = root / relative
    content = read_regular_file_bounded(
        path,
        MAX_CONFIG_BYTES,
        boundary=root,
        label="config",
    )
    return content.decode("utf-8")


def inspect_project(root: Path, hosts: tuple[str, ...], skip_binaries: bool) -> list[dict[str, str]]:
    results: list[dict[str, str]] = [
        {
            "host": "runtime",
            "check": "Git",
            "status": "present" if shutil.which("git") else "missing",
        },
        {
            "host": "runtime",
            "check": "Python >= 3.11",
            "status": "present" if sys.version_info >= MINIMUM_PYTHON else "invalid",
        },
    ]
    for relative, expected in (("AGENTS.md", "file"), (".agents/skills", "directory")):
        results.append(
            {
                "host": "shared",
                "check": relative,
                "status": path_status(root, relative, expected),
            }
        )
    for host in hosts:
        if not skip_binaries:
            results.append(
                {
                    "host": host,
                    "check": "binary",
                    "status": "present" if shutil.which(HOST_BINARIES[host]) else "missing",
                }
            )
        for relative, expected in HOST_PATHS[host]:
            results.append(
                {
                    "host": host,
                    "check": relative,
                    "status": path_status(root, relative, expected),
                }
            )
    if "claude" in hosts and path_status(root, ".claude/CLAUDE.md", "file") == "present":
        try:
            imported = read_config(root, ".claude/CLAUDE.md").strip() == "@../AGENTS.md"
        except (OSError, UnicodeDecodeError, ValueError):
            imported = False
        results.append(
            {
                "host": "claude",
                "check": "AGENTS import",
                "status": "present" if imported else "invalid",
            }
        )
    return sorted(results, key=lambda item: (item["host"], item["check"]))


def parse_configs(root: Path, results: list[dict[str, str]]) -> None:
    def mark_invalid(relative: str) -> None:
        for item in results:
            if item["check"] == relative:
                item["status"] = "invalid"
                return
        results.append({"host": "config", "check": relative, "status": "invalid"})

    for relative in PROJECT_JSON_CONFIGS:
        status = path_status(root, relative, "file")
        if status == "present":
            try:
                json.loads(read_config(root, relative))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                mark_invalid(relative)
        elif status == "invalid":
            mark_invalid(relative)
    relative = ".codex/config.toml"
    status = path_status(root, relative, "file")
    if status == "present":
        try:
            tomllib.loads(read_config(root, relative))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError):
            mark_invalid(relative)
    elif status == "invalid":
        mark_invalid(relative)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--hosts", default="codex,claude,cursor")
    parser.add_argument("--skip-binaries", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    hosts = tuple(dict.fromkeys(part.strip() for part in args.hosts.split(",") if part.strip()))
    if not hosts or any(host not in HOST_BINARIES for host in hosts):
        print("ERROR: hosts must be a comma-separated subset of codex,claude,cursor")
        return 2
    try:
        results = inspect_project(args.project_root, hosts, args.skip_binaries)
        parse_configs(args.project_root, results)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1
    invalid = any(item["status"] == "invalid" for item in results)
    missing = any(item["status"] == "missing" for item in results)
    payload = {"ready": not invalid and not missing, "checks": results}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        for item in results:
            print(f"{item['status'].upper()}: {item['host']} {item['check']}")
    return 1 if invalid else 2 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
