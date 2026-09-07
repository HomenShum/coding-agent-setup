#!/usr/bin/env python3
"""Plan additive project setup; create only reviewed missing files, never activate hosts."""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True  # Planning must also be read-only when the kit is the target.

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat

from bounded_process import run_bounded
from git_safety import clean_git_environment
from path_safety import is_link_like, read_regular_file_bounded, reject_linked_path
from sync_skills import canonical_skills, skill_files, tree_digest

ROOT = Path(__file__).absolute().parents[1]
MAX_FILES = 256
MAX_ENTRIES = 1024
MAX_FILE_BYTES = 1_048_576
MAX_TOTAL_BYTES = 16 * MAX_FILE_BYTES
MAX_PLAN_BYTES = 2 * MAX_FILE_BYTES
TOOLS = (
    "agent_preflight.py", "prove_preflight_mutations.py", "validate_agent_state.py",
    "sync_skills.py", "self_review_hook.py", "setup_doctor.py", "path_safety.py",
    "bounded_process.py", "git_safety.py", "check_branch_stack.py", "check_claim_language.py",
    "validate_skill_receipt.py", "bootstrap_learning.py", "outcome_review.py", "deployment_profile.py",
)


def digest(content):
    return hashlib.sha256(content).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


class SetupError(ValueError):
    pass


def fail(code):
    raise SetupError(code)


def bounded(path, boundary=ROOT):
    return read_regular_file_bounded(path, MAX_FILE_BYTES, boundary=boundary, label="setup file")


def identity(path):
    value = path.stat()
    return [value.st_dev, value.st_ino]


def git(root, *args):
    result = run_bounded(
        ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *args],
        cwd=root, timeout_seconds=5, output_limit=4096, env=clean_git_environment(),
    )
    return result.returncode, os.fsdecode(result.output).strip()


def target_identity(target):
    root = Path(os.path.abspath(target))
    reject_linked_path(root, Path(root.anchor), label="target")
    if not root.is_dir():
        fail("TARGET_DIRECTORY_REQUIRED")
    code, top = git(root, "rev-parse", "--show-toplevel")
    if code or os.path.normcase(os.path.abspath(top)) != os.path.normcase(str(root)):
        fail("EXACT_GIT_WORKTREE_ROOT_REQUIRED")
    code, directory = git(root, "rev-parse", "--absolute-git-dir")
    if code or not Path(directory).is_dir():
        fail("GIT_DIRECTORY_UNAVAILABLE")
    branch_code, branch = git(root, "symbolic-ref", "-q", "HEAD")
    head_code, head = git(root, "rev-parse", "--verify", "-q", "HEAD^{commit}")
    if head_code:
        # git init has a symbolic branch and no reference yet; a broken existing ref is not unborn.
        missing, _ = git(root, "show-ref", "--verify", "--quiet", branch)
        if branch_code or not branch.startswith("refs/heads/") or missing != 1:
            fail("INVALID_GIT_HEAD")
        head = None
    return {"root": str(root), "root_identity": identity(root), "git_directory": directory,
            "git_identity": identity(Path(directory)), "branch": None if branch_code else branch,
            "head": head, "unborn": head is None}


def materialization():
    """The one maintained map for both fresh and existing projects."""
    files = {}

    def add(source, target):
        if target in files or len(files) >= MAX_FILES:
            fail("DUPLICATE_OR_TOO_MANY_DESTINATIONS")
        files[target] = ROOT / source

    def tree(source, target, exclude=()):
        pending = [ROOT / source]
        entries = 0
        while pending:
            directory = pending.pop()
            reject_linked_path(directory, ROOT, label="template")
            with os.scandir(directory) as children:
                for item in children:
                    entries += 1
                    if entries > MAX_ENTRIES or is_link_like(Path(item.path)):
                        fail("UNSAFE_OR_OVERSIZED_TEMPLATE_TREE")
                    if item.is_dir(follow_symlinks=False):
                        pending.append(Path(item.path))
                    elif item.is_file(follow_symlinks=False):
                        relative = Path(item.path).relative_to(ROOT / source).as_posix()
                        if relative not in exclude:
                            add(Path(item.path).relative_to(ROOT), (Path(target) / relative).as_posix())
                    else:
                        fail("NONREGULAR_TEMPLATE")

    tree("templates/project", ".")
    for source, destination in (
        ("templates/codex/project.config.toml", ".codex/config.toml"),
        ("templates/claude/settings.json", ".claude/settings.json"),
        ("templates/cursor/mcp.json", ".cursor/mcp.json"),
    ):
        add(source, destination)
    for host in ("codex", "claude", "cursor"):
        tree(f"templates/{host}/agents", f".{host}/agents")
    tree("templates/harness", "templates/harness", ("preflight.json", "self-review.json"))
    for name in ("preflight", "self-review"):
        add(f"templates/harness/{name}.target.json", f"templates/harness/{name}.json")
    tree("templates/learning", "templates/learning")
    for name in TOOLS:
        add(f"scripts/{name}", f"scripts/{name}")
    add("tests/test_preflight_mutations.py", "tests/test_preflight_mutations.py")
    for skill in canonical_skills(ROOT / "templates/project/.agents/skills"):
        for path in skill_files(skill):
            add(path.relative_to(ROOT), f".claude/skills/{skill.name}/{path.relative_to(skill).as_posix()}")
    content = {name: bounded(files[name]) for name in sorted(files)}
    if sum(map(len, content.values())) > MAX_TOTAL_BYTES:
        fail("TEMPLATE_BYTE_LIMIT")
    rows = [{"destination": name, "source": files[name].relative_to(ROOT).as_posix(),
             "bytes": len(data), "sha256": digest(data)} for name, data in content.items()]
    return rows, content


