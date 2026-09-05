#!/usr/bin/env python3
"""Run a deterministic, bounded seven-layer agent preflight."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from bounded_process import OutputLimitExceeded, run_bounded
from git_safety import clean_git_environment, effective_graft_error
from path_safety import is_link_like, read_regular_file_bounded, reject_linked_path


CHECK_NAMES = (
    "shape_version",
    "silent_handlers",
    "convention_sync",
    "runtime",
    "selftests",
    "visual",
    "self_review",
)
SELF_REVIEW_QUESTIONS = (
    "intent",
    "evidence",
    "regression",
    "security",
    "scope",
    "visual",
    "handoff",
)
VALID_STATUSES = frozenset({"PASS", "FAIL", "NO_GATE"})

MAX_CONFIG_BYTES = 65_536
MAX_FILES = 256
MAX_FILE_BYTES = 1_048_576
MAX_TOTAL_BYTES = 8_388_608
MAX_ERRORS = 64
MAX_ERRORS_PER_CHECK = 8
MAX_PATTERNS = 16
MAX_VISITED_ENTRIES = 1_024
MAX_PAIRS = 16
MAX_RULES = 32
MAX_IMPORTS = 32
MAX_COMMANDS = 8
MAX_COMMAND_ARGS = 32
MAX_ARGUMENT_CHARS = 2_048
MAX_COMMAND_OUTPUT_BYTES = 65_536
MAX_COMMAND_SECONDS = 60
MAX_ARTIFACTS = 16
MAX_ANSWER_CHARS = 4_096
SENSITIVE_PATH_PARTS = frozenset({".git", ".agent-local", ".ssh", ".aws", "secret", "secrets"})
SENSITIVE_BASENAMES = frozenset(
    {
        "auth.json",
        "credentials.json",
        "history.jsonl",
        "session.sqlite",
        "state.sqlite",
        "settings.local.json",
    }
)
SENSITIVE_SUFFIXES = frozenset({".db", ".key", ".p12", ".pem", ".pfx", ".sqlite", ".sqlite3"})

_JS_EMPTY_CATCH = re.compile(
    r"\bcatch\s*(?:\([^)]*\))?\s*\{\s*(?:(?://[^\n]*(?:\n|$))|(?:/\*.*?\*/\s*))*\}",
    re.DOTALL,
)


@dataclass
class ReadBudget:
    files: int = 0
    total_bytes: int = 0


def _bounded_errors(messages: list[str]) -> list[str]:
    return sorted(set(messages))[:MAX_ERRORS_PER_CHECK]


def _result(
    name: str,
    status: str,
    errors: list[str] | None = None,
    evidence: list[str] | None = None,
) -> dict[str, Any]:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    return {
        "name": name,
        "status": status,
        "errors": _bounded_errors(errors or []),
        "evidence": sorted(set(evidence or [])),
    }


def _safe_path(root: Path, raw: Any, *, must_exist: bool = True) -> tuple[Path | None, str | None]:
    if not isinstance(raw, str) or not raw.strip():
        return None, "path must be a non-empty string"
    if len(raw) > MAX_ARGUMENT_CHARS:
        return None, "path exceeds the character cap"
    relative = Path(raw)
    if relative.is_absolute():
        return None, "path must be repository-relative"
    lowered_parts = tuple(part.lower() for part in relative.parts)
    basename = lowered_parts[-1] if lowered_parts else ""
    if (
        any(part in SENSITIVE_PATH_PARTS for part in lowered_parts)
        or basename == ".env"
        or (basename.startswith(".env.") and basename != ".env.example")
        or basename in SENSITIVE_BASENAMES
        or Path(basename).suffix in SENSITIVE_SUFFIXES
    ):
        return None, "credential or runtime-state paths are not accepted"
    root_absolute = Path(os.path.abspath(root))
    candidate = Path(os.path.abspath(root_absolute / relative))
    try:
        if is_link_like(root_absolute):
            raise ValueError("repository root is link-like")
        root_resolved = root_absolute.resolve(strict=True)
        reject_linked_path(candidate, root_resolved, label="preflight")
        resolved = candidate.resolve(strict=must_exist)
        resolved.relative_to(root_resolved)
    except (OSError, RuntimeError, ValueError):
        return None, "path escapes the repository or cannot be resolved"
    if must_exist and not candidate.exists():
        return None, "path does not exist"
    return candidate, None


def _read_bytes(root: Path, raw: Any, budget: ReadBudget) -> tuple[bytes | None, str | None]:
    path, error = _safe_path(root, raw)
    if error:
        return None, error
    assert path is not None
    if budget.files + 1 > MAX_FILES:
        return None, f"file-read cap exceeds {MAX_FILES}"
    try:
        data = read_regular_file_bounded(
            path,
            MAX_FILE_BYTES,
            boundary=root,
            label="preflight file",
        )
    except (OSError, ValueError) as exc:
        return None, f"cannot read file: {type(exc).__name__}"
    if budget.total_bytes + len(data) > MAX_TOTAL_BYTES:
        return None, f"byte-read cap exceeds {MAX_TOTAL_BYTES}"
    budget.files += 1
    budget.total_bytes += len(data)
    return data, None


def _read_text(root: Path, raw: Any, budget: ReadBudget) -> tuple[str | None, str | None]:
    data, error = _read_bytes(root, raw, budget)
    if error:
        return None, error
    assert data is not None
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, "file is not valid UTF-8"


def _read_json(root: Path, raw: Any, budget: ReadBudget) -> tuple[Any, str | None]:
    text, error = _read_text(root, raw, budget)
    if error:
        return None, error
    assert text is not None
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON at line {exc.lineno} column {exc.colno}"


def _decode_json(data: bytes) -> tuple[Any, str | None]:
    try:
        return json.loads(data.decode("utf-8")), None
    except UnicodeDecodeError:
        return None, "file is not valid UTF-8"
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON at line {exc.lineno} column {exc.colno}"


def _committed_json(
    root: Path, revision: str, relative: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Read one bounded JSON blob from Git without trusting inherited Git routing."""

    try:
        completed = run_bounded(
            ["git", "-C", str(root), "show", f"{revision}:{Path(relative).as_posix()}"],
            cwd=root,
            timeout_seconds=5,
            output_limit=MAX_FILE_BYTES,
            env=clean_git_environment(),
        )
    except OutputLimitExceeded:
        return None, "committed schema exceeds the read cap"
    except subprocess.TimeoutExpired:
        return None, "committed schema lookup exceeded its time budget"
    except OSError as exc:
        return None, f"committed schema lookup failed: {type(exc).__name__}"
    if completed.returncode != 0:
        return None, None
    value, error = _decode_json(completed.output)
    if error:
        return None, f"committed schema is invalid: {error}"
    if not isinstance(value, dict):
        return None, "committed schema must be a JSON object"
    return value, None


