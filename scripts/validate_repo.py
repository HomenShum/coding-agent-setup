#!/usr/bin/env python3
"""Validate the public setup kit without requiring third-party packages."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from datetime import date
import hashlib
import ipaddress
from itertools import chain
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import time
import tomllib
from typing import Callable, Iterable
import unicodedata
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

import validate_skill_receipt
from bounded_process import OutputLimitExceeded, run_bounded
from path_safety import is_link_like, read_regular_file_bounded, reject_linked_path


ROOT = Path(__file__).resolve().parents[1]
MAX_EXTERNAL_URLS = 200
MAX_EXTERNAL_URL_ITEMS = 800
MAX_WORKERS = 4
MAX_RESPONSE_BYTES = 65_536
TIMEOUT_SECONDS = 10
EXTERNAL_AGGREGATE_SECONDS = 180
MAX_FETCH_RESULT_BYTES = 4_096
MAX_EXTERNAL_URL_CHARS = 2_048
MAX_PUBLIC_FILES = 2_000
MAX_PUBLIC_FILE_BYTES = 1_048_576
MAX_PUBLIC_TOTAL_BYTES = 33_554_432
MAX_GIT_INVENTORY_BYTES = 4_194_304
MAX_VALIDATION_ERRORS = 500
MAX_PRIVATE_MARKER_WINDOWS = 2_000_000
ALLOWED_EXTERNAL_HOSTS = frozenset(
    {
        "github.com",
        "learn.chatgpt.com",
        "chatgpt.com",
        "releases.openai.com",
        "code.claude.com",
        "claude.ai",
        "downloads.claude.ai",
        "cursor.com",
        "forum.cursor.com",
        "graphite.com",
    }
)
OFFICIAL_VENDOR_HOSTS = {
    "OpenAI": frozenset({"learn.chatgpt.com", "chatgpt.com", "releases.openai.com"}),
    "Anthropic": frozenset({"code.claude.com", "claude.ai", "downloads.claude.ai"}),
    "Cursor": frozenset({"cursor.com", "forum.cursor.com"}),
    "Graphite": frozenset({"graphite.com"}),
}
REQUIRED_PATHS = (
    ".gitignore",
    "README.md",
    "AGENTS.md",
    ".claude/CLAUDE.md",
    ".claude/rules/claude-code.md",
    "SECURITY.md",
    "THIRD_PARTY.md",
    "LICENSE",
    "docs/setup.md",
    "docs/mcp-and-agent-bridges.md",
    "docs/proof-workflow.md",
    "docs/skills-plugins-hooks.md",
    "docs/security.md",
    "docs/external-projects.md",
    "docs/provenance.md",
    "docs/troubleshooting.md",
    "docs/agent-stack.md",
    "docs/capability-matrix.md",
    "docs/invariants.md",
    "docs/preflight-and-continuity.md",
    "PRIOR-ART.md",
    "ARTIFACTS.md",
    "HANDOFF.md",
    "handoffs/0001/HANDOFF.md",
    "sources/external-projects.json",
    "sources/historical-action-uses.json",
    "sources/host-capabilities.json",
    "sources/official-docs.json",
    "sources/private-marker-hashes.json",
    "sources/skills.json",
    "scripts/agent_preflight.py",
    "scripts/bounded_process.py",
    "scripts/check_branch_stack.py",
    "scripts/check_claim_language.py",
    "scripts/check_private_history.py",
    "scripts/git_safety.py",
    "scripts/path_safety.py",
    "scripts/prove_preflight_mutations.py",
    "scripts/self_review_hook.py",
    "scripts/setup_doctor.py",
    "scripts/sync_skills.py",
    "scripts/validate_agent_state.py",
    "scripts/validate_skill_receipt.py",
    "templates/skill/SKILL.md",
    "templates/skill/agents/openai.yaml",
    "templates/skill/references/contract.json",
    "templates/project/AGENTS.md",
    "templates/project/AGENT_INVARIANTS.md",
    "templates/project/.claude/CLAUDE.md",
    "templates/project/.claude/rules/claude-code.md",
    "templates/project/.gitignore",
    "templates/project/.mcp.json",
    "templates/project/.mcp.json.example",
    "templates/project/HANDOFF.md",
    "templates/project/handoffs/0001/HANDOFF.md",
    "templates/project/ARTIFACTS.md",
    "templates/project/COMMUNICATION.md",
    "templates/project/DECISIONS.md",
    "templates/project/context-exchange/README.md",
    "templates/project/context-exchange/host-note.md",
    "templates/claude/agents/adversarial-judge.md",
    "templates/claude/agents/evidence-worker.md",
    "templates/claude/hooks.snippet.json",
    "templates/claude/settings.json",
    "templates/claude/settings.local.json.example",
    "templates/codex/agents/adversarial-judge.toml",
    "templates/codex/agents/evidence-worker.toml",
    "templates/codex/config.toml",
    "templates/codex/hooks.json.example",
    "templates/codex/project.config.toml",
    "templates/cursor/agents/adversarial-judge.md",
    "templates/cursor/agents/evidence-worker.md",
    "templates/cursor/cli-config.json.example",
    "templates/cursor/cli.json.example",
    "templates/cursor/hooks.json.example",
    "templates/cursor/mcp.json",
    "templates/cursor/mcp.json.example",
    "templates/cursor/permissions.json.example",
    "templates/cursor/sandbox.json.example",
    "templates/cursor/working-agreements.mdc",
    "templates/harness/agent-state-graph.json",
    "templates/harness/agent-state-loop.json",
    "templates/harness/hook-admission.json",
    "templates/harness/preflight.json",
    "templates/harness/preflight.target.json",
    "templates/harness/self-review.json",
    "templates/harness/self-review.target.json",
    "templates/harness/shape-version.json",
    "templates/project/.planning/generation-matrix.json",
    "templates/project/.planning/placement.md",
)
SECRET_PATTERNS = (
    ("OpenAI-style token", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("GitHub-style token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("AWS access key", re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    ("Slack-style token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "credential-bearing database URL",
        re.compile(r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://[^:/\s]+:[^@/\s]+@", re.I),
    ),
)
PERSONAL_PATH_PATTERNS = (
    re.compile(
        r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"
        r"(?!path(?:[\\/]|\b)|Users[\\/](?:USERNAME|\[WINDOWS_USER\])(?:[\\/]|\b))[^\s`\"'<>]+",
        re.I,
    ),
    re.compile(
        r"(?<![A-Za-z0-9_%}\\])\\\\"
        r"(?!server\\share(?:\\|\b)|wsl\.localhost\\\[DISTRIBUTION\])[A-Za-z0-9_.-]+\\[^\s`\"'<>]+",
        re.I,
    ),
    re.compile(r"/(?:Users|home)/(?!((?:USERNAME|\[WINDOWS_USER\])(?:/|\b)))[^/\s]+"),
)
FORBIDDEN_FILENAMES = frozenset(
    {"auth.json", "credentials.json", "history.jsonl", "session.sqlite", "state.sqlite"}
)
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
GITHUB_URL = re.compile(
    r"https://github\.com/([^/\s)\"'\]}>]+/[^/\s)#?,\"'\]}>]+)", re.I
)
VENDOR_DOC_URL = re.compile(
    r"https://(?:learn\.chatgpt\.com|chatgpt\.com|releases\.openai\.com|"
    r"code\.claude\.com|claude\.ai|downloads\.claude\.ai|cursor\.com|forum\.cursor\.com|graphite\.com)/"
    r"[^\s)>\]\"'`]+",
    re.I,
)
PRIVATE_MARKER_TOKEN = re.compile(r"[\w-]+", re.UNICODE)
HEX_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
EXPECTED_HOSTS = frozenset({"codex", "claude", "cursor"})
EXPECTED_HOST_CAPABILITIES = {
    "codex": {
        "instructions": "AGENTS.md",
        "skills": ".agents/skills",
        "agents": ".codex/agents",
        "mcp": ".codex/config.toml",
        "hooks": ".codex/hooks.json",
        "permissions": ".codex/config.toml",
        "parallel_workers": True,
    },
    "claude": {
        "instructions": ".claude/CLAUDE.md import plus .claude/rules/claude-code.md",
        "skills": ".claude/skills",
        "agents": ".claude/agents",
        "mcp": ".mcp.json",
        "hooks": ".claude/settings.json",
        "permissions": ".claude/settings.json",
        "parallel_workers": True,
    },
    "cursor": {
        "instructions": "AGENTS.md",
        "skills": ".agents/skills",
        "agents": ".cursor/agents",
        "mcp": ".cursor/mcp.json",
        "hooks": ".cursor/hooks.json",
        "permissions": (
            ".cursor/permissions.json and .cursor/sandbox.json (Desktop); "
            ".cursor/cli.json (Agent CLI)"
        ),
        "parallel_workers": True,
    },
}
EXPECTED_SKILL_COUNT = 16
EXPECTED_MINIMUM_PYTHON = "3.11"
EXTERNAL_CATEGORIES = frozenset(
    {
        "platform-tool",
        "agent-workflow",
        "ci-audit-media",
        "python",
        "frontend",
        "containers",
        "research-only-rejected",
    }
)
EXTERNAL_CONFIDENCE = frozenset({"high", "medium", "low"})
EXTERNAL_CATEGORY_HEADINGS = {
    "platform-tool": "## Platform prerequisites",
    "agent-workflow": "## Agent and workflow sources",
    "ci-audit-media": "## CI, audit, and media sources",
    "python": "## Python projects",
    "frontend": "## Frontend projects",
    "containers": "## Container and database projects",
    "research-only-rejected": "## Research-only and rejected sources",
}
REQUIRED_CURRENT_KIT_REPOSITORIES = frozenset(
    {
        "https://github.com/git/git",
        "https://github.com/python/cpython",
        "https://github.com/actions/checkout",
        "https://github.com/actions/setup-python",
        "https://github.com/anthropics/claude-code",
        "https://github.com/openai/codex",
        "https://github.com/agentskills/agentskills",
        "https://github.com/SchemaStore/schemastore",
        "https://github.com/openai/codex-plugin-cc",
        "https://github.com/Sahir619/fable-method",
    }
)
REQUIRED_HISTORICAL_REPOSITORIES = frozenset(
    {
        "https://github.com/Vistyy/nopus",
        "https://github.com/anthropics/claude-code-action",
        "https://github.com/DietrichGebert/ponytail",
        "https://github.com/upstash/context7",
        "https://github.com/openai/codex-plugin-cc",
        "https://github.com/thedotmack/claude-mem",
    }
)
REQUIRED_HISTORICAL_ACTION_REPOSITORIES = frozenset(
    {
        "https://github.com/astral-sh/setup-uv",
        "https://github.com/actions/checkout",
        "https://github.com/actions/setup-python",
        "https://github.com/actions/setup-node",
        "https://github.com/actions/upload-artifact",
        "https://github.com/langfuse/experiment-action",
        "https://github.com/anthropics/claude-code-action",
    }
)
ACTION_USE = re.compile(
    r"(?m)^\s*-\s*uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
    r"(?:/[^\s@]+)?@[^\s#]+"
)
SERVICE_REPOSITORY_MARKERS = (
    (
        "https://" + "json.schemastore.org/",
        "https://github.com/SchemaStore/schemastore",
    ),
)
FALLBACK_IGNORED_DIRECTORIES = frozenset(
    {
        ".agent-local",
        ".codex",
        ".codex-log",
        ".codex-run",
        ".git",
        ".next",
        ".playwright-mcp",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
    }
)
FALLBACK_IGNORED_PATH_PREFIXES = frozenset(
    {(".claude", "skills"), (".claude", "worktrees")}
)
FALLBACK_IGNORED_FILENAMES = frozenset(
    {".ds_store", "claude.local.md", "thumbs.db"}
)
FALLBACK_IGNORED_SUFFIXES = frozenset(
    {".db", ".pyc", ".sqlite", ".sqlite3"}
)


class BoundedErrors(list[str]):
    """Collect deterministic diagnostics without allowing adversarial growth."""

    _cap_message = f"validation error cap reached: {MAX_VALIDATION_ERRORS}"

    def append(self, item: str) -> None:
        if len(self) < MAX_VALIDATION_ERRORS - 1:
            super().append(item)
        elif len(self) == MAX_VALIDATION_ERRORS - 1:
            super().append(self._cap_message)

    def extend(self, items: Iterable[str]) -> None:
        for item in items:
            self.append(item)


def _run_git_inventory(root: Path, arguments: list[str], cap: int) -> tuple[int, bytes]:
    clean_environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    completed = run_bounded(
        ["git", "-C", str(root), *arguments],
        cwd=root,
        timeout_seconds=10,
        output_limit=cap,
        env=clean_environment,
    )
    return completed.returncode, completed.output


def _git_public_paths(root: Path, errors: BoundedErrors) -> list[Path] | None:
    """Return tracked plus untracked nonignored paths for an exact repository root."""

    try:
        code, raw_root = _run_git_inventory(root, ["rev-parse", "--show-toplevel"], 4_096)
    except (OutputLimitExceeded, subprocess.TimeoutExpired):
        errors.append("Git publication root probe exceeded its resource budget")
        return []
    except OSError:
        return None
    if code != 0:
        return None
    if len(raw_root) > 4_096:
        errors.append("Git publication root output exceeded its cap")
        return []
    try:
        reported_root = Path(os.fsdecode(raw_root).strip())
        exact_root = Path(os.path.abspath(root)).resolve(strict=True)
        if not reported_root.is_absolute() or reported_root.resolve(strict=True) != exact_root:
            return None
    except (OSError, RuntimeError, ValueError):
        errors.append("Git publication inventory returned an invalid repository root")
        return []

    try:
        code, raw_paths = _run_git_inventory(
            exact_root,
            ["ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            MAX_GIT_INVENTORY_BYTES,
        )
    except OutputLimitExceeded:
        errors.append(
            f"Git publication inventory exceeded {MAX_GIT_INVENTORY_BYTES} bytes"
        )
        return []
    except subprocess.TimeoutExpired:
        errors.append("Git publication inventory exceeded its time budget")
        return []
    except OSError:
        errors.append("Git publication inventory failed")
        return []
    if code != 0:
        errors.append("Git publication inventory returned a failure")
        return []
    if len(raw_paths) > MAX_GIT_INVENTORY_BYTES:
        errors.append(
            f"Git publication inventory exceeded {MAX_GIT_INVENTORY_BYTES} bytes"
        )
        return []
    if not raw_paths:
        return []
    if not raw_paths.endswith(b"\0"):
        errors.append("Git publication inventory was not NUL terminated")
        return []

    try:
        deleted_code, raw_deleted = _run_git_inventory(
            exact_root,
            ["ls-files", "-z", "--deleted"],
            MAX_GIT_INVENTORY_BYTES,
        )
    except OutputLimitExceeded:
        errors.append(
            f"Git deleted-path inventory exceeded {MAX_GIT_INVENTORY_BYTES} bytes"
        )
        return []
    except subprocess.TimeoutExpired:
        errors.append("Git deleted-path inventory exceeded its time budget")
        return []
    except OSError:
        errors.append("Git deleted-path inventory failed")
        return []
    if deleted_code != 0:
        errors.append("Git deleted-path inventory returned a failure")
        return []
    if raw_deleted and not raw_deleted.endswith(b"\0"):
        errors.append("Git deleted-path inventory was not NUL terminated")
        return []
    deleted_paths = {
        os.fsdecode(raw_relative)
        for raw_relative in raw_deleted[:-1].split(b"\0")
        if raw_relative
    }

    public_paths: list[Path] = []
    seen: set[str] = set()
    for raw_relative in raw_paths[:-1].split(b"\0"):
        if len(public_paths) >= MAX_PUBLIC_FILES:
            errors.append(f"public file cap exceeded: more than {MAX_PUBLIC_FILES}")
            return []
        relative_text = os.fsdecode(raw_relative)
        if relative_text in deleted_paths:
            continue
        relative = Path(relative_text)
        if (
            not relative_text
            or relative.is_absolute()
            or ".." in relative.parts
            or relative_text in seen
        ):
            errors.append("Git publication inventory contained an unsafe or duplicate path")
            return []
        seen.add(relative_text)
        public_paths.append(exact_root / relative)
    return public_paths


def _fallback_ignored(relative: Path, *, directory: bool) -> bool:
    lowered = tuple(part.lower() for part in relative.parts)
    name = lowered[-1] if lowered else ""
    if directory and (
        name in FALLBACK_IGNORED_DIRECTORIES
        or any(lowered[: len(prefix)] == prefix for prefix in FALLBACK_IGNORED_PATH_PREFIXES)
    ):
        return True
    if directory:
        return False
    return (
        (name == ".env" or (name.startswith(".env.") and name != ".env.example"))
        or name in FALLBACK_IGNORED_FILENAMES
        or lowered == (".claude", "settings.local.json")
        or Path(name).suffix in FALLBACK_IGNORED_SUFFIXES
        or any(lowered[: len(prefix)] == prefix for prefix in FALLBACK_IGNORED_PATH_PREFIXES)
        or any(part in FALLBACK_IGNORED_DIRECTORIES for part in lowered)
    )


def _accept_public_file(root: Path, path: Path, errors: BoundedErrors) -> bool:
    try:
        reject_linked_path(path, root, label="publication")
        metadata = path.lstat()
    except (OSError, ValueError):
        errors.append(f"linked or unavailable publication input: {path.relative_to(root)}")
        return False
    if is_link_like(path):
        errors.append(f"linked file is not portable publication input: {path.relative_to(root)}")
        return False
    if not stat.S_ISREG(metadata.st_mode):
        errors.append(f"non-regular publication input: {path.relative_to(root)}")
        return False
    if metadata.st_size > MAX_PUBLIC_FILE_BYTES:
        errors.append(
            f"public file exceeds {MAX_PUBLIC_FILE_BYTES}-byte scan cap: {path.relative_to(root)}"
        )
        return False
    return True


def collect_public_files(root: Path, errors: BoundedErrors) -> list[Path]:
    """Inventory publishable files through Git, with an exact-ignore no-Git fallback."""

    root = Path(os.path.abspath(root))
    public_files: list[Path] = []
    entries_seen = 0
    if is_link_like(root):
        errors.append("linked repository root is not portable publication input")
        return public_files
    git_paths = _git_public_paths(root, errors)
    if git_paths is not None:
        for path in git_paths:
            if _accept_public_file(root, path, errors):
                public_files.append(path)
        return public_files

    for current, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        try:
            reject_linked_path(current_path, root, label="publication")
        except (OSError, ValueError):
            errors.append(
                f"linked directory is not portable publication input: {current_path.relative_to(root)}"
            )
            directory_names[:] = []
            continue
        kept_directories: list[str] = []
        for name in sorted(directory_names):
            candidate = current_path / name
            relative = candidate.relative_to(root)
            if _fallback_ignored(relative, directory=True):
                continue
            entries_seen += 1
            if entries_seen > MAX_PUBLIC_FILES:
                errors.append(f"public file cap exceeded: more than {MAX_PUBLIC_FILES}")
                return public_files
            if is_link_like(candidate):
                errors.append(
                    f"linked directory is not portable publication input: {candidate.relative_to(root)}"
                )
                continue
            kept_directories.append(name)
        directory_names[:] = kept_directories

        for name in sorted(file_names):
            path = current_path / name
            relative = path.relative_to(root)
            if _fallback_ignored(relative, directory=False):
                continue
            entries_seen += 1
            if entries_seen > MAX_PUBLIC_FILES:
                errors.append(f"public file cap exceeded: more than {MAX_PUBLIC_FILES}")
                return public_files
            if _accept_public_file(root, path, errors):
                public_files.append(path)
    return public_files


def read_text(path: Path) -> str:
    candidate = Path(os.path.abspath(path))
    content = read_regular_file_bounded(
        candidate,
        MAX_PUBLIC_FILE_BYTES,
        boundary=Path(candidate.anchor),
        label="publication input",
    )
    return content.decode("utf-8")


def normalize_repo_url(url: str) -> str:
    if not isinstance(url, str) or not url:
        raise ValueError("repository URL must be a non-empty string")
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if (
        parsed.scheme != "https"
        or parsed.netloc.lower() != "github.com"
        or len(parts) != 2
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"not a GitHub repository URL: {url}")
    normalized = f"https://github.com/{parts[0]}/{parts[1].removesuffix('.git')}"
    candidate = url[:-1] if url.endswith("/") else url
    if candidate.endswith(".git"):
        candidate = candidate[:-4]
    if candidate != normalized:
        raise ValueError(f"not a canonical GitHub repository root URL: {url}")
    return normalized


def normalize_doc_url(url: str) -> str:
    if not isinstance(url, str) or not url:
        raise ValueError("official document URL must be a non-empty string")
    parsed = urlparse(url.rstrip(".,;"))
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_EXTERNAL_HOSTS:
        raise ValueError(f"official document is not on the HTTPS allowlist: {url}")
    return parsed._replace(fragment="").geturl()


def render_external_project_row(project: dict[str, object]) -> str:
    """Render one exact human-ledger row from validated machine fields."""

    details = [f"Evidence: {project['evidence']}"]
    if "revision" in project:
        details.append(f"Revision: {project['revision']}")
    if "notes" in project:
        details.append(f"Notes: {project['notes']}")
    return (
        f"| [{project['name']}]({project['repository']}) | "
        f"{project['relationship']} | {project['license']} | "
        f"{project['accessed']} | {'<br>'.join(details)} |"
    )


def is_json_variant(path: Path) -> bool:
    """Return whether a publication file promises JSON syntax."""

    name = path.name.lower()
    return name.endswith(".json") or name.endswith(".json.example")


def parse_json_object(
    content: str,
    label: str,
    errors: BoundedErrors,
) -> dict[str, object] | None:
    """Parse a catalog-like object while converting every bad shape to a diagnostic."""

    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        errors.append(f"invalid {label}: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"invalid {label}: root must be an object")
        return None
    return payload


def is_valid_access_date(value: object) -> bool:
    """Accept only real ISO calendar dates that are not later than today."""

    if not isinstance(value, str):
        return False
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return False
    return parsed <= date.today()


def load_private_marker_rules(
    content: str,
    errors: BoundedErrors,
) -> tuple[tuple[int, str], ...]:
    """Load digest-only marker rules without ever reconstructing their plaintext."""

    payload = parse_json_object(content, "private marker policy", errors)
    if payload is None:
        return ()
    if payload.get("algorithm") != "sha256-lower-nfkc":
        errors.append("invalid private marker policy: unsupported algorithm")
    raw_markers = payload.get("markers")
    if not isinstance(raw_markers, list) or not raw_markers:
        errors.append("invalid private marker policy: markers must be a non-empty array")
        return ()

    rules: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for index, raw_marker in enumerate(raw_markers):
        if not isinstance(raw_marker, dict):
            errors.append(f"invalid private marker policy: marker {index} must be an object")
            continue
        length = raw_marker.get("length")
        digest = raw_marker.get("digest")
        if isinstance(length, bool) or not isinstance(length, int) or not 1 <= length <= 128:
            errors.append(f"invalid private marker policy: marker {index} has invalid length")
            continue
        if not isinstance(digest, str) or HEX_DIGEST.fullmatch(digest) is None:
            errors.append(f"invalid private marker policy: marker {index} has invalid digest")
            continue
        rule = (length, digest)
        if rule in seen:
            errors.append(f"invalid private marker policy: duplicate marker {index}")
            continue
        seen.add(rule)
        rules.append(rule)
    return tuple(sorted(rules))


def find_hashed_private_marker(
    value: str,
    rules: tuple[tuple[int, str], ...],
    remaining_windows: int,
) -> tuple[bool, int, bool]:
    """Scan normalized token windows within a caller-owned, global work budget."""

    normalized = unicodedata.normalize("NFKC", value).lower()
    windows_used = 0
    token_streams = (match.group(0) for match in PRIVATE_MARKER_TOKEN.finditer(normalized))
    collapsed = "".join(character for character in normalized if character.isalnum())
    for token in chain(token_streams, (collapsed,)):
        if not token:
            continue
        for length, digest in rules:
            if len(token) < length:
                continue
            for offset in range(len(token) - length + 1):
                if windows_used >= remaining_windows:
                    return False, windows_used, True
                candidate = token[offset : offset + length]
                windows_used += 1
                if hashlib.sha256(candidate.encode("utf-8")).hexdigest() == digest:
                    return True, windows_used, False
    return False, windows_used, False


def validate_private_markers(
    root: Path,
    texts: dict[Path, str],
    errors: BoundedErrors,
) -> tuple[tuple[int, str], ...]:
    """Reject digest-listed terms in paths or content with bounded, redacted output."""

    policy_path = root / "sources/private-marker-hashes.json"
    policy_content = texts.get(policy_path)
    if policy_content is None:
        return ()
    rules = load_private_marker_rules(policy_content, errors)
    if not rules:
        return ()

    remaining = MAX_PRIVATE_MARKER_WINDOWS
    for path in sorted(texts):
        relative = path.relative_to(root).as_posix()
        matched_path, used, exceeded = find_hashed_private_marker(relative, rules, remaining)
        remaining -= used
        if exceeded:
            errors.append(
                f"private marker scan cap exceeded: more than {MAX_PRIVATE_MARKER_WINDOWS} windows"
            )
            return rules
        if matched_path:
            path_digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:12]
            errors.append(f"private-source marker present in publication path: id={path_digest}")
            continue

        matched_content, used, exceeded = find_hashed_private_marker(
            texts[path], rules, remaining
        )
        remaining -= used
        if exceeded:
            errors.append(
                f"private marker scan cap exceeded: more than {MAX_PRIVATE_MARKER_WINDOWS} windows"
            )
            return rules
        if matched_content:
            errors.append(f"private-source marker present in content: {relative}")
    return rules


def redact_private_marker_diagnostics(
    diagnostics: Iterable[str],
    rules: tuple[tuple[int, str], ...],
) -> list[str]:
    """Fail closed if another validator diagnostic would echo marker plaintext."""

    if not rules:
        return list(diagnostics)
    redacted: list[str] = []
    remaining = MAX_PRIVATE_MARKER_WINDOWS
    for diagnostic in diagnostics:
        matched, used, exceeded = find_hashed_private_marker(diagnostic, rules, remaining)
        remaining -= used
        if exceeded:
            redacted.append("validation diagnostics withheld: private marker scan cap exceeded")
            return redacted
        if matched:
            diagnostic_id = hashlib.sha256(diagnostic.encode("utf-8")).hexdigest()[:12]
            redacted.append(f"validation diagnostic withheld: id={diagnostic_id}")
        else:
            redacted.append(diagnostic)
    return redacted


def parse_skill_frontmatter(content: str) -> dict[str, str] | None:
    """Parse the flat name/description frontmatter required by portable skills."""

    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        closing = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return None
    fields: dict[str, str] = {}
    for line in lines[1:closing]:
        if not line.strip() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    return fields


def validate_host_capabilities(
    root: Path,
    texts: dict[Path, str],
    errors: BoundedErrors,
) -> None:
    """Require an explicit, drift-free capability record for all three hosts."""

    path = root / "sources/host-capabilities.json"
    content = texts.get(path)
    if content is None:
        return
    payload = parse_json_object(content, "host capability catalog", errors)
    if payload is None:
        return
    raw_hosts = payload.get("hosts")
    if not isinstance(raw_hosts, list):
        errors.append("invalid host capability catalog: hosts must be an array")
        return

    names: list[str] = []
    for index, host in enumerate(raw_hosts):
        if not isinstance(host, dict):
            errors.append(f"invalid host capability catalog: host {index} must be an object")
            continue
        name = host.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"invalid host capability catalog: host {index} needs a name")
            continue
        names.append(name)
        expected = EXPECTED_HOST_CAPABILITIES.get(name)
        if expected is None:
            continue
        expected_keys = {"name", *expected}
        observed_keys = set(host)
        missing_fields = sorted(expected_keys - observed_keys)
        extra_fields = sorted(observed_keys - expected_keys)
        if missing_fields:
            errors.append(
                f"host capability drift: {name} missing fields={','.join(missing_fields)}"
            )
        if extra_fields:
            errors.append(
                f"host capability drift: {name} extra fields={','.join(extra_fields)}"
            )
        for field, expected_value in expected.items():
            if host.get(field) != expected_value or type(host.get(field)) is not type(expected_value):
                errors.append(f"host capability drift: {name}.{field} does not match")
    if len(names) != len(set(names)):
        errors.append("host capability catalog contains duplicate host names")
    observed = set(names)
    if observed != EXPECTED_HOSTS:
        missing = ", ".join(sorted(EXPECTED_HOSTS - observed)) or "none"
        extra = ", ".join(sorted(observed - EXPECTED_HOSTS)) or "none"
        errors.append(f"host capability drift: missing={missing}; extra={extra}")


def validate_skill_catalog(
    root: Path,
    texts: dict[Path, str],
    errors: BoundedErrors,
) -> None:
    """Cross-check the canonical skill manifest, directories, and host metadata."""

    manifest_path = root / "sources/skills.json"
    content = texts.get(manifest_path)
    if content is None:
        return
    payload = parse_json_object(content, "skill catalog", errors)
    if payload is None:
        return
    if payload.get("canonical_root") != "templates/project/.agents/skills":
        errors.append("invalid skill catalog: canonical_root must name the portable skill tree")

    raw_skills = payload.get("skills")
    if not isinstance(raw_skills, list):
        errors.append("invalid skill catalog: skills must be an array")
        return
    if not all(isinstance(value, str) and value for value in raw_skills):
        errors.append("invalid skill catalog: every skill name must be a non-empty string")
        manifest_names = {value for value in raw_skills if isinstance(value, str) and value}
    else:
        manifest_names = set(raw_skills)
    if len(raw_skills) != len(manifest_names):
        errors.append("skill catalog contains duplicate or invalid names")
    if len(manifest_names) != EXPECTED_SKILL_COUNT:
        errors.append(
            f"skill catalog must contain exactly {EXPECTED_SKILL_COUNT} skills; "
            f"found {len(manifest_names)}"
        )

    skill_root = root / "templates/project/.agents/skills"
    try:
        skill_directories = sorted(path for path in skill_root.iterdir() if path.is_dir())
    except OSError as exc:
        errors.append(f"cannot inspect canonical skill tree: {exc}")
        return
    directory_names = {path.name for path in skill_directories}
    if directory_names != manifest_names:
        missing = ", ".join(sorted(manifest_names - directory_names)) or "none"
        extra = ", ".join(sorted(directory_names - manifest_names)) or "none"
        errors.append(f"skill manifest drift: missing_directories={missing}; extra_directories={extra}")
    if len(directory_names) != EXPECTED_SKILL_COUNT:
        errors.append(
            f"canonical skill tree must contain exactly {EXPECTED_SKILL_COUNT} directories; "
            f"found {len(directory_names)}"
        )

    for directory in skill_directories:
        skill_name = directory.name
        skill_path = directory / "SKILL.md"
        skill_content = texts.get(skill_path)
        if skill_content is None:
            errors.append(f"skill is missing SKILL.md: {skill_name}")
        else:
            if len(skill_content.splitlines()) >= 100:
                errors.append(f"skill SKILL.md must be under 100 lines: {skill_name}")
            frontmatter = parse_skill_frontmatter(skill_content)
            if frontmatter is None:
                errors.append(f"skill has invalid frontmatter: {skill_name}")
            else:
                if frontmatter.get("name") != skill_name:
                    errors.append(f"skill frontmatter name does not match folder: {skill_name}")
                if not frontmatter.get("description"):
                    errors.append(f"skill frontmatter needs a description: {skill_name}")

        metadata_path = directory / "agents/openai.yaml"
        metadata_content = texts.get(metadata_path)
        if metadata_content is None:
            errors.append(f"skill is missing agents/openai.yaml: {skill_name}")
            continue
        try:
            metadata = json.loads(metadata_content)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(metadata, dict):
            errors.append(f"skill openai.yaml root must be an object: {skill_name}")
            continue
        interface = metadata.get("interface")
        default_prompt = interface.get("default_prompt") if isinstance(interface, dict) else None
        if not isinstance(default_prompt, str) or f"${skill_name}" not in default_prompt:
            errors.append(f"skill openai.yaml default_prompt must invoke ${skill_name}")

        contract_path = directory / "references/contract.json"
        contract_content = texts.get(contract_path)
        if contract_content is None:
            errors.append(f"skill is missing references/contract.json: {skill_name}")
            continue
        contract = parse_json_object(
            contract_content,
            f"skill contract {skill_name}",
            errors,
        )
        if contract is None:
            continue
        for error in validate_skill_receipt.validate_contract(contract):
            errors.append(f"skill contract {skill_name}: {error}")
        if contract.get("skill") != skill_name:
            errors.append(f"skill contract name does not match folder: {skill_name}")
        if "references/contract.json" not in (skill_content or ""):
            errors.append(f"skill does not link its execution contract: {skill_name}")
        if "parameterized `verification.argv`" not in (skill_content or ""):
            errors.append(f"skill does not explain its receipt validator argv: {skill_name}")

    scaffold = root / "templates/skill"
    scaffold_text = texts.get(scaffold / "SKILL.md")
    scaffold_contract_text = texts.get(scaffold / "references/contract.json")
    scaffold_metadata_text = texts.get(scaffold / "agents/openai.yaml")
    if scaffold_text is not None:
        if len(scaffold_text.splitlines()) >= 100:
            errors.append("skill scaffold SKILL.md must be under 100 lines")
        frontmatter = parse_skill_frontmatter(scaffold_text)
        if frontmatter is None or frontmatter.get("name") != "example-proof":
            errors.append("skill scaffold frontmatter must name example-proof")
        if frontmatter is not None and not frontmatter.get("description"):
            errors.append("skill scaffold frontmatter needs a description")
        if "references/contract.json" not in scaffold_text:
            errors.append("skill scaffold must link its execution contract")
        if "parameterized `verification.argv`" not in scaffold_text:
            errors.append("skill scaffold must explain its receipt validator argv")
    if scaffold_contract_text is not None:
        contract = parse_json_object(scaffold_contract_text, "skill scaffold contract", errors)
        if contract is not None:
            for error in validate_skill_receipt.validate_contract(contract):
                errors.append(f"skill scaffold contract: {error}")
            if contract.get("skill") != "example-proof":
                errors.append("skill scaffold contract must name example-proof")
    if scaffold_metadata_text is not None:
        metadata = parse_json_object(scaffold_metadata_text, "skill scaffold metadata", errors)
        interface = metadata.get("interface") if metadata is not None else None
        prompt = interface.get("default_prompt") if isinstance(interface, dict) else None
        if not isinstance(prompt, str) or "$example-proof" not in prompt:
            errors.append("skill scaffold metadata must invoke $example-proof")


def validate_inert_templates(
    root: Path,
    texts: dict[Path, str],
    errors: BoundedErrors,
) -> None:
    """Fail when a copy-by-default host adapter would start executable tooling."""

    for relative in ("templates/project/.mcp.json", "templates/cursor/mcp.json"):
        content = texts.get(root / relative)
        if content is None:
            continue
        payload = parse_json_object(content, f"inactive MCP template {relative}", errors)
        servers = payload.get("mcpServers") if payload is not None else None
        if not isinstance(servers, dict) or servers:
            errors.append(f"active MCP server in copy-by-default template: {relative}")

    for relative in (
        "templates/project/.mcp.json.example",
        "templates/cursor/mcp.json.example",
    ):
        content = texts.get(root / relative)
        if content is None:
            continue
        payload = parse_json_object(content, f"MCP opt-in template {relative}", errors)
        servers = payload.get("mcpServers") if payload is not None else None
        is_claude = relative.startswith("templates/project/")
        local_name = "[PROJECT_SLUG]-tools" if is_claude else "project-tools"
        local = servers.get(local_name) if isinstance(servers, dict) else None
        if is_claude and isinstance(servers, dict) and set(servers) != {
            "[PROJECT_SLUG]-tools",
            "[PROJECT_SLUG]-remote-token",
        }:
            errors.append("Claude MCP example must use repository-specific server IDs")
        if not isinstance(local, dict) or local.get("command") != "[PYTHON_EXECUTABLE]":
            errors.append(f"MCP example must require an explicit Python launcher: {relative}")
        expected_entrypoint = (
            "${CLAUDE_PROJECT_DIR:-.}/[PROJECT_MCP_ENTRYPOINT]"
            if is_claude
            else "${workspaceFolder}/[PROJECT_MCP_ENTRYPOINT]"
        )
        if not isinstance(local, dict) or local.get("args") != [expected_entrypoint]:
            errors.append(f"MCP example must anchor its project entrypoint: {relative}")

    claude_relative = "templates/claude/settings.json"
    claude_content = texts.get(root / claude_relative)
    if claude_content is not None:
        payload = parse_json_object(
            claude_content,
            f"inactive hook template {claude_relative}",
            errors,
        )
        hooks = payload.get("hooks") if payload is not None else None
        if hooks not in (None, {}):
            errors.append(f"active hooks in copy-by-default template: {claude_relative}")
        permissions = payload.get("permissions") if payload is not None else None
        deny = permissions.get("deny") if isinstance(permissions, dict) else None
        required_claude_denials = {"Read(/**/.env*)", "Read(/**/secrets/**)"}
        if not isinstance(deny, list) or not required_claude_denials.issubset(deny):
            errors.append(
                "Claude settings example is missing recursive project-secret denials"
            )

    for codex_relative in (
        "templates/codex/config.toml",
        "templates/codex/project.config.toml",
    ):
        codex_content = texts.get(root / codex_relative)
        if codex_content is None:
            continue
        try:
            payload = tomllib.loads(codex_content)
        except tomllib.TOMLDecodeError:
            continue
        servers = payload.get("mcp_servers")
        if not isinstance(servers, dict) or not servers:
            errors.append(f"disabled MCP example missing from template: {codex_relative}")
            continue
        for name, server in servers.items():
            if not isinstance(server, dict) or server.get("enabled") is not False:
                errors.append(
                    f"active MCP server in copy-by-default template: {codex_relative} ({name})"
                )
        local_name = "project_tools" if codex_relative.endswith("project.config.toml") else "example_local"
        local_server = servers.get(local_name)
        if not isinstance(local_server, dict) or local_server.get("command") != "[PYTHON_EXECUTABLE]":
            errors.append(f"Codex MCP example must require an explicit Python launcher: {codex_relative}")
        if (
            codex_relative.endswith("project.config.toml")
            and isinstance(local_server, dict)
            and local_server.get("cwd") != "[ABSOLUTE_PROJECT_ROOT]"
        ):
            errors.append("Codex project MCP example must bind its working directory to the project root")
        if (
            codex_relative.endswith("project.config.toml")
            and isinstance(local_server, dict)
            and local_server.get("args") != ["-m", "[PROJECT_MCP_MODULE]"]
        ):
            errors.append("Codex project MCP example must require an explicit project module")

    cursor_cli_examples = (
        ("templates/cursor/cli-config.json.example", True),
        ("templates/cursor/cli.json.example", False),
    )
    required_denials = {
        "Read(**/.env*)",
        "Write(**/.env*)",
        "Write(**/*.key)",
    }
    for relative, is_global in cursor_cli_examples:
        content = texts.get(root / relative)
        if content is None:
            continue
        payload = parse_json_object(content, f"Cursor CLI template {relative}", errors)
        if payload is None:
            continue
        allowed_keys = {"version", "permissions"}
        if is_global:
            allowed_keys.update({"editor", "approvalMode"})
        if set(payload) != allowed_keys or payload.get("version") != 1:
            errors.append(f"Cursor CLI template has an unexpected shape: {relative}")
        permissions = payload.get("permissions")
        allow = permissions.get("allow") if isinstance(permissions, dict) else None
        deny = permissions.get("deny") if isinstance(permissions, dict) else None
        if isinstance(permissions, dict) and set(permissions) != {"allow", "deny"}:
            errors.append(f"{relative} permissions must contain exactly allow and deny")
        if allow != []:
            errors.append(f"Cursor CLI example allowlist must start empty: {relative}")
        if not isinstance(deny, list) or not required_denials.issubset(deny):
            errors.append(f"Cursor CLI example is missing baseline denials: {relative}")
        if is_global and payload.get("approvalMode") != "allowlist":
            errors.append("Cursor CLI global example must use allowlist approval mode")

    cursor_permissions_relative = "templates/cursor/permissions.json.example"
    cursor_permissions_content = texts.get(root / cursor_permissions_relative)
    if cursor_permissions_content is not None:
        payload = parse_json_object(
            cursor_permissions_content,
            f"Cursor Desktop permissions template {cursor_permissions_relative}",
            errors,
        )
        expected_block_instructions = [
            "Do not read, write, print, copy, or transmit any .env file.",
            "Do not read, write, print, copy, or transmit files under any secrets directory.",
            "Do not read, write, print, copy, or transmit private key files.",
        ]
        if payload is not None:
            if set(payload) != {"mcpAllowlist", "terminalAllowlist", "autoRun"}:
                errors.append("Cursor Desktop permissions template has an unexpected shape")
            if payload.get("mcpAllowlist") != [] or payload.get("terminalAllowlist") != []:
                errors.append("Cursor Desktop permission allowlists must start empty")
            auto_run = payload.get("autoRun")
            if not isinstance(auto_run, dict) or set(auto_run) != {
                "allow_instructions",
                "block_instructions",
            }:
                errors.append("Cursor Desktop autoRun policy has an unexpected shape")
            if isinstance(auto_run, dict):
                if auto_run.get("allow_instructions") != []:
                    errors.append("Cursor Desktop autoRun allow instructions must start empty")
                if auto_run.get("block_instructions") != expected_block_instructions:
                    errors.append("Cursor Desktop permissions are missing baseline secret blocks")

    cursor_sandbox_relative = "templates/cursor/sandbox.json.example"
    cursor_sandbox_content = texts.get(root / cursor_sandbox_relative)
    if cursor_sandbox_content is not None:
        payload = parse_json_object(
            cursor_sandbox_content,
            f"Cursor Desktop sandbox template {cursor_sandbox_relative}",
            errors,
        )
        expected_keys = {
            "type",
            "additionalReadwritePaths",
            "additionalReadonlyPaths",
            "disableTmpWrite",
            "enableSharedBuildCache",
            "networkPolicy",
        }
        if payload is not None:
            if set(payload) != expected_keys:
                errors.append("Cursor Desktop sandbox template has an unexpected shape")
            if payload.get("type") != "workspace_readwrite":
                errors.append("Cursor Desktop sandbox must stay workspace-scoped")
            if (
                payload.get("additionalReadwritePaths") != []
                or payload.get("additionalReadonlyPaths") != []
            ):
                errors.append("Cursor Desktop sandbox must not grant extra filesystem paths")
            if payload.get("disableTmpWrite") is not False:
                errors.append("Cursor Desktop sandbox disableTmpWrite must be boolean false")
            if payload.get("enableSharedBuildCache") is not False:
                errors.append("Cursor Desktop sandbox shared build cache must start disabled")
            network_policy = payload.get("networkPolicy")
            if not isinstance(network_policy, dict) or set(network_policy) != {
                "default",
                "allow",
                "deny",
            }:
                errors.append("Cursor Desktop sandbox network policy has an unexpected shape")
            elif (
                network_policy.get("default") != "deny"
                or network_policy.get("allow") != []
                or network_policy.get("deny") != []
            ):
                errors.append("Cursor Desktop sandbox network policy must start deny-by-default")

    personal_content = texts.get(root / "templates/global/WORKING_AGREEMENTS.md")
    cursor_personal = texts.get(root / "templates/cursor/working-agreements.mdc")
    if personal_content is not None and cursor_personal is not None:
        body_start = personal_content.find("## Modes")
        expected_frontmatter = (
            "---\n"
            "description: Personal working agreements for Cursor Agent\n"
            "globs:\n"
            "alwaysApply: true\n"
            "---\n\n"
        )
        if body_start < 0 or cursor_personal != expected_frontmatter + personal_content[body_start:]:
            errors.append(
                "Cursor personal rule must be an .mdc file with always-apply frontmatter "
                "and the canonical working-agreement body"
            )

    required_ignores = {
        "__pycache__/",
        "*.py[cod]",
        ".pytest_cache/",
        ".agent-local/",
        ".claude/settings.local.json",
        ".claude/skills/",
        ".claude/worktrees/",
        "CLAUDE.local.md",
        ".env",
        ".env.*",
        "!.env.example",
    }
    for relative in (".gitignore", "templates/project/.gitignore"):
        content = texts.get(root / relative)
        if content is None:
            continue
        entries = {
            line.strip()
            for line in content.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        for missing in sorted(required_ignores - entries):
            errors.append(f"publication ignore missing {missing}: {relative}")

    preflight_content = texts.get(root / "templates/harness/preflight.json")
    if preflight_content is not None:
        payload = parse_json_object(preflight_content, "kit preflight", errors)
        checks = payload.get("checks") if payload is not None else None
        runtime = checks.get("runtime") if isinstance(checks, dict) else None
        minimum = runtime.get("minimum_python") if isinstance(runtime, dict) else None
        if minimum != EXPECTED_MINIMUM_PYTHON:
            errors.append(
                f"kit preflight minimum_python must equal {EXPECTED_MINIMUM_PYTHON}"
            )


def validate_repo(root: Path = ROOT) -> list[str]:
    errors = BoundedErrors()
    for relative in REQUIRED_PATHS:
        if not (root / relative).is_file():
            errors.append(f"missing required file: {relative}")

    public_files = collect_public_files(root, errors)
    for path in public_files:
        if path.name.lower() in FORBIDDEN_FILENAMES:
            errors.append(f"forbidden state file: {path.relative_to(root)}")
        if (
            path.name == ".env"
            or (path.name.startswith(".env.") and path.name != ".env.example")
            or path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}
        ):
            errors.append(f"forbidden local-data file: {path.relative_to(root)}")

    texts: dict[Path, str] = {}
    total_public_bytes = 0
    for path in public_files:
        try:
            discovered_size = path.stat().st_size
        except OSError as exc:
            errors.append(
                f"cannot stat public file {path.relative_to(root)}: {type(exc).__name__}"
            )
            continue
        if total_public_bytes + discovered_size > MAX_PUBLIC_TOTAL_BYTES:
            errors.append(
                f"public byte cap exceeded: more than {MAX_PUBLIC_TOTAL_BYTES} bytes"
            )
            break
        total_public_bytes += discovered_size
        try:
            reject_linked_path(path, root, label="publication input")
            content = read_text(path)
        except (OSError, ValueError) as exc:
            errors.append(f"cannot read public file {path.relative_to(root)}: {exc}")
            continue
        except UnicodeDecodeError:
            errors.append(f"non-UTF-8 or binary publication file: {path.relative_to(root)}")
            continue
        texts[path] = content
        relative = path.relative_to(root)
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(content):
                errors.append(f"possible {label}: {relative}")
        for pattern_index, pattern in enumerate(PERSONAL_PATH_PATTERNS, start=1):
            if pattern.search(content):
                errors.append(
                    f"possible personal absolute path class {pattern_index}: {relative}"
                )

    private_marker_rules = validate_private_markers(root, texts, errors)

    for path, content in texts.items():
        if not is_json_variant(path):
            continue
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSON {path.relative_to(root)}: {exc}")

    for path, content in texts.items():
        if path.name != "openai.yaml" or path.parent.name != "agents":
            continue
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSON-subset YAML {path.relative_to(root)}: {exc}")

    for path, content in texts.items():
        if path.suffix.lower() != ".toml":
            continue
        try:
            tomllib.loads(content)
        except tomllib.TOMLDecodeError as exc:
            errors.append(f"invalid TOML {path.relative_to(root)}: {exc}")

    for relative in (".claude/CLAUDE.md", "templates/project/.claude/CLAUDE.md"):
        content = texts.get(root / relative)
        if content is not None and content.strip() != "@../AGENTS.md":
            errors.append(
                f"{relative} must contain only the @../AGENTS.md shared import"
            )
    for relative in ("CLAUDE.md", "templates/project/CLAUDE.md"):
        if (root / relative).exists():
            errors.append(f"root-level Claude compatibility file is forbidden: {relative}")

    invariant_content = texts.get(root / "templates/project/AGENT_INVARIANTS.md")
    if invariant_content is not None:
        invariant_numbers = [
            int(match.group(1))
            for line in invariant_content.splitlines()
            if (match := re.match(r"^(\d+)\. \*\*", line)) is not None
        ]
        if invariant_numbers != list(range(1, 23)):
            errors.append("portable invariants must be numbered exactly 1 through 22")

    validate_host_capabilities(root, texts, errors)
    validate_skill_catalog(root, texts, errors)
    validate_inert_templates(root, texts, errors)

    workflow = texts.get(root / ".github/workflows/validate.yml", "")
    history_job = re.search(
        r"(?ms)^  history:\s*$.*?(?=^  [A-Za-z0-9_-]+:\s*$|\Z)", workflow
    )
    if history_job is None:
        errors.append("validation workflow is missing the reachable-history job")
    else:
        history_text = history_job.group(0)
        if "fetch-depth: 0" not in history_text:
            errors.append("reachable-history job must use a full checkout")
        if "python scripts/check_private_history.py" not in history_text:
            errors.append("reachable-history job is missing its marker gate")
    offline_job = re.search(
        r"(?ms)^  offline:\s*$.*?(?=^  [A-Za-z0-9_-]+:\s*$|\Z)", workflow
    )
    if offline_job is None or "fetch-depth: 2" not in offline_job.group(0):
        errors.append("offline shape-version job must fetch at least two commits")
    external_job = re.search(
        r"(?ms)^  external-links:\s*$.*?(?=^  [A-Za-z0-9_-]+:\s*$|\Z)", workflow
    )
    if external_job is None:
        errors.append("validation workflow is missing the external-links job")
    else:
        timeout_match = re.search(r"(?m)^    timeout-minutes: (\d+)\s*$", external_job.group(0))
        minimum_external_seconds = EXTERNAL_AGGREGATE_SECONDS + TIMEOUT_SECONDS + 63
        if (
            timeout_match is None
            or int(timeout_match.group(1)) * 60 < minimum_external_seconds
        ):
            errors.append("external-links job timeout is below the bounded batch budget")

    for path, content in texts.items():
        if path.suffix.lower() != ".md":
            continue
        for raw_target in MARKDOWN_LINK.findall(content):
            target = raw_target.strip().strip("<>").split("#", 1)[0]
            if not target or urlparse(target).scheme or target.startswith("#"):
                continue
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                errors.append(f"local link escapes repository: {path.relative_to(root)} -> {target}")
                continue
            if not resolved.exists():
                errors.append(f"broken local link: {path.relative_to(root)} -> {target}")

    external_path = root / "sources/external-projects.json"
    historical_actions_path = root / "sources/historical-action-uses.json"
    official_path = root / "sources/official-docs.json"
    catalog_repos: set[str] = set()
    external_projects: list[dict[str, object]] = []
    if external_path in texts:
        payload = parse_json_object(
            texts[external_path], "external project catalog", errors
        )
        if payload is not None and set(payload) != {
            "schema_version",
            "accessed",
            "scope",
            "methodology",
            "license_notice",
            "projects",
        }:
            errors.append("external project catalog has an unexpected shape")
        if payload is not None and payload.get("schema_version") != 1:
            errors.append("external project catalog schema_version must equal 1")
        if payload is not None and not is_valid_access_date(payload.get("accessed")):
            errors.append("external project catalog has an invalid or future access date")
        for field in ("scope", "license_notice"):
            if payload is not None and (
                not isinstance(payload.get(field), str) or not payload[field].strip()
            ):
                errors.append(f"external project catalog {field} must be non-empty text")
        projects = payload.get("projects") if payload is not None else None
        if payload is not None and not isinstance(projects, list):
            errors.append("invalid external project catalog: projects must be an array")
        if isinstance(projects, list):
            catalog_repo_keys: set[str] = set()
            for index, project in enumerate(projects):
                if not isinstance(project, dict):
                    errors.append(f"external project {index} must be an object")
                    continue
                required_project_fields = {
                    "name",
                    "repository",
                    "category",
                    "relationship",
                    "license",
                    "accessed",
                    "evidence",
                    "confidence",
                }
                allowed_project_fields = required_project_fields | {"notes", "revision", "check"}
                missing = sorted(required_project_fields - project.keys())
                extra = sorted(project.keys() - allowed_project_fields)
                if missing:
                    errors.append(f"external project {index} missing: {', '.join(missing)}")
                    continue
                if extra:
                    errors.append(f"external project {index} has unknown fields: {', '.join(extra)}")
                for field in required_project_fields:
                    if not isinstance(project.get(field), str) or not project[field]:
                        errors.append(
                            f"external project {index} field {field} must be a non-empty string"
                        )
                accessed = project.get("accessed")
                if not is_valid_access_date(accessed):
                    errors.append(f"external project {index} has invalid or future access date")
                if project.get("category") not in EXTERNAL_CATEGORIES:
                    errors.append(f"external project {index} has invalid category")
                if project.get("confidence") not in EXTERNAL_CONFIDENCE:
                    errors.append(f"external project {index} has invalid confidence")
                for optional_field in ("notes", "revision"):
                    if optional_field in project and (
                        not isinstance(project[optional_field], str)
                        or not project[optional_field].strip()
                    ):
                        errors.append(
                            f"external project {index} has invalid {optional_field}"
                        )
                if not isinstance(project.get("check", True), bool):
                    errors.append(f"external project {index} has non-boolean check flag")
                if project.get("check") is False and not project.get("notes"):
                    errors.append(f"external project {index} skips checks without a note")
                try:
                    normalized = normalize_repo_url(project["repository"])
                except (KeyError, TypeError, ValueError) as exc:
                    errors.append(f"external project {index} has invalid repository: {exc}")
                    continue
                normalized_key = normalized.lower()
                if normalized_key in catalog_repo_keys:
                    errors.append(f"duplicate external repository: {normalized}")
                catalog_repo_keys.add(normalized_key)
                catalog_repos.add(normalized)
                external_projects.append(project)

            methodology = payload.get("methodology") if payload is not None else None
            if not isinstance(methodology, dict):
                errors.append("external project catalog needs a methodology object")
            else:
                if set(methodology) != {
                    "current_kit_direct",
                    "current_kit_authorities",
                    "required_historical_sources",
                    "historical_evidence",
                    "excluded",
                }:
                    errors.append("external project methodology has an unexpected shape")
                method_repositories: set[str] = set()
                for field in ("current_kit_direct", "current_kit_authorities"):
                    values = methodology.get(field)
                    if not isinstance(values, list) or not values:
                        errors.append(f"external project methodology {field} must be a non-empty array")
                        continue
                    for index, value in enumerate(values):
                        try:
                            normalized = normalize_repo_url(value)
                        except (TypeError, ValueError) as exc:
                            errors.append(
                                f"external project methodology {field} item {index} is invalid: {exc}"
                            )
                            continue
                        key = normalized.lower()
                        if key in method_repositories:
                            errors.append(f"external project methodology duplicates {normalized}")
                        method_repositories.add(key)
                        if key not in catalog_repo_keys:
                            errors.append(
                                f"external project methodology references an uncatalogued repository: {normalized}"
                            )
                required_keys = {
                    value.lower() for value in REQUIRED_CURRENT_KIT_REPOSITORIES
                }
                for missing_repository in sorted(required_keys - method_repositories):
                    errors.append(
                        f"required current-kit repository missing from methodology: {missing_repository}"
                    )
                historical_values = methodology.get("required_historical_sources")
                historical_repositories: set[str] = set()
                if not isinstance(historical_values, list) or not historical_values:
                    errors.append(
                        "external project methodology required_historical_sources "
                        "must be a non-empty array"
                    )
                else:
                    for index, value in enumerate(historical_values):
                        try:
                            normalized = normalize_repo_url(value)
                        except (TypeError, ValueError) as exc:
                            errors.append(
                                "external project methodology required_historical_sources "
                                f"item {index} is invalid: {exc}"
                            )
                            continue
                        key = normalized.lower()
                        if key in historical_repositories:
                            errors.append(
                                f"external project methodology duplicates historical source {normalized}"
                            )
                        historical_repositories.add(key)
                        if key not in catalog_repo_keys:
                            errors.append(
                                "external project methodology references an uncatalogued "
                                f"historical repository: {normalized}"
                            )
                required_historical = {
                    value.lower() for value in REQUIRED_HISTORICAL_REPOSITORIES
                }
                missing_historical = sorted(required_historical - historical_repositories)
                extra_historical = sorted(historical_repositories - required_historical)
                if missing_historical or extra_historical:
                    errors.append(
                        "required historical source baseline drift: "
                        f"missing={missing_historical}; extra={extra_historical}"
                    )
                for field in ("historical_evidence", "excluded"):
                    values = methodology.get(field)
                    if not isinstance(values, list) or not values or not all(
                        isinstance(value, str) and value for value in values
                    ):
                        errors.append(f"external project methodology {field} must be a non-empty string array")

    historical_action_repositories: set[str] = set()
    historical_action_content = texts.get(historical_actions_path)
    if historical_action_content is not None:
        action_payload = parse_json_object(
            historical_action_content,
            "historical action-use catalog",
            errors,
        )
        if action_payload is not None and set(action_payload) != {
            "schema_version",
            "scope",
            "actions",
        }:
            errors.append("historical action-use catalog has an unexpected shape")
        if action_payload is not None and action_payload.get("schema_version") != 1:
            errors.append("historical action-use catalog schema_version must equal 1")
        scope = action_payload.get("scope") if action_payload is not None else None
        if not isinstance(scope, str) or not scope:
            errors.append("historical action-use catalog scope must be non-empty text")
        actions = action_payload.get("actions") if action_payload is not None else None
        if not isinstance(actions, list) or not actions or len(actions) > 64:
            errors.append("historical action-use catalog actions must contain 1 to 64 items")
        else:
            for index, action in enumerate(actions):
                if not isinstance(action, dict) or set(action) != {
                    "repository",
                    "revision",
                    "evidence",
                }:
                    errors.append(f"historical action use {index} has an unexpected shape")
                    continue
                if not all(
                    isinstance(action.get(field), str) and action[field]
                    for field in ("repository", "revision", "evidence")
                ):
                    errors.append(f"historical action use {index} has an empty field")
                    continue
                try:
                    normalized = normalize_repo_url(action["repository"])
                except (TypeError, ValueError) as exc:
                    errors.append(f"historical action use {index} has an invalid repository: {exc}")
                    continue
                key = normalized.lower()
                if key in historical_action_repositories:
                    errors.append(f"duplicate historical action source: {normalized}")
                historical_action_repositories.add(key)
                if key not in {value.lower() for value in catalog_repos}:
                    errors.append(
                        f"historical action source missing from external project catalog: {normalized}"
                    )
    required_action_repositories = {
        value.lower() for value in REQUIRED_HISTORICAL_ACTION_REPOSITORIES
    }
    missing_actions = sorted(required_action_repositories - historical_action_repositories)
    extra_actions = sorted(historical_action_repositories - required_action_repositories)
    if missing_actions or extra_actions:
        errors.append(
            "historical action source baseline drift: "
            f"missing={missing_actions}; extra={extra_actions}"
        )

    cited_repos: set[str] = set()
    for content in texts.values():
        for path_part in GITHUB_URL.findall(content):
            normalized = normalize_repo_url(f"https://github.com/{path_part}")
            if normalized.lower() != "https://github.com/homenshum/coding-agent-setup":
                cited_repos.add(normalized)
        for action in ACTION_USE.findall(content):
            cited_repos.add(normalize_repo_url(f"https://github.com/{action}"))
        for marker, repository in SERVICE_REPOSITORY_MARKERS:
            if marker in content:
                cited_repos.add(repository)
    missing_repos = sorted(
        repo for repo in cited_repos if repo.lower() not in {value.lower() for value in catalog_repos}
    )
    errors.extend(f"uncatalogued GitHub repository: {repo}" for repo in missing_repos)

    human_ledger = texts.get(root / "docs/external-projects.md", "")
    external_content = texts.get(external_path, "")
    expected_ledger_digest = hashlib.sha256(external_content.encode("utf-8")).hexdigest()
    digest_match = re.search(
        r"(?m)^<!-- external-projects-json-sha256: ([0-9a-f]{64}) -->$",
        human_ledger,
    )
    if digest_match is None or digest_match.group(1) != expected_ledger_digest:
        errors.append("human external ledger is not bound to the machine ledger digest")
    human_repos = {
        normalize_repo_url(f"https://github.com/{path_part}").lower()
        for path_part in GITHUB_URL.findall(human_ledger)
    }
    errors.extend(
        f"external repository missing from human ledger: {repo}"
        for repo in sorted(catalog_repos)
        if repo.lower() not in human_repos
    )
    for index, project in enumerate(external_projects):
        values = tuple(
            project.get(field)
            for field in ("name", "repository", "relationship", "license", "accessed")
        )
        if not all(isinstance(value, str) and value for value in values):
            continue
        name, repository, relationship, license_name, accessed = values
        row = next(
            (
                line
                for line in human_ledger.splitlines()
                if f"]({repository}) |" in line
            ),
            "",
        )
        expected_row = render_external_project_row(project)
        if row != expected_row:
            errors.append(f"external project {index} exact row drifts from human ledger")
        category = project.get("category")
        heading = EXTERNAL_CATEGORY_HEADINGS.get(category) if isinstance(category, str) else None
        if heading is not None and row:
            heading_position = human_ledger.find(heading)
            row_position = human_ledger.find(row)
            next_heading = human_ledger.find("\n## ", heading_position + len(heading))
            if (
                heading_position < 0
                or row_position < heading_position
                or (next_heading >= 0 and row_position >= next_heading)
            ):
                errors.append(f"external project {index} category drifts from human ledger")
    expected_project_rows = [
        render_external_project_row(project)
        for project in external_projects
        if all(
            isinstance(project.get(field), str) and project[field]
            for field in ("name", "repository", "relationship", "license", "accessed")
        )
    ]
    expected_row_set = set(expected_project_rows)
    observed_project_rows = [
        line for line in human_ledger.splitlines() if line in expected_row_set
    ]
    if observed_project_rows != expected_project_rows:
        errors.append("external project row order drifts from machine ledger")

    catalog_docs: set[str] = set()
    if official_path in texts:
        payload = parse_json_object(texts[official_path], "official document catalog", errors)
        if payload is not None and set(payload) != {"accessed", "sources"}:
            errors.append("official document catalog has an unexpected shape")
        sources = payload.get("sources") if payload is not None else None
        official_accessed = payload.get("accessed") if payload is not None else None
        if not is_valid_access_date(official_accessed):
            errors.append("official document catalog has an invalid or future access date")
        if payload is not None and not isinstance(sources, list):
            errors.append("invalid official document catalog: sources must be an array")
        if isinstance(sources, list):
            for index, source in enumerate(sources):
                if not isinstance(source, dict):
                    errors.append(f"official source {index} must be an object")
                    continue
                missing = sorted({"vendor", "topic", "url"} - source.keys())
                extra = sorted(source.keys() - {"vendor", "topic", "url"})
                if missing:
                    errors.append(f"official source {index} missing: {', '.join(missing)}")
                    continue
                if extra:
                    errors.append(f"official source {index} has unknown fields: {', '.join(extra)}")
                for field in ("vendor", "topic"):
                    if not isinstance(source.get(field), str) or not source[field].strip():
                        errors.append(
                            f"official source {index} field {field} must be a non-empty string"
                        )
                try:
                    normalized_doc = normalize_doc_url(source["url"])
                    vendor = source.get("vendor")
                    hostname = (urlparse(normalized_doc).hostname or "").lower()
                    if (
                        not isinstance(vendor, str)
                        or vendor not in OFFICIAL_VENDOR_HOSTS
                        or hostname not in OFFICIAL_VENDOR_HOSTS[vendor]
                    ):
                        errors.append(
                            f"official source {index} vendor does not match its URL host"
                        )
                    if normalized_doc in catalog_docs:
                        errors.append(f"duplicate official document: {normalized_doc}")
                    catalog_docs.add(normalized_doc)
                except (KeyError, TypeError, ValueError) as exc:
                    errors.append(f"official source {index} has invalid URL: {exc}")
    cited_docs = {
        normalize_doc_url(match.group(0))
        for content in texts.values()
        for match in VENDOR_DOC_URL.finditer(content)
    }
    errors.extend(
        f"uncatalogued official document: {url}" for url in sorted(cited_docs - catalog_docs)
    )

    safe_errors = redact_private_marker_diagnostics(errors, private_marker_rules)
    return sorted(set(safe_errors))


def validate_public_destination(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_EXTERNAL_HOSTS:
        raise ValueError(f"external URL is not on the HTTPS allowlist: {url}")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError(f"external host did not resolve: {parsed.hostname}")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast, ip.is_reserved, ip.is_unspecified)):
            raise ValueError(f"external host resolved to a non-public address: {parsed.hostname}")


class SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        target = urljoin(req.full_url, newurl)
        validate_public_destination(target)
        redirected = super().redirect_request(req, fp, code, msg, headers, target)
        if redirected is None:
            return None
        source = urlparse(req.full_url)
        destination = urlparse(target)
        source_origin = (source.scheme.lower(), source.hostname, source.port or 443)
        destination_origin = (
            destination.scheme.lower(),
            destination.hostname,
            destination.port or 443,
        )
        if source_origin != destination_origin:
            for header in ("Authorization", "Proxy-Authorization", "Cookie"):
                redirected.remove_header(header)
        return redirected


def fetch_external(url: str) -> tuple[bool, str]:
    try:
        validate_public_destination(url)
        headers = {"User-Agent": "codex-claude-setup-validator/1.0"}
        github_token = os.environ.get("SETUP_LINKCHECK_GITHUB_TOKEN")
        if github_token and urlparse(url).hostname == "github.com":
            headers["Authorization"] = f"Bearer {github_token}"
        request = Request(url, headers=headers)
        with build_opener(SafeRedirectHandler()).open(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                body = body[:MAX_RESPONSE_BYTES]
            status = getattr(response, "status", 200)
            if status < 200 or status >= 400:
                return False, f"HTTP {status}"
            return True, f"HTTP {status}; sampled {len(body)} bytes"
    except Exception as exc:  # one URL must not abort the remaining bounded checks
        return False, f"{type(exc).__name__}: {exc}"


def fetch_external_bounded(
    url: str,
    *,
    deadline: float | None = None,
) -> tuple[bool, str]:
    """Run DNS, redirects, and HTTP in a child with a killable wall-clock deadline."""

    if not isinstance(url, str) or not url or len(url) > MAX_EXTERNAL_URL_CHARS:
        return False, "URL is missing or exceeds the character cap"
    process_budget = float(TIMEOUT_SECONDS + 3)
    if deadline is not None:
        process_budget = min(process_budget, deadline - time.monotonic())
        if process_budget <= 0:
            return False, "fetch skipped after the aggregate deadline"
    try:
        completed = run_bounded(
            [sys.executable, str(Path(__file__).resolve()), "--_fetch-one", url],
            cwd=Path(__file__).resolve().parents[1],
            timeout_seconds=process_budget,
            output_limit=MAX_FETCH_RESULT_BYTES,
        )
        raw = completed.output
    except subprocess.TimeoutExpired:
        return False, "fetch exceeded its bounded process deadline"
    except OutputLimitExceeded:
        return False, "fetch result exceeded the output cap"
    except OSError as exc:
        return False, f"fetch process failed: {type(exc).__name__}"
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False, f"fetch process returned invalid output with exit {completed.returncode}"
    if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
        return False, "fetch process returned an invalid result shape"
    detail = payload.get("detail")
    if not isinstance(detail, str) or len(detail) > MAX_FETCH_RESULT_BYTES:
        return False, "fetch process returned an invalid detail"
    return payload["ok"], detail


def check_external_urls(
    urls: Iterable[str],
    fetcher: Callable[[str], tuple[bool, str]] | None = None,
    *,
    aggregate_seconds: float = EXTERNAL_AGGREGATE_SECONDS,
) -> list[tuple[str, bool, str]]:
    if aggregate_seconds <= 0 or aggregate_seconds > EXTERNAL_AGGREGATE_SECONDS:
        raise ValueError(
            f"aggregate_seconds must be from greater than zero to {EXTERNAL_AGGREGATE_SECONDS}"
        )
    unique_urls: set[str] = set()
    items_seen = 0
    for url in urls:
        items_seen += 1
        if items_seen > MAX_EXTERNAL_URL_ITEMS:
            raise ValueError(
                f"external URL input cap exceeded: more than {MAX_EXTERNAL_URL_ITEMS} items"
            )
        if not isinstance(url, str) or not url or len(url) > MAX_EXTERNAL_URL_CHARS:
            raise ValueError("external URL is missing or exceeds the character cap")
        if url in unique_urls:
            continue
        if len(unique_urls) >= MAX_EXTERNAL_URLS:
            raise ValueError(
                f"external URL cap exceeded: more than {MAX_EXTERNAL_URLS} unique URLs"
            )
        unique_urls.add(url)
    bounded = sorted(unique_urls)
    results: list[tuple[str, bool, str]] = []
    deadline = time.monotonic() + aggregate_seconds
    if fetcher is None:
        def bounded_fetch(url: str) -> tuple[bool, str]:
            return fetch_external_bounded(url, deadline=deadline)
    else:
        bounded_fetch = fetcher
    pool = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    future_urls = {pool.submit(bounded_fetch, url): url for url in bounded}
    completed_futures: set[object] = set()
    try:
        remaining = max(0.001, deadline - time.monotonic())
        for future in as_completed(future_urls, timeout=remaining):
            completed_futures.add(future)
            url = future_urls[future]
            try:
                ok, detail = future.result()
            except Exception as exc:
                ok, detail = False, f"{type(exc).__name__}: {exc}"
            results.append((url, ok, detail))
    except FuturesTimeoutError:
        pass
    finally:
        unfinished = [
            (future, url)
            for future, url in future_urls.items()
            if future not in completed_futures
        ]
        for future, _ in unfinished:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
        for _, url in unfinished:
            results.append((url, False, "external URL batch exceeded its aggregate deadline"))
    return sorted(results)


def catalog_urls(root: Path = ROOT) -> list[str]:
    external = json.loads(read_text(root / "sources/external-projects.json"))
    official = json.loads(read_text(root / "sources/official-docs.json"))
    return [
        project["repository"]
        for project in external["projects"]
        if project.get("check", True)
    ] + [
        source["url"] for source in official["sources"]
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-external", action="store_true", help="perform bounded live URL checks")
    parser.add_argument("--_fetch-one", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args._fetch_one is not None:
        ok, detail = fetch_external(args._fetch_one)
        print(json.dumps({"detail": detail, "ok": ok}, sort_keys=True))
        return 0 if ok else 1

    errors = validate_repo()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("PASS: offline repository validation")

    if args.check_external:
        try:
            urls = catalog_urls()
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            print(f"ERROR: cannot load external catalogs — {type(exc).__name__}: {exc}")
            return 1
        results = check_external_urls(urls)
        for url, ok, detail in results:
            print(f"{'PASS' if ok else 'ERROR'}: {url} — {detail}")
        if any(not ok for _, ok, _ in results):
            return 1
        print(f"PASS: {len(results)} bounded external URL checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