def classify(root, name, source):
    target = root / name
    try:
        reject_linked_path(target, root, label="destination")
        for parent in target.parents:
            if parent == root:
                break
            if parent.exists() and not parent.is_dir():
                fail("PARENT_NOT_DIRECTORY")
        try:
            metadata = target.lstat()
        except FileNotFoundError:
            return {"state": "MISSING", "destination_sha256": None}
        if not stat.S_ISREG(metadata.st_mode):
            return {"state": "BLOCKED", "destination_sha256": None, "reason": "NONREGULAR_DESTINATION"}
        data = bounded(target, root)
        return {"state": "IDENTICAL" if data == source else "CONFLICT", "destination_sha256": digest(data)}
    except (OSError, ValueError):
        return {"state": "BLOCKED", "destination_sha256": None, "reason": "UNSAFE_UNREADABLE_OR_OVERSIZED"}


def canonical_ready(root, skill, selected, content):
    """Compare complete bounded path/byte sets, including local extras, just like tree_digest."""
    prefix = f".agents/skills/{skill}/"
    expected = {name[len(prefix):]: data for name, data in content.items() if name.startswith(prefix)}
    target = root / ".agents/skills" / skill
    reject_linked_path(target, root, label="canonical skill")
    actual = {}
    if target.exists():
        for path in skill_files(target):
            actual[path.relative_to(target).as_posix()] = bounded(path, root)
    if set(actual) - set(expected) or any(data != expected[name] for name, data in actual.items()):
        return False
    missing = set(expected) - set(actual)
    if any(prefix + name not in selected for name in missing):
        return False
    if not missing:
        return tree_digest(target) == tree_digest(ROOT / "templates/project/.agents/skills" / skill)
    return True  # Every missing byte is bound to an explicitly selected canonical addition.


def make_plan(target):
    target_info = target_identity(target)
    root = Path(target_info["root"])
    source, content = materialization()
    rows = [{**row, **classify(root, row["destination"], content[row["destination"]])} for row in source]
    missing = {x["destination"] for x in rows if x["state"] == "MISSING"}
    skills = {}
    for row in rows:
        name = row["destination"]
        if name.startswith(".claude/skills/"):
            skill = name.split("/")[2]
            if skill not in skills:
                try:
                    skills[skill] = canonical_ready(root, skill, missing, content)
                except (ValueError, OSError):
                    skills[skill] = False
            row["canonical_skill_ready_after_missing_additions"] = skills[skill]
    kit_code, revision = git(ROOT, "rev-parse", "--verify", "-q", "HEAD")
    result = {"version": 1, "kit": {"revision": None if kit_code else revision,
              "owner_sha256": digest(bounded(Path(__file__)))}, "target": target_info, "rows": rows,
              "ready": False, "activation": False}
    result["plan_sha256"] = digest(encoded(result))
    return result