def _head_parents(root: Path) -> tuple[list[str] | None, str | None]:
    """Return every parent named by HEAD, distinguishing a root commit from missing history."""

    try:
        completed = run_bounded(
            ["git", "-C", str(root), "cat-file", "-p", "HEAD"],
            cwd=root,
            timeout_seconds=5,
            output_limit=MAX_FILE_BYTES,
            env=clean_git_environment(),
        )
    except OutputLimitExceeded:
        return None, "HEAD metadata exceeds the read cap"
    except subprocess.TimeoutExpired:
        return None, "HEAD metadata lookup exceeded its time budget"
    except OSError as exc:
        return None, f"HEAD metadata lookup failed: {type(exc).__name__}"
    if completed.returncode != 0:
        return None, None
    try:
        header = completed.output.split(b"\n\n", 1)[0].decode("ascii")
    except UnicodeDecodeError:
        return None, "HEAD metadata is not ASCII"
    parents: list[str] = []
    for line in header.splitlines():
        if not line.startswith("parent "):
            continue
        parent = line.removeprefix("parent ")
        if re.fullmatch(r"[0-9a-f]{40,64}", parent) is None:
            return None, "HEAD contains an invalid parent identifier"
        parents.append(parent)
        if len(parents) > MAX_PAIRS:
            return None, f"HEAD has more than {MAX_PAIRS} parents"
    return parents, None


def _commit_is_available(root: Path, revision: str) -> tuple[bool, str | None]:
    """Check that a parent commit object exists locally without inheriting Git routing."""

    try:
        completed = run_bounded(
            ["git", "-C", str(root), "cat-file", "-e", f"{revision}^{{commit}}"],
            cwd=root,
            timeout_seconds=5,
            output_limit=1_024,
            env=clean_git_environment(),
        )
    except OutputLimitExceeded:
        return False, "parent availability check exceeded the output cap"
    except subprocess.TimeoutExpired:
        return False, "parent availability check exceeded its time budget"
    except OSError as exc:
        return False, f"parent availability check failed: {type(exc).__name__}"
    return completed.returncode == 0, None


