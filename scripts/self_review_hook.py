#!/usr/bin/env python3
"""Bounded, product-neutral checkpoint and self-review hook core."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any

from bounded_process import OutputLimitExceeded, run_bounded
from path_safety import is_link_like, read_regular_file_bounded, reject_linked_path


MAX_INPUT_BYTES = 65_536
MAX_CHECKPOINT_BYTES = 8_192
MAX_HOOK_OUTPUT_BYTES = 8_192
MAX_TREE_ENTRIES = 2_048
MAX_TREE_FILES = 2_048
MAX_TREE_FILE_BYTES = 131_072
MAX_TREE_TOTAL_BYTES = 8_388_608
MAX_GIT_OUTPUT_BYTES = 4_096
MAX_CWD_BYTES = 4_096
MAX_SESSION_ID_BYTES = 1_024
MAX_NUDGES_PER_SESSION = 5
GIT_IDENTITY_BUDGET_SECONDS = 2
LOCK_WAIT_SECONDS = 2
STALE_LOCK_SECONDS = 10
STATE_DIR = Path(".agent-local") / "self-review"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = (
    "What user outcome is now observable?",
    "What changed outside the declared scope?",
    "Which claim lacks a replayable receipt?",
    "Did any test, threshold, or expectation become weaker?",
    "What failure path or degraded state was exercised?",
    "What did this change teach that belongs in a gate?",
    "Is HANDOFF.md current for the next host?",
)
CHECKPOINT_PATTERN = re.compile(
    r"\A# Agent checkpoint\n\n"
    r"- Session fingerprint: `([0-9a-f]{16})`\n"
    r"- Working tree digest: `([0-9a-f]{64})`\n"
    r"- Resume: read `HANDOFF\.md`, inspect the current diff, and rerun the named proof\.\n"
    r"- Stored data: fingerprints only; no prompt or transcript content\.\n\Z"
)
EXCLUDED_TREE_DIRECTORIES = frozenset(
    {
        ".agent-local",
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
        "venv",
    }
)
SENSITIVE_TREE_PARTS = frozenset({".aws", ".ssh", "secret", "secrets"})
SENSITIVE_TREE_NAMES = frozenset(
    {
        "auth.json",
        "claude.local.md",
        "credentials.json",
        "history.jsonl",
        "session.sqlite",
        "settings.local.json",
        "state.sqlite",
    }
)
EXCLUDED_TREE_PATHS = frozenset(
    {(".claude", "skills"), (".claude", "worktrees")}
)
SENSITIVE_TREE_SUFFIXES = frozenset(
    {".db", ".key", ".p12", ".pem", ".pfx", ".sqlite", ".sqlite3"}
)


def read_payload(stream: Any) -> dict[str, Any]:
    raw = stream.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError(f"hook input exceeds {MAX_INPUT_BYTES} bytes")
    if not raw.strip():
        return {}
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("hook input must be a JSON object")
    return value


def _digest_field(digest: Any, label: str, value: bytes) -> None:
    encoded_label = label.encode("ascii")
    digest.update(len(encoded_label).to_bytes(2, "big"))
    digest.update(encoded_label)
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def _sensitive_tree_path(relative: Path) -> bool:
    lowered = tuple(part.lower() for part in relative.parts)
    name = lowered[-1] if lowered else ""
    return (
        any(part in SENSITIVE_TREE_PARTS for part in lowered)
        or name == ".env"
        or (name.startswith(".env.") and name != ".env.example")
        or name in SENSITIVE_TREE_NAMES
        or Path(name).suffix in SENSITIVE_TREE_SUFFIXES
    )


def _bounded_file_fingerprint(path: Path, remaining: int) -> tuple[bytes, int]:
    """Return complete bounded content without following a symbolic link."""

    allowance = min(MAX_TREE_FILE_BYTES, remaining)
    label = "tree file" if allowance == MAX_TREE_FILE_BYTES else "tree"
    content = read_regular_file_bounded(
        path,
        allowance,
        boundary=Path(path.anchor),
        label=label,
    )
    return content, len(content)


def tree_digest(root: Path) -> str:
    """Hash a bounded, copy-safe content view without opening credential stores."""

    digest = hashlib.sha256(b"self-review-tree-v2\0")
    try:
        root_absolute = Path(os.path.abspath(root))
        if is_link_like(root_absolute):
            raise ValueError("tree root is link-like")
        root_resolved = root_absolute.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("tree root is unavailable") from exc
    if not root_resolved.is_dir():
        raise ValueError("tree root is not a directory")

    pending = [Path(".")]
    entries_seen = 0
    files_seen = 0
    bytes_read = 0
    while pending:
        relative_directory = pending.pop()
        current = root_resolved / relative_directory
        try:
            reject_linked_path(current, root_resolved, label="tree")
        except (OSError, ValueError):
            _digest_field(
                digest,
                "linked-directory",
                relative_directory.as_posix().encode("utf-8", "surrogateescape"),
            )
            continue
        names: list[str] = []
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    entries_seen += 1
                    if entries_seen > MAX_TREE_ENTRIES:
                        raise ValueError(
                            f"tree entry count exceeds the {MAX_TREE_ENTRIES}-entry digest cap"
                        )
                    names.append(entry.name)
        except OSError as exc:
            raise ValueError("tree directory could not be scanned") from exc

        for name in reversed(sorted(names)):
            relative = relative_directory / name
            path = root_resolved / relative
            relative_bytes = relative.as_posix().encode("utf-8", "surrogateescape")
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise ValueError("tree entry could not be inspected") from exc
            if is_link_like(path):
                _digest_field(digest, "link-like", relative_bytes)
                continue
            if stat.S_ISDIR(metadata.st_mode):
                lowered_parts = tuple(part.lower() for part in relative.parts)
                if (
                    name.lower() in EXCLUDED_TREE_DIRECTORIES
                    or lowered_parts in EXCLUDED_TREE_PATHS
                ):
                    _digest_field(digest, "excluded-directory", relative_bytes)
                    continue
                _digest_field(digest, "directory", relative_bytes)
                pending.append(relative)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                _digest_field(digest, "non-regular", relative_bytes)
                continue
            if relative.parts == (".git",):
                _digest_field(digest, "excluded-file", relative_bytes)
                continue
            if _sensitive_tree_path(relative):
                _digest_field(digest, "sensitive-file-redacted", relative_bytes)
                continue
            files_seen += 1
            if files_seen > MAX_TREE_FILES:
                raise ValueError(
                    f"tree file count exceeds the {MAX_TREE_FILES}-file digest cap"
                )
            try:
                fingerprint, consumed = _bounded_file_fingerprint(
                    path,
                    MAX_TREE_TOTAL_BYTES - bytes_read,
                )
            except OSError as exc:
                raise ValueError("tree file could not be read") from exc
            bytes_read += consumed
            _digest_field(digest, "file-path", relative_bytes)
            _digest_field(digest, "file-content", fingerprint)
    return digest.hexdigest()


def session_key(host: str, payload: dict[str, Any]) -> str:
    field = "conversation_id" if host == "cursor" else "session_id"
    value = payload.get(field)
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError(f"{host} hook input needs a non-empty {field}")
    raw_identifier = value.encode("utf-8")
    if len(raw_identifier) > MAX_SESSION_ID_BYTES:
        raise ValueError(f"{host} hook {field} exceeds its cap")
    raw = host.encode("ascii") + b"\0" + field.encode("ascii") + b"\0" + raw_identifier
    return hashlib.sha256(raw).hexdigest()[:16]


def _git_path(root: Path, argument: str, deadline: float) -> Path:
    """Resolve one Git-owned path with a deadline and bounded output."""

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Git worktree identity budget exhausted")
    clean_environment = {
        key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")
    }
    try:
        completed = run_bounded(
            ["git", "-C", str(root), "rev-parse", "--path-format=absolute", argument],
            cwd=root,
            timeout_seconds=remaining,
            output_limit=MAX_GIT_OUTPUT_BYTES,
            env=clean_environment,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("Git worktree identity budget exhausted") from exc
    except OutputLimitExceeded as exc:
        raise ValueError("Git path output exceeded its cap") from exc
    raw = completed.output
    if completed.returncode != 0:
        raise ValueError("event working directory is not in the project repository")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("Git path output is not UTF-8") from exc
    if len(lines) != 1 or not lines[0]:
        raise ValueError("Git path output was not one path")
    result = Path(lines[0])
    if not result.is_absolute():
        raise ValueError("Git path output was not absolute")
    return Path(os.path.abspath(result))


def resolve_event_root(
    host: str,
    payload: dict[str, Any],
    project_root: Path = PROJECT_ROOT,
) -> Path:
    """Select the active project or its generated Claude worktree without escaping it."""

    base_absolute = Path(os.path.abspath(project_root))
    if is_link_like(base_absolute) or not base_absolute.is_dir():
        raise ValueError("hook project root must be a local directory")
    base = base_absolute.resolve(strict=True)
    if host != "claude":
        return base
    raw_cwd = payload.get("cwd")
    if raw_cwd is None:
        return base
    if not isinstance(raw_cwd, str) or not raw_cwd or "\0" in raw_cwd:
        raise ValueError("hook cwd must be a non-empty path string")
    if len(raw_cwd.encode("utf-8")) > MAX_CWD_BYTES:
        raise ValueError("hook cwd exceeds its path cap")
    supplied = Path(raw_cwd)
    if not supplied.is_absolute():
        raise ValueError("hook cwd must be absolute")
    candidate = Path(os.path.abspath(supplied))
    reject_linked_path(candidate, base, label="hook cwd")
    if not candidate.is_dir():
        raise ValueError("hook cwd must be a local directory")
    relative_cwd = candidate.relative_to(base)
    lowered = tuple(part.lower() for part in relative_cwd.parts[:2])
    if lowered != (".claude", "worktrees"):
        return base
    if len(relative_cwd.parts) < 3:
        raise ValueError("hook cwd does not identify one generated worktree")

    declared_root = base.joinpath(*relative_cwd.parts[:3])
    reject_linked_path(declared_root, base, label="generated worktree")
    deadline = time.monotonic() + GIT_IDENTITY_BUDGET_SECONDS
    active_root_lexical = _git_path(candidate, "--show-toplevel", deadline)
    reject_linked_path(active_root_lexical, base, label="active worktree")
    active_root = active_root_lexical.resolve(strict=True)
    if os.path.normcase(str(active_root)) != os.path.normcase(str(declared_root.resolve(strict=True))):
        raise ValueError("hook cwd is not inside the named generated worktree")

    base_common = _git_path(base, "--git-common-dir", deadline)
    active_common = _git_path(active_root, "--git-common-dir", deadline)
    for common in (base_common, active_common):
        if is_link_like(common) or not common.is_dir():
            raise ValueError("Git common metadata must be a local directory")
    base_common = base_common.resolve(strict=True)
    active_common = active_common.resolve(strict=True)
    if os.path.normcase(os.path.normpath(str(base_common))) != os.path.normcase(
        os.path.normpath(str(active_common))
    ):
        raise ValueError("hook cwd does not share the project Git metadata")
    return active_root


def state_path(root: Path) -> Path:
    return state_directory(root, create=False) / "state.json"


def state_directory(root: Path, *, create: bool) -> Path:
    """Return the local state directory only when no component is a symlink."""

    root_absolute = Path(os.path.abspath(root))
    if is_link_like(root_absolute) or not root_absolute.is_dir():
        raise ValueError("checkpoint root must be a local directory")
    current = root_absolute.resolve(strict=True)
    for part in STATE_DIR.parts:
        current = current / part
        if is_link_like(current):
            raise ValueError("checkpoint state path must use local directories")
        if current.exists():
            if not current.is_dir():
                raise ValueError("checkpoint state path must use local directories")
        elif create:
            current.mkdir(exist_ok=True)
            if is_link_like(current) or not current.is_dir():
                raise ValueError("checkpoint state path must use local directories")
    return current


def read_state_text(root: Path, name: str) -> str | None:
    directory = state_directory(root, create=False)
    path = directory / name
    if not path.exists() and not is_link_like(path):
        return None
    if is_link_like(path) or not path.is_file():
        raise ValueError(f"{name} is unavailable or invalid")
    try:
        data = read_regular_file_bounded(
            path,
            MAX_CHECKPOINT_BYTES,
            boundary=root,
            label="checkpoint input",
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"{name} is unavailable or invalid") from exc
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{name} is unavailable or invalid") from exc


def load_state(root: Path) -> dict[str, Any]:
    content = read_state_text(root, "state.json")
    if content is None:
        return {"sessions": {}}
    try:
        value = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("state.json is unavailable or invalid") from exc
    if not isinstance(value, dict) or set(value) != {"sessions"}:
        raise ValueError("state.json is unavailable or invalid")
    sessions = value.get("sessions")
    if not isinstance(sessions, dict) or len(sessions) > 64:
        raise ValueError("state.json is unavailable or invalid")
    for key, record in sessions.items():
        if not isinstance(key, str) or re.fullmatch(r"[0-9a-f]{16}", key) is None:
            raise ValueError("state.json is unavailable or invalid")
        if not isinstance(record, dict) or set(record) != {"count", "digest"}:
            raise ValueError("state.json is unavailable or invalid")
        count = record.get("count")
        digest = record.get("digest")
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 0 <= count <= MAX_NUDGES_PER_SESSION
            or not isinstance(digest, str)
            or (digest and re.fullmatch(r"[0-9a-f]{64}", digest) is None)
        ):
            raise ValueError("state.json is unavailable or invalid")
    return value


def atomic_write(root: Path, name: str, content: str) -> None:
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_CHECKPOINT_BYTES:
        raise ValueError("checkpoint output cap exceeded")
    directory = state_directory(root, create=True)
    path = directory / name
    reject_linked_path(path, root, label="checkpoint output")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def state_lock(root: Path):
    """Serialize checkpoint updates across concurrent host events."""

    lock_path = state_directory(root, create=True) / "state.lock"
    reject_linked_path(lock_path, root, label="checkpoint lock")
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(descriptor, str(os.getpid()).encode("ascii"))
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EEXIST}:
                raise
            try:
                stale = time.time() - lock_path.stat().st_mtime > STALE_LOCK_SECONDS
            except OSError:
                stale = False
            if stale:
                try:
                    lock_path.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError("checkpoint state lock budget exhausted")
            time.sleep(0.01)
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def checkpoint_text(session_fingerprint: str, digest: str) -> str:
    return (
        "# Agent checkpoint\n\n"
        f"- Session fingerprint: `{session_fingerprint}`\n"
        f"- Working tree digest: `{digest}`\n"
        "- Resume: read `HANDOFF.md`, inspect the current diff, and rerun the named proof.\n"
        "- Stored data: fingerprints only; no prompt or transcript content.\n"
    )


def write_checkpoint(host: str, root: Path, payload: dict[str, Any]) -> str:
    digest = tree_digest(root)
    content = checkpoint_text(session_key(host, payload), digest)
    atomic_write(root, "CHECKPOINT.md", content)
    return digest


def start_output(host: str, root: Path) -> dict[str, Any]:
    context = "No prior checkpoint exists. Read HANDOFF.md before changing files."
    try:
        checkpoint = read_state_text(root, "CHECKPOINT.md")
    except ValueError:
        checkpoint = None
        context = (
            "Prior checkpoint is unavailable or invalid. Read HANDOFF.md and "
            "re-establish continuity before relying on resumed state."
        )
    if checkpoint is not None:
        match = CHECKPOINT_PATTERN.fullmatch(checkpoint)
        if match is None:
            context = (
                "Prior checkpoint is unavailable or invalid. Read HANDOFF.md and "
                "re-establish continuity before relying on resumed state."
            )
        else:
            context = checkpoint_text(match.group(1), match.group(2))
    if host == "cursor":
        return {"additional_context": context}
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }


def stop_output(host: str, root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("stop_hook_active") is True:
        return {}
    if host == "cursor":
        status = payload.get("status")
        if status not in {"completed", "aborted", "error"}:
            raise ValueError("cursor stop status must be completed, aborted, or error")
        if status != "completed":
            return {}
        loop_count = payload.get("loop_count")
        if isinstance(loop_count, bool) or not isinstance(loop_count, int) or loop_count < 0:
            raise ValueError("cursor stop loop_count must be a non-negative integer")
        if loop_count >= MAX_NUDGES_PER_SESSION:
            return {}
    if host == "claude":
        for field in ("background_tasks", "session_crons"):
            value = payload.get(field, [])
            if not isinstance(value, list):
                raise ValueError(f"claude stop {field} must be an array")
            if value:
                return {}
    digest = tree_digest(root)
    key = session_key(host, payload)
    path = state_path(root)
    with state_lock(root):
        state = load_state(root)
        sessions = state["sessions"]
        record = sessions.get(key)
        if record is None:
            record = {"count": 0, "digest": ""}
        count = record.get("count", 0)
        should_nudge = digest != record.get("digest") and count < MAX_NUDGES_PER_SESSION
        if should_nudge:
            record = {"count": count + 1, "digest": digest}
        sessions[key] = record
        if len(sessions) > 64:
            retained_peers = [item for item in sorted(sessions) if item != key][-63:]
            sessions = {item: sessions[item] for item in retained_peers}
            sessions[key] = record
        atomic_write(root, "state.json", json.dumps({"sessions": sessions}, sort_keys=True))
    if not should_nudge:
        return {}
    message = "Self-review before yielding:\n" + "\n".join(
        f"{index}. {question}" for index, question in enumerate(QUESTIONS, 1)
    )
    if host == "cursor":
        return {"followup_message": message}
    if host == "claude":
        return {"decision": "block", "reason": message}
    return {"decision": "block", "reason": message}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=("codex", "claude", "cursor"), required=True)
    parser.add_argument(
        "--event", choices=("session-start", "pre-compact", "stop"), required=True
    )
    args = parser.parse_args()
    try:
        payload = read_payload(sys.stdin)
        root = resolve_event_root(args.host, payload)
        if args.event == "pre-compact":
            write_checkpoint(args.host, root, payload)
            output: dict[str, Any] = {}
        elif args.event == "session-start":
            output = start_output(args.host, root)
        else:
            output = stop_output(args.host, root, payload)
        serialized = json.dumps(output, sort_keys=True)
        if len(serialized.encode("utf-8")) > MAX_HOOK_OUTPUT_BYTES:
            raise ValueError("hook output cap exceeded")
        print(serialized)
        return 0
    except (OSError, TimeoutError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        diagnostic = f"{type(exc).__name__}: {exc}".encode("utf-8", "replace")
        diagnostic = diagnostic[: MAX_HOOK_OUTPUT_BYTES - 1]
        print(diagnostic.decode("utf-8", "ignore"), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