# These private operations share one creation boundary for project files and
# external evidence. No mutation follows a multi-component checked pathname.
if os.name == "nt":
    import ctypes as c
    from ctypes import wintypes as w
    import msvcrt

    class _UnicodeString(c.Structure):
        _fields_ = [("Length", w.USHORT), ("MaximumLength", w.USHORT), ("Buffer", w.LPWSTR)]

    class _ObjectAttributes(c.Structure):
        _fields_ = [("Length", w.ULONG), ("RootDirectory", w.HANDLE),
                    ("ObjectName", c.POINTER(_UnicodeString)), ("Attributes", w.ULONG),
                    ("SecurityDescriptor", c.c_void_p), ("SecurityQualityOfService", c.c_void_p)]

    class _IoStatus(c.Structure):
        _fields_ = [("Status", c.c_void_p), ("Information", c.c_size_t)]

    class _AttributeTag(c.Structure):
        _fields_ = [("attributes", w.DWORD), ("tag", w.DWORD)]

    _kernel = c.WinDLL("kernel32", use_last_error=True)
    _native = c.WinDLL("ntdll")
    _kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    _kernel.CreateFileW.restype = w.HANDLE
    _kernel.CloseHandle.argtypes = [w.HANDLE]
    _kernel.CloseHandle.restype = w.BOOL
    _kernel.GetFileInformationByHandleEx.argtypes = [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
    _kernel.GetFileInformationByHandleEx.restype = w.BOOL
    _native.NtCreateFile.argtypes = [c.POINTER(w.HANDLE), w.DWORD, c.POINTER(_ObjectAttributes),
        c.POINTER(_IoStatus), c.c_void_p, w.ULONG, w.ULONG, w.ULONG, w.ULONG, c.c_void_p, w.ULONG]
    _native.NtCreateFile.restype = c.c_long
    _native.RtlNtStatusToDosError.argtypes = [c.c_long]
    _native.RtlNtStatusToDosError.restype = w.ULONG


def _close_directory(handle):
    if os.name == "nt":
        if not _kernel.CloseHandle(handle):
            raise c.WinError(c.get_last_error())
    else:
        os.close(handle)


def _validate_directory(handle):
    if os.name == "nt":
        info = _AttributeTag()
        if not _kernel.GetFileInformationByHandleEx(handle, 9, c.byref(info), c.sizeof(info)):
            raise c.WinError(c.get_last_error())
        if not info.attributes & 0x10 or info.attributes & 0x400:
            fail("NON_DIRECTORY_OR_REPARSE_HANDLE")
    elif not stat.S_ISDIR(os.fstat(handle).st_mode):
        fail("NON_DIRECTORY_HANDLE")


def _relative_open(parent, name, *, directory, create):
    if not name or name in (".", "..") or any(x in name for x in ("/", "\\", ":", "\0")):
        fail("SINGLE_COMPONENT_REQUIRED")
    if os.name == "nt":
        text = c.create_unicode_buffer(name)
        length = len(name.encode("utf-16-le"))
        if length > 65532:
            fail("COMPONENT_TOO_LONG")
        string = _UnicodeString(length, length + 2, c.cast(text, w.LPWSTR))
        attrs = _ObjectAttributes(c.sizeof(_ObjectAttributes), parent, c.pointer(string), 0x40, None, None)
        io, output = _IoStatus(), w.HANDLE()
        # FILE_OPEN/FILE_CREATE; directory/non-directory; synchronous, open reparse
        # itself so the handle query rejects it. Keep delete sharing disabled.
        # FILE_READ_ATTRIBUTES is required by the descriptor's fstat/readback.
        status = _native.NtCreateFile(c.byref(output), (0x80000000 if directory else 0x40000080) | 0x100000,
            c.byref(attrs), c.byref(io), None, 0x10 if directory else 0x80,
            3 if directory else 1, 2 if create else 1,
            (1 if directory else 0x40) | 0x20 | 0x00200000, None, 0)
        if status < 0:
            raise c.WinError(_native.RtlNtStatusToDosError(status))
        handle = output.value
        try:
            if directory:
                _validate_directory(handle)
                return handle
            # open_osfhandle transfers HANDLE ownership to the returned descriptor.
            return msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
        except BaseException:
            _kernel.CloseHandle(handle)
            raise
    if directory:
        if create:
            os.mkdir(name, 0o700, dir_fd=parent)
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    return os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)