def _check_shape_version(root: Path, settings: Any, budget: ReadBudget) -> dict[str, Any]:
    errors: list[str] = []
    evidence: list[str] = []
    pairs = settings.get("pairs") if isinstance(settings, dict) else None
    if not isinstance(pairs, list) or not pairs or len(pairs) > MAX_PAIRS:
        return _result(
            "shape_version",
            "FAIL",
            [f"pairs must contain 1 to {MAX_PAIRS} entries"],
        )
    graft_error = effective_graft_error(root, repository_required=False)
    if graft_error:
        return _result("shape_version", "FAIL", [graft_error])
    for index, pair in enumerate(pairs):
        if not isinstance(pair, dict):
            errors.append(f"pair {index} must be an object")
            continue
        schema_path = pair.get("schema")
        receipt_path = pair.get("receipt")
        schema_data, schema_error = _read_bytes(root, schema_path, budget)
        receipt_data, receipt_error = _read_bytes(root, receipt_path, budget)
        schema = None
        receipt = None
        if schema_data is not None:
            schema, decode_error = _decode_json(schema_data)
            schema_error = schema_error or decode_error
        if receipt_data is not None:
            receipt, decode_error = _decode_json(receipt_data)
            receipt_error = receipt_error or decode_error
        if schema_error:
            errors.append(f"pair {index} schema: {schema_error}")
        if receipt_error:
            errors.append(f"pair {index} receipt: {receipt_error}")
        if schema_error or receipt_error:
            continue
        assert schema_data is not None
        if not isinstance(schema, dict) or not isinstance(receipt, dict):
            errors.append(f"pair {index} schema and receipt must be JSON objects")
            continue
        schema_version = schema.get("version")
        receipt_version = receipt.get("version")
        expected_version = schema.get("receipt_version")
        if (
            not isinstance(schema_version, int)
            or isinstance(schema_version, bool)
            or schema_version < 1
        ):
            errors.append(f"pair {index} schema version must be a positive integer")
        if (
            not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
            or expected_version < 1
        ):
            errors.append(f"pair {index} expected receipt version must be a positive integer")
        if (
            not isinstance(receipt_version, int)
            or isinstance(receipt_version, bool)
            or receipt_version < 1
        ):
            errors.append(f"pair {index} receipt version must be a positive integer")
        if expected_version != receipt_version:
            errors.append(f"pair {index} receipt version does not match its schema")

        committed, committed_error = _committed_json(root, "HEAD", str(schema_path))
        if committed_error:
            errors.append(f"pair {index} {committed_error}")
        baselines: list[dict[str, Any]] = []
        if committed == schema:
            parents, parents_error = _head_parents(root)
            if parents_error:
                errors.append(f"pair {index} {parents_error}")
            elif parents is None:
                errors.append(f"pair {index} cannot establish the HEAD history boundary")
            else:
                for parent_revision in parents:
                    available, availability_error = _commit_is_available(root, parent_revision)
                    if availability_error:
                        errors.append(f"pair {index} {availability_error}")
                        continue
                    if not available:
                        errors.append(
                            f"pair {index} parent commit is unavailable; fetch at least two commits"
                        )
                        continue
                    parent, parent_error = _committed_json(
                        root, parent_revision, str(schema_path)
                    )
                    if parent_error:
                        errors.append(f"pair {index} {parent_error}")
                    elif parent is not None:
                        baselines.append(parent)
                if not parents and schema_version != 1:
                    errors.append(
                        f"pair {index} first committed schema version must equal 1"
                    )
                if parents and not baselines and not any(
                    "parent commit is unavailable" in error for error in errors
                ) and schema_version != 1:
                    errors.append(
                        f"pair {index} first committed schema version must equal 1"
                    )
        elif committed is not None:
            baselines.append(committed)
        elif schema_version != 1:
            errors.append(f"pair {index} first committed schema version must equal 1")

        for baseline in baselines:
            if baseline == schema:
                continue
            prior_version = baseline.get("version")
            if (
                not isinstance(prior_version, int)
                or isinstance(prior_version, bool)
                or not isinstance(schema_version, int)
                or isinstance(schema_version, bool)
                or schema_version <= prior_version
            ):
                errors.append(
                    f"pair {index} schema shape changed without a higher schema version"
                )
        schema_artifact = schema.get("artifact")
        receipt_artifact = receipt.get("artifact")
        if not isinstance(schema_artifact, str) or not schema_artifact:
            errors.append(f"pair {index} schema artifact must be a non-empty string")
        if not isinstance(receipt_artifact, str) or not receipt_artifact:
            errors.append(f"pair {index} receipt artifact must be a non-empty string")
        if schema_artifact != receipt_artifact:
            errors.append(f"pair {index} artifact identity does not match")
        schema_digest = hashlib.sha256(schema_data).hexdigest()
        receipt_schema_digest = receipt.get("schema_digest")
        if (
            not isinstance(receipt_schema_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", receipt_schema_digest)
        ):
            errors.append(f"pair {index} schema_digest must be a lowercase SHA-256 value")
        elif receipt_schema_digest != schema_digest:
            errors.append(f"pair {index} canonical schema digest does not match")
        required = schema.get("required_receipt_fields")
        if (
            not isinstance(required, list)
            or not required
            or len(required) > MAX_RULES
            or any(not isinstance(field, str) or not field for field in required)
        ):
            errors.append(f"pair {index} required_receipt_fields is invalid")
        else:
            missing = sorted(set(required) - receipt.keys())
            if missing:
                errors.append(f"pair {index} receipt is missing: {', '.join(missing)}")
        evidence.append(
            f"pair {index}: schema {schema_version}, receipt {receipt_version}, sha256 {schema_digest}"
        )
    return _result("shape_version", "FAIL" if errors else "PASS", errors, evidence)


def _python_silent_handlers(text: str, label: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [f"{label}: invalid Python at line {exc.lineno}"]
    errors: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        silent = all(
            isinstance(statement, ast.Pass)
            or (
                isinstance(statement, ast.Expr)
                and isinstance(statement.value, ast.Constant)
                and (isinstance(statement.value.value, str) or statement.value.value is Ellipsis)
            )
            for statement in node.body
        )
        if not node.body or silent:
            errors.append(f"{label}:{node.lineno}: silent exception handler")
            if len(errors) >= MAX_ERRORS_PER_CHECK:
                break
    return errors


def _collect_pattern_files(root: Path, patterns: Any) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    if (
        not isinstance(patterns, list)
        or not patterns
        or len(patterns) > MAX_PATTERNS
        or any(not isinstance(pattern, str) or not pattern for pattern in patterns)
    ):
        return [], [f"patterns must contain 1 to {MAX_PATTERNS} strings"]
    found: set[str] = set()
    visited = 0
    for pattern in patterns:
        if (
            len(pattern) > MAX_ARGUMENT_CHARS
            or "\x00" in pattern
            or Path(pattern).is_absolute()
            or ".." in Path(pattern).parts
        ):
            errors.append("patterns must be bounded repository-relative globs")
            continue
        pattern_path = Path(pattern)
        directory_raw = pattern_path.parent.as_posix()
        filename_pattern = pattern_path.name
        if (
            "**" in pattern
            or any(character in directory_raw for character in "*?[")
            or not filename_pattern
        ):
            errors.append("patterns may match filenames in one explicit directory only")
            continue
        directory, directory_error = _safe_path(root, directory_raw)
        if directory_error:
            errors.append(f"pattern directory: {directory_error}")
            continue
        assert directory is not None
        if not directory.is_dir():
            errors.append("pattern parent must be a directory")
            continue
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    visited += 1
                    if visited > MAX_VISITED_ENTRIES:
                        return [], errors + [f"visited entry cap exceeds {MAX_VISITED_ENTRIES}"]
                    if not fnmatch.fnmatchcase(entry.name, filename_pattern):
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    candidate = Path(entry.path)
                    relative = candidate.relative_to(root).as_posix()
                    if candidate.is_symlink():
                        if len(errors) < MAX_ERRORS_PER_CHECK:
                            errors.append("a pattern result was a symbolic link")
                        continue
                    if relative in found:
                        continue
                    found.add(relative)
                    if len(found) > MAX_FILES:
                        return [], errors + [f"matched file cap exceeds {MAX_FILES}"]
        except (OSError, ValueError) as exc:
            errors.append(f"cannot scan pattern directory: {type(exc).__name__}")
    return sorted(found), errors


def _check_silent_handlers(root: Path, settings: Any, budget: ReadBudget) -> dict[str, Any]:
    patterns = settings.get("patterns") if isinstance(settings, dict) else None
    paths, errors = _collect_pattern_files(root, patterns)
    for relative in paths:
        text, read_error = _read_text(root, relative, budget)
        if read_error:
            errors.append(f"{relative}: {read_error}")
            continue
        assert text is not None
        suffix = Path(relative).suffix.lower()
        if suffix == ".py":
            errors.extend(_python_silent_handlers(text, relative))
        elif suffix in {".js", ".jsx", ".ts", ".tsx"} and _JS_EMPTY_CATCH.search(text):
            errors.append(f"{relative}: silent JavaScript/TypeScript catch handler")
        if len(errors) >= MAX_ERRORS_PER_CHECK:
            break
    evidence = [f"scanned {len(paths)} handler-bearing source files"] if paths else []
    return _result("silent_handlers", "FAIL" if errors else "PASS", errors, evidence)


def _check_convention_sync(root: Path, settings: Any, budget: ReadBudget) -> dict[str, Any]:
    rules = settings.get("rules") if isinstance(settings, dict) else None
    if not isinstance(rules, list) or not rules or len(rules) > MAX_RULES:
        return _result(
            "convention_sync",
            "FAIL",
            [f"rules must contain 1 to {MAX_RULES} entries"],
        )
    errors: list[str] = []
    evidence: list[str] = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            errors.append(f"rule {index} must be an object")
            continue
        relative = rule.get("path")
        markers = rule.get("contains")
        if (
            not isinstance(markers, list)
            or not markers
            or len(markers) > MAX_RULES
            or any(not isinstance(marker, str) or not marker or len(marker) > MAX_ARGUMENT_CHARS for marker in markers)
        ):
            errors.append(f"rule {index} contains must be a bounded non-empty string array")
            continue
        text, read_error = _read_text(root, relative, budget)
        if read_error:
            errors.append(f"rule {index}: {read_error}")
            continue
        assert text is not None
        for marker_index, marker in enumerate(markers):
            if marker not in text:
                errors.append(f"rule {index} is missing marker {marker_index}")
                if len(errors) >= MAX_ERRORS_PER_CHECK:
                    break
        evidence.append(f"rule {index}: {relative}")
        if len(errors) >= MAX_ERRORS_PER_CHECK:
            break
    return _result("convention_sync", "FAIL" if errors else "PASS", errors, evidence)


def _parse_version(value: Any) -> tuple[int, ...] | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", value):
        return None
    return tuple(int(part) for part in value.split("."))


def _check_runtime(root: Path, settings: Any, budget: ReadBudget) -> dict[str, Any]:
    del budget
    if not isinstance(settings, dict):
        return _result("runtime", "FAIL", ["runtime settings must be an object"])
    errors: list[str] = []
    minimum = _parse_version(settings.get("minimum_python"))
    if minimum is None:
        errors.append("minimum_python must be a dotted numeric version")
    elif sys.version_info[: len(minimum)] < minimum:
        errors.append(f"Python does not meet minimum {settings['minimum_python']}")
    imports = settings.get("imports")
    if (
        not isinstance(imports, list)
        or len(imports) > MAX_IMPORTS
        or any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_]\w*", name) for name in imports)
    ):
        errors.append(
            f"imports must contain at most {MAX_IMPORTS} top-level module names"
        )
        imports = []
    probe_timeout = settings.get("probe_timeout_seconds", 5)
    probe_errors: list[str] = []
    probe_evidence: list[str] = []
    if (
        not isinstance(probe_timeout, int)
        or isinstance(probe_timeout, bool)
        or probe_timeout < 1
        or probe_timeout > MAX_COMMAND_SECONDS
    ):
        errors.append(f"probe_timeout_seconds must be from 1 to {MAX_COMMAND_SECONDS}")
    elif imports:
        probe = (
            "import importlib.machinery,json,sys;"
            "names=json.loads(sys.argv[1]);"
            "missing=[name for name in names if name not in sys.builtin_module_names "
            "and importlib.machinery.PathFinder.find_spec(name) is None];"
            "raise SystemExit(0 if not missing else 4)"
        )
        probe_errors, probe_evidence = _run_command(
            root,
            {
                "argv": ["{python}", "-c", probe, json.dumps(imports, separators=(",", ":"))],
                "timeout_seconds": probe_timeout,
            },
            "runtime",
        )
        errors.extend(probe_errors)
    evidence = [
        f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        f"runtime executable basename: {Path(sys.executable).name}",
    ]
    if imports:
        evidence.extend(probe_evidence)
        if not probe_errors:
            evidence.append(f"resolved {len(imports)} required modules without importing them")
    return _result("runtime", "FAIL" if errors else "PASS", errors, evidence)


def _command_argv(spec: Any) -> tuple[list[str] | None, int | None, str | None]:
    if not isinstance(spec, dict):
        return None, None, "command must be an object"
    argv = spec.get("argv")
    timeout = spec.get("timeout_seconds")
    if (
        not isinstance(argv, list)
        or not argv
        or len(argv) > MAX_COMMAND_ARGS
        or any(not isinstance(arg, str) or not arg or len(arg) > MAX_ARGUMENT_CHARS for arg in argv)
    ):
        return None, None, f"argv must contain 1 to {MAX_COMMAND_ARGS} bounded strings"
    if (
        not isinstance(timeout, int)
        or isinstance(timeout, bool)
        or timeout < 1
        or timeout > MAX_COMMAND_SECONDS
    ):
        return None, None, f"timeout_seconds must be from 1 to {MAX_COMMAND_SECONDS}"
    expanded = [sys.executable if arg == "{python}" else arg for arg in argv]
    return expanded, timeout, None


def _run_command(root: Path, spec: Any, index: int | str) -> tuple[list[str], list[str]]:
    argv, timeout, config_error = _command_argv(spec)
    if config_error:
        return [f"command {index}: {config_error}"], []
    assert argv is not None and timeout is not None
    try:
        completed = run_bounded(
            argv,
            cwd=root,
            timeout_seconds=timeout,
            output_limit=MAX_COMMAND_OUTPUT_BYTES,
        )
    except OutputLimitExceeded:
        return [f"command {index} output exceeded {MAX_COMMAND_OUTPUT_BYTES} bytes"], []
    except subprocess.TimeoutExpired as exc:
        captured = exc.output if isinstance(exc.output, bytes) else b""
        digest = hashlib.sha256(captured).hexdigest()
        return [f"command {index} exceeded its {timeout}-second budget"], [
            f"command {index}: timeout, output sha256 {digest}"
        ]
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return [f"command {index} could not start: {type(exc).__name__}"], []
    digest = hashlib.sha256(completed.output).hexdigest()
    evidence = [
        f"command {index}: exit {completed.returncode}, output sha256 {digest}"
    ]
    errors: list[str] = []
    if completed.returncode != 0:
        errors.append(f"command {index} exited with status {completed.returncode}")
    return errors, evidence


def _check_selftests(root: Path, settings: Any, budget: ReadBudget) -> dict[str, Any]:
    del budget
    commands = settings.get("commands") if isinstance(settings, dict) else None
    if not isinstance(commands, list) or not commands or len(commands) > MAX_COMMANDS:
        return _result(
            "selftests",
            "FAIL",
            [f"commands must contain 1 to {MAX_COMMANDS} entries"],
        )
    errors: list[str] = []
    evidence: list[str] = []
    for index, command in enumerate(commands):
        command_errors, command_evidence = _run_command(root, command, index)
        errors.extend(command_errors)
        evidence.extend(command_evidence)
        if len(errors) >= MAX_ERRORS_PER_CHECK:
            break
    return _result("selftests", "FAIL" if errors else "PASS", errors, evidence)


def _check_visual(root: Path, settings: Any, budget: ReadBudget) -> dict[str, Any]:
    del budget
    if not isinstance(settings, dict):
        return _result("visual", "NO_GATE", ["visual gate is not configured"])
    mode = settings.get("mode")
    if mode == "not_applicable":
        reason = settings.get("reason")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_ANSWER_CHARS:
            return _result("visual", "NO_GATE", ["not_applicable requires a bounded reason"])
        return _result("visual", "PASS", evidence=["visual gate explicitly not applicable"])
    if mode != "required":
        return _result(
            "visual",
            "NO_GATE",
            ["visual mode must be required or not_applicable"],
        )
    artifacts = settings.get("artifacts")
    if (
        not isinstance(artifacts, list)
        or not artifacts
        or len(artifacts) > MAX_ARTIFACTS
        or any(not isinstance(item, str) or not item for item in artifacts)
    ):
        return _result(
            "visual",
            "NO_GATE",
            [f"required visual gate needs 1 to {MAX_ARTIFACTS} artifact paths"],
        )
    before: dict[str, tuple[int, int, int]] = {}
    precheck_errors: list[str] = []
    for index, raw in enumerate(artifacts):
        path, path_error = _safe_path(root, raw, must_exist=False)
        if path_error:
            precheck_errors.append(f"artifact {index}: {path_error}")
            continue
        assert path is not None
        if path.exists():
            if not path.is_file():
                precheck_errors.append(f"artifact {index}: existing path is not a regular file")
                continue
            try:
                stat = path.stat()
            except OSError as exc:
                precheck_errors.append(f"artifact {index}: cannot stat: {type(exc).__name__}")
                continue
            before[raw] = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    if precheck_errors:
        return _result("visual", "NO_GATE", precheck_errors)
    argv, timeout, command_error = _command_argv(settings.get("command"))
    del argv, timeout
    if command_error:
        return _result("visual", "NO_GATE", [f"visual gate: {command_error}"])
    errors, evidence = _run_command(root, settings.get("command"), 0)
    if errors:
        return _result("visual", "FAIL", errors, evidence)
    for index, raw in enumerate(artifacts):
        path, path_error = _safe_path(root, raw)
        if path_error:
            errors.append(f"artifact {index}: {path_error}")
            continue
        assert path is not None
        try:
            size = path.stat().st_size
        except OSError as exc:
            errors.append(f"artifact {index}: cannot stat: {type(exc).__name__}")
            continue
        if not path.is_file() or size < 1:
            errors.append(f"artifact {index}: expected a non-empty regular file")
        elif size > MAX_FILE_BYTES:
            errors.append(f"artifact {index}: exceeds {MAX_FILE_BYTES} bytes")
        else:
            stat = path.stat()
            after = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
            if before.get(raw) == after:
                errors.append(f"artifact {index}: command left a stale pre-existing artifact")
                continue
            evidence.append(f"artifact {index}: {raw} ({size} bytes)")
    return _result("visual", "FAIL" if errors else "PASS", errors, evidence)


def compute_bound_digest(
    root: Path,
    paths: list[str],
    budget: ReadBudget | None = None,
) -> tuple[str | None, list[str], list[str]]:
    active_budget = budget or ReadBudget()
    errors: list[str] = []
    normalized: list[str] = []
    if (
        not isinstance(paths, list)
        or not paths
        or len(paths) > MAX_RULES
        or any(not isinstance(item, str) or not item for item in paths)
    ):
        return None, [f"paths must contain 1 to {MAX_RULES} strings"], []
    for raw in paths:
        path, path_error = _safe_path(root, raw)
        if path_error:
            errors.append(f"digest path: {path_error}")
            continue
        assert path is not None
        normalized.append(path.resolve().relative_to(root.resolve()).as_posix())
    normalized = sorted(normalized)
    if len(set(normalized)) != len(normalized):
        errors.append("digest paths must be unique")
    if errors:
        return None, _bounded_errors(errors), normalized
    digest = hashlib.sha256()
    for relative in normalized:
        data, read_error = _read_bytes(root, relative, active_budget)
        if read_error:
            errors.append(f"{relative}: {read_error}")
            continue
        assert data is not None
        encoded_path = relative.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(4, "big"))
        digest.update(encoded_path)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return (digest.hexdigest() if not errors else None), _bounded_errors(errors), normalized