@contextmanager
def _creation_parent(path, root=None, receipt=None):
    """Hold a bounded directory chain; create only selected-file parents."""
    path = Path(os.path.abspath(path))
    if len(path.parts) > 64:
        fail("DIRECTORY_DEPTH_LIMIT")
    if os.name != "nt" and (not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY")
                            or os.open not in os.supports_dir_fd or os.mkdir not in os.supports_dir_fd):
        fail("DIRECTORY_RELATIVE_CREATION_UNSUPPORTED")
    handles = []
    try:
        if os.name == "nt":
            handle = _kernel.CreateFileW(path.anchor, 0x80000000, 3, None, 3, 0x02000000 | 0x00200000, None)
            if handle == c.c_void_p(-1).value:
                raise c.WinError(c.get_last_error())
        else:
            handle = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        handles.append(handle)
        _validate_directory(handle)
        current = Path(path.anchor)
        for name in path.parts[1:]:
            current = current / name
            try:
                handle = _relative_open(handles[-1], name, directory=True, create=False)
            except FileNotFoundError:
                if receipt is None or current == root or not current.is_relative_to(root):
                    raise
                relative = current.relative_to(root).as_posix()
                receipt.record(path=relative, state="PENDING_DIRECTORY")
                try:
                    handle = _relative_open(handles[-1], name, directory=True, create=True)
                    state = "CREATED_DIRECTORY"
                except FileExistsError:
                    handle = _relative_open(handles[-1], name, directory=True, create=False)
                    state = "EXISTING_DIRECTORY"
                handles.append(handle)
                receipt.record(path=relative, state=state)
                continue
            handles.append(handle)
        yield handles[-1]
    finally:
        # Close every acquired handle even if a close itself reports an error.
        error = None
        for handle in reversed(handles):
            try:
                _close_directory(handle)
            except OSError as exc:
                error = exc
        if error is not None:
            raise error


def external_fd(path, target):
    path = Path(os.path.abspath(path))
    if any(path.is_relative_to(root) for root in (target, ROOT)):
        fail("OUTPUT_MUST_BE_EXTERNAL_TO_TARGET_AND_KIT")
    reject_linked_path(path, Path(path.anchor), label="external output")
    fd = None
    try:
        with _creation_parent(path.parent) as parent:
            fd = _relative_open(parent, path.name, directory=False, create=True)
        return fd
    except BaseException:
        if fd is not None:
            os.close(fd)
        raise


def write_all(fd, content):
    view = memoryview(content)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("write made no progress")
        view = view[written:]
    os.fsync(fd)


class Receipt:
    def __init__(self, path, root):
        self.fd = external_fd(path, root)
        self.events = []
        self.durable = 0

    def record(self, **event):
        if len(self.events) >= MAX_ENTRIES:
            fail("RECEIPT_EVENT_LIMIT")
        self.events.append({"sequence": len(self.events), **event})
        write_all(self.fd, encoded(self.events[-1]) + b"\n")
        self.durable = len(self.events)

    def close(self):
        os.close(self.fd)


def create_missing(root, name, data, receipt):
    target = root / name
    with _creation_parent(target.parent, root, receipt) as parent:
        receipt.record(path=name, state="PENDING_FILE")
        fd = _relative_open(parent, target.name, directory=False, create=True)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                fail("NONREGULAR_CREATED_FILE")
            write_all(fd, data)
        except BaseException:
            # The durable PENDING_FILE remains even if the receipt device itself fails.
            receipt.record(path=name, state="PARTIAL_FILE", bytes=os.fstat(fd).st_size)
            raise
        finally:
            os.close(fd)
    actual = bounded(target, root)
    if actual != data:
        fail("CREATED_FILE_READBACK_CHANGED")
    receipt.record(path=name, state="CREATED_FILE", bytes=len(actual), sha256=digest(actual))