def _check_self_review(root: Path, settings: Any, budget: ReadBudget) -> dict[str, Any]:
    if not isinstance(settings, dict):
        return _result("self_review", "FAIL", ["self_review settings must be an object"])
    paths = settings.get("paths")
    digest, errors, normalized = compute_bound_digest(root, paths, budget)
    receipt, receipt_error = _read_json(root, settings.get("receipt"), budget)
    if receipt_error:
        errors.append(f"receipt: {receipt_error}")
        return _result("self_review", "FAIL", errors)
    if not isinstance(receipt, dict):
        errors.append("receipt must be a JSON object")
        return _result("self_review", "FAIL", errors)
    expected_artifact = settings.get("artifact")
    if not isinstance(expected_artifact, str) or not expected_artifact:
        errors.append("self_review artifact must be a non-empty string")
    elif receipt.get("artifact") != expected_artifact:
        errors.append("receipt artifact does not match self_review settings")
    receipt_version = receipt.get("version")
    if (
        not isinstance(receipt_version, int)
        or isinstance(receipt_version, bool)
        or receipt_version < 1
    ):
        errors.append("receipt version must be a positive integer")
    if receipt.get("status") != "complete":
        errors.append("receipt status must equal complete")
    if receipt.get("paths") != normalized:
        errors.append("receipt paths do not match the configured digest paths")
    if not isinstance(receipt.get("digest"), str) or not re.fullmatch(r"[0-9a-f]{64}", receipt["digest"]):
        errors.append("receipt digest must be a lowercase SHA-256 value")
    elif digest is not None and receipt["digest"] != digest:
        errors.append("receipt digest does not match the configured paths")
    answers = receipt.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(SELF_REVIEW_QUESTIONS):
        errors.append("receipt must answer exactly seven self-review questions")
    else:
        for question in SELF_REVIEW_QUESTIONS:
            answer = answers[question]
            if not isinstance(answer, str) or not answer.strip() or len(answer) > MAX_ANSWER_CHARS:
                errors.append(f"self-review answer is invalid: {question}")
    evidence = [f"bound {len(normalized)} paths to sha256 {digest}"] if digest else []
    return _result("self_review", "FAIL" if errors else "PASS", errors, evidence)


_CHECKERS = {
    "shape_version": _check_shape_version,
    "silent_handlers": _check_silent_handlers,
    "convention_sync": _check_convention_sync,
    "runtime": _check_runtime,
    "selftests": _check_selftests,
    "visual": _check_visual,
    "self_review": _check_self_review,
}


def run_preflight(root: Path, config: Any) -> dict[str, Any]:
    root = root.resolve()
    global_errors: list[str] = []
    if not isinstance(config, dict):
        config = {}
        global_errors.append("configuration must be a JSON object")
    if config.get("version") != 2:
        global_errors.append("configuration version must equal 2")
    configured = config.get("configured")
    if not isinstance(configured, bool):
        global_errors.append("configured must be boolean")
    checks = config.get("checks")
    if not isinstance(checks, dict):
        checks = {}
        global_errors.append("checks must be an object")

    if not global_errors and configured is False:
        if checks:
            global_errors.append("an unconfigured target must use an empty checks object")
        else:
            remedy = config.get("remedy")
            if (
                not isinstance(remedy, list)
                or not remedy
                or len(remedy) > MAX_RULES
                or any(
                    not isinstance(item, str)
                    or not item.strip()
                    or len(item) > MAX_ANSWER_CHARS
                    for item in remedy
                )
            ):
                global_errors.append("an unconfigured target needs a bounded remedy list")
            else:
                return {
                    "ok": False,
                    "status": "NO_GATE",
                    "checks": [
                        _result(name, "NO_GATE", ["target-owned proof is not configured"])
                        for name in CHECK_NAMES
                    ],
                    "errors": ["configure target-owned proof before promotion"],
                    "remedy": remedy,
                    "limits": {
                        "files": MAX_FILES,
                        "total_bytes": MAX_TOTAL_BYTES,
                        "commands": MAX_COMMANDS,
                        "command_output_bytes": MAX_COMMAND_OUTPUT_BYTES,
                        "command_seconds": MAX_COMMAND_SECONDS,
                        "errors": MAX_ERRORS,
                    },
                    "observed": {"files_read": 0, "bytes_read": 0},
                }
    if set(checks) != set(CHECK_NAMES):
        global_errors.append("checks must contain exactly the seven named preflight layers")
    budget = ReadBudget()
    results: list[dict[str, Any]] = []
    for name in CHECK_NAMES:
        try:
            result = _CHECKERS[name](root, checks.get(name), budget)
        except Exception as exc:  # explicit failure boundary for untrusted configuration
            result = _result(name, "FAIL", [f"check could not complete: {type(exc).__name__}"])
        results.append(result)
    if any(result["status"] == "FAIL" for result in results) or global_errors:
        status = "FAIL"
    elif any(result["status"] == "NO_GATE" for result in results):
        status = "NO_GATE"
    else:
        status = "PASS"
    return {
        "ok": status == "PASS",
        "status": status,
        "checks": results,
        "errors": sorted(set(global_errors))[:MAX_ERRORS],
        "limits": {
            "files": MAX_FILES,
            "total_bytes": MAX_TOTAL_BYTES,
            "commands": MAX_COMMANDS,
            "command_output_bytes": MAX_COMMAND_OUTPUT_BYTES,
            "command_seconds": MAX_COMMAND_SECONDS,
            "errors": MAX_ERRORS,
        },
        "observed": {"files_read": budget.files, "bytes_read": budget.total_bytes},
    }