def load_plan(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail("DUPLICATE_PLAN_KEY")
            result[key] = value
        return result
    return json.loads(read_regular_file_bounded(path, MAX_PLAN_BYTES, boundary=Path(path.absolute().anchor)),
                      object_pairs_hook=pairs, parse_constant=lambda _: fail("NONFINITE_PLAN_VALUE"))


def apply_plan(target, plan, included, all_missing, receipt_path):
    receipt = None
    result = {"status": "FAILED", "ready": False, "activation": False}
    try:
        if not isinstance(plan, dict) or set(plan) != {"version", "kit", "target", "rows", "ready", "activation", "plan_sha256"}:
            fail("INVALID_PLAN")
        unsigned = {k: v for k, v in plan.items() if k != "plan_sha256"}
        if plan["plan_sha256"] != digest(encoded(unsigned)):
            fail("PLAN_DIGEST_MISMATCH")
        current = make_plan(target)
        if any(plan[k] != current[k] for k in ("version", "kit", "target", "ready", "activation")):
            fail("STALE_PLAN_IDENTITY")
        if not isinstance(plan["rows"], list) or len(plan["rows"]) != len(current["rows"]):
            fail("INVALID_PLAN_ROWS")
        old = {}
        fields = {"destination", "source", "bytes", "sha256"}
        for row, expected in zip(plan["rows"], current["rows"]):
            if not isinstance(row, dict) or set(row) != set(expected) or any(row[k] != expected[k] for k in fields):
                fail("UNRECOGNIZED_PLAN_MAPPING")
            if row["state"] not in {"MISSING", "IDENTICAL", "CONFLICT", "BLOCKED"}:
                fail("INVALID_PLAN_STATE")
            old[row["destination"]] = row
        selected = sorted({x["destination"] for x in plan["rows"] if x["state"] == "MISSING"} if all_missing else set(included))
        if not selected or len(selected) != len(included) and not all_missing or any(x not in old for x in selected):
            fail("EXPLICIT_UNIQUE_SELECTION_REQUIRED")
        live = {x["destination"]: x for x in current["rows"]}
        for name in selected:
            if old[name]["state"] not in {"MISSING", "IDENTICAL"} or live[name]["state"] not in {"MISSING", "IDENTICAL"}:
                fail("SELECTED_DESTINATION_CONFLICT")
            if old[name]["state"] == "IDENTICAL" and live[name]["state"] != "IDENTICAL":
                fail("STALE_IDENTICAL_DESTINATION")
        root = Path(current["target"]["root"])
        sources, content = materialization()
        if len(sources) != len(current["rows"]) or any(any(row[k] != expected[k] for k in fields) for row, expected in zip(sources, current["rows"])):
            fail("SOURCE_CHANGED_BEFORE_WRITE")
        for skill in {name.split("/")[2] for name in selected if name.startswith(".claude/skills/")}:
            if not canonical_ready(root, skill, set(selected), content):
                fail("CANONICAL_SKILL_CONFLICT_OR_INCOMPLETE_SELECTION")
        receipt = Receipt(receipt_path, root)
        receipt.record(state="STARTED", plan_sha256=plan["plan_sha256"], selected=selected, target=current["target"])
        if target_identity(root) != current["target"]:
            fail("TARGET_CHANGED_BEFORE_WRITE")
        for name in selected:
            if name.startswith(".claude/skills/") and not canonical_ready(root, name.split("/")[2], set(), content):
                fail("CANONICAL_SKILL_CHANGED")
            state = classify(root, name, content[name])
            if state["state"] == "IDENTICAL":
                receipt.record(path=name, state="IDENTICAL", sha256=state["destination_sha256"])
            elif state["state"] == "MISSING":
                create_missing(root, name, content[name], receipt)
            else:
                fail("DESTINATION_CHANGED_DURING_APPLY")
        final = make_plan(root)
        unresolved = [{"path": x["destination"], "state": x["state"]} for x in final["rows"]
                      if x["state"] != "IDENTICAL" or x.get("canonical_skill_ready_after_missing_additions") is False]
        result.update(status="APPLIED_WITH_UNRESOLVED_ITEMS" if unresolved else "UNCONFIGURED",
                      unresolved=unresolved, plan_sha256=plan["plan_sha256"])
        receipt.record(state="COMPLETED", **result)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        result.update(status="FAILED", reason=str(exc) if isinstance(exc, SetupError) else type(exc).__name__)
        if receipt is not None and receipt.durable == len(receipt.events):
            try:
                receipt.record(state="FAILED", reason=result["reason"])
            except OSError:
                result["receipt_failure"] = True
    finally:
        if receipt is not None:
            result.update(events=receipt.events, durable_events=receipt.durable)
            if receipt.durable != len(receipt.events):
                result.update(status="FAILED", receipt_failure=True)
            try:
                receipt.close()
            except OSError:
                result.update(status="FAILED", receipt_failure=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=("plan", "apply"), default="plan")
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--out", type=Path, help="new external plan file; otherwise stdout only")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--all-missing", action="store_true")
    parser.add_argument("--receipt", type=Path, help="new external append-only JSONL progress receipt")
    args = parser.parse_args()
    try:
        if args.command == "plan":
            if args.plan or args.include or args.all_missing or args.receipt:
                fail("APPLY_OPTIONS_REQUIRE_APPLY")
            result = make_plan(args.target)
            if args.out:
                fd = external_fd(args.out, Path(result["target"]["root"]))
                try:
                    write_all(fd, encoded(result) + b"\n")
                finally:
                    os.close(fd)
        else:
            if not args.plan or not args.receipt or args.out or bool(args.include) == args.all_missing:
                fail("APPLY_REQUIRES_PLAN_RECEIPT_AND_ONE_SELECTION_MODE")
            result = apply_plan(args.target, load_plan(args.plan), args.include, args.all_missing, args.receipt)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 1 if result.get("status") == "FAILED" else 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError) as exc:
        print(json.dumps({"status": "FAILED", "reason": str(exc) if isinstance(exc, SetupError) else type(exc).__name__, "ready": False, "activation": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