def load_config(root: Path, raw: Path | str) -> Any:
    path, error = _safe_path(root, str(raw))
    if error:
        raise ValueError(f"configuration unavailable: {error}")
    assert path is not None
    data = read_regular_file_bounded(
        path,
        MAX_CONFIG_BYTES,
        boundary=root,
        label="configuration",
    )
    return json.loads(data.decode("utf-8"))


def _fatal_payload(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "NO_GATE",
        "checks": [
            _result(name, "NO_GATE", ["configuration unavailable"])
            for name in CHECK_NAMES
        ],
        "errors": [message],
        "limits": {
            "files": MAX_FILES,
            "total_bytes": MAX_TOTAL_BYTES,
            "commands": MAX_COMMANDS,
            "command_output_bytes": MAX_COMMAND_OUTPUT_BYTES,
            "command_seconds": MAX_COMMAND_SECONDS,
            "errors": MAX_ERRORS,
        },
        "observed": {"files_read": 0, "bytes_read": 0},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("templates/harness/preflight.json"),
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        config = load_config(root, args.config)
        payload = run_preflight(root, config)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        payload = _fatal_payload(f"cannot load configuration: {type(exc).__name__}: {exc}")
    if args.json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        for result in payload["checks"]:
            print(f"{result['status']}: {result['name']}")
            for error in result["errors"]:
                print(f"  {error}")
        for error in payload["errors"]:
            print(f"ERROR: {error}")
        print(f"{payload['status']}: seven-layer preflight")
    if payload["status"] == "PASS":
        return 0
    if payload["status"] == "NO_GATE":
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
