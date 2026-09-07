"""A maintainer adds reviewed setup files without replacing an existing project's work."""
from concurrent.futures import ThreadPoolExecutor
import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = Path(tempfile.gettempdir()).resolve(strict=True)
sys.path.insert(0, str(ROOT / "scripts"))
import setup_project as setup


class ExistingProjectAdoption(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=TEMP_ROOT, prefix="setup-adoption-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.target = self.base / "existing project"
        self.target.mkdir()
        self.git("init", "--quiet", "--template=")

    def git(self, *args):
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.hooksPath=" + str(self.base / "no-hooks"),
             "-c", "user.name=Setup fixture", "-c", "user.email=fixture@example.invalid", *args],
            cwd=self.target, env=setup.clean_git_environment(), capture_output=True, timeout=15,
        )
        self.assertEqual(0, result.returncode, result.stderr.decode(errors="replace"))
        return result.stdout

    def cli(self, *args, kit=ROOT):
        return subprocess.run(
            [sys.executable, "-B", str(kit / "scripts/setup_project.py"), "--target", str(self.target), *args],
            capture_output=True, text=True, timeout=45, env=setup.clean_git_environment(),
        )

    def plan(self, kit=ROOT):
        result = self.cli(kit=kit)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def apply(self, plan, names, receipt="receipt.jsonl"):
        return setup.apply_plan(self.target, plan, names, False, self.base / receipt)

    def snapshot(self):
        return {p.relative_to(self.target).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.target.rglob("*") if p.is_file()}

    def assert_failed(self, result):
        self.assertEqual("FAILED", result["status"], result)
        self.assertFalse(result["ready"])

    def test_dirty_owner_reviews_then_adds_only_missing_file_and_repeats_without_private_reads(self):
        (self.target / "AGENTS.md").write_text("Keep our existing project policy.\n")
        (self.target / "tracked.txt").write_text("original\n")
        self.git("add", "AGENTS.md", "tracked.txt")
        self.git("commit", "--quiet", "-m", "fixture baseline")
        (self.target / "tracked.txt").write_text("unfinished owner edit\n")
        secret = self.target / ".env"
        secret.write_text("PRIVATE_ADOPTION_SENTINEL=not-for-output\n")
        (self.target / "AGENT_INVARIANTS.md").write_bytes((ROOT / "templates/project/AGENT_INVARIANTS.md").read_bytes())
        before = self.snapshot()
        read = setup.read_regular_file_bounded
        with mock.patch.object(setup, "read_regular_file_bounded", side_effect=lambda p, *a, **kw: self.assertNotEqual(secret, p) or read(p, *a, **kw)):
            plan = setup.make_plan(self.target)
        self.assertEqual(before, self.snapshot())
        states = {r["destination"]: r for r in plan["rows"]}
        self.assertEqual("CONFLICT", states["AGENTS.md"]["state"])
        self.assertEqual("IDENTICAL", states["AGENT_INVARIANTS.md"]["state"])
        self.assertEqual("MISSING", states["scripts/path_safety.py"]["state"])
        self.assertEqual(64, len(states["scripts/path_safety.py"]["sha256"]))
        self.assertIsNone(states["scripts/path_safety.py"]["destination_sha256"])
        self.assertNotIn("PRIVATE_ADOPTION_SENTINEL", json.dumps(plan))
        file = self.base / "plan.json"
        file.write_text(json.dumps(plan))
        result = self.cli("apply", "--plan", str(file), "--include", "scripts/path_safety.py", "--receipt", str(self.base / "native-receipt.jsonl"))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("APPLIED_WITH_UNRESOLVED_ITEMS", payload["status"])
        self.assertFalse(payload["ready"])
        for p, value in before.items():
            self.assertEqual(value, self.snapshot()[p], p)
        self.assertEqual((ROOT / "scripts/path_safety.py").read_bytes(), (self.target / "scripts/path_safety.py").read_bytes())
        installed = self.snapshot()
        for n in range(4):
            repeated = self.apply(plan, ["scripts/path_safety.py"], f"repeat-{n}.jsonl")
            self.assertNotEqual("FAILED", repeated["status"], repeated)
            self.assertFalse(any(e["state"].startswith("CREATED") for e in repeated["events"]))
            self.assertEqual(installed, self.snapshot())

    def test_fresh_unborn_git_target_uses_native_cli_and_keeps_inactive_configuration(self):
        plan = self.plan()
        self.assertTrue(plan["target"]["unborn"])
        self.assertIsNone(plan["target"]["head"])
        p = self.base / "fresh-plan.json"
        p.write_text(json.dumps(plan))
        result = self.cli("apply", "--plan", str(p), "--all-missing", "--receipt", str(self.base / "fresh.jsonl"))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("UNCONFIGURED", json.loads(result.stdout)["status"])
        self.assertFalse((self.target / ".codex/hooks.json").exists())
        self.assertFalse((self.target / ".cursor/hooks.json").exists())
        self.assertNotIn("hooks", json.loads((self.target / ".claude/settings.json").read_text()))
        self.assertEqual(2, (self.target / ".codex/config.toml").read_text().count("enabled = false"))
        self.assertEqual((ROOT / "templates/harness/preflight.target.json").read_bytes(), (self.target / "templates/harness/preflight.json").read_bytes())
        receipt = [json.loads(line) for line in (self.base / "fresh.jsonl").read_text().splitlines()]
        self.assertEqual("STARTED", receipt[0]["state"])
        self.assertEqual("COMPLETED", receipt[-1]["state"])
        self.assertTrue(any(e["state"] == "CREATED_DIRECTORY" for e in receipt))
        for e in receipt:
            if e["state"] == "CREATED_FILE":
                self.assertEqual(e["sha256"], hashlib.sha256((self.target / e["path"]).read_bytes()).hexdigest())

    def test_existing_external_receipt_or_internal_output_is_never_overwritten(self):
        plan = self.plan()
        existing = self.base / "existing.jsonl"
        existing.write_text("private previous receipt")
        before = self.snapshot()
        self.assert_failed(self.apply(plan, ["AGENTS.md"], "existing.jsonl"))
        self.assertEqual("private previous receipt", existing.read_text())
        self.assert_failed(setup.apply_plan(self.target, plan, ["AGENTS.md"], False, self.target / "report.jsonl"))
        self.assertEqual(before, self.snapshot())

    def test_leaf_created_by_real_competing_writer_is_preserved_between_intent_and_open(self):
        plan = self.plan()
        original = setup.Receipt.record
        def competing(receipt, **event):
            original(receipt, **event)
            if event.get("state") == "PENDING_FILE":
                code = "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('other writer owns this file')"
                subprocess.run([sys.executable, "-c", code, str(self.target / event["path"])], check=True, timeout=10)
        with mock.patch.object(setup.Receipt, "record", competing):
            result = self.apply(plan, ["AGENTS.md"])
        self.assert_failed(result)
        self.assertEqual("other writer owns this file", (self.target / "AGENTS.md").read_text())
        self.assertFalse(any(e["state"] == "CREATED_FILE" for e in result["events"]))

    def test_two_actual_cli_writers_and_later_manual_edit_never_replace_each_other(self):
        plan = self.plan()
        file = self.base / "plan.json"
        file.write_text(json.dumps(plan))
        with ThreadPoolExecutor(max_workers=2) as pool:
            runs = list(pool.map(lambda n: self.cli("apply", "--plan", str(file), "--include", "AGENTS.md", "--receipt", str(self.base / f"race-{n}.jsonl")), range(2)))
        self.assertTrue(any(x.returncode == 0 for x in runs))
        self.assertEqual((ROOT / "templates/project/AGENTS.md").read_bytes(), (self.target / "AGENTS.md").read_bytes())
        created = [e for x in runs for e in json.loads(x.stdout).get("events", []) if e["state"] == "CREATED_FILE"]
        self.assertEqual(1, len(created))
        (self.target / "AGENTS.md").write_text("owner adapts instructions")
        self.assert_failed(self.apply(plan, ["AGENTS.md"], "later.jsonl"))
        self.assertEqual("owner adapts instructions", (self.target / "AGENTS.md").read_text())

    def test_equal_length_actual_source_change_invalidates_reviewed_missing_destination(self):
        kit = self.base / "kit"
        shutil.copytree(ROOT, kit, ignore=shutil.ignore_patterns(".git", "__pycache__", ".agent-local"))
        plan = self.plan(kit=kit)
        source = kit / "templates/project/AGENTS.md"
        original = source.read_bytes()
        source.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        self.assertEqual(len(original), source.stat().st_size)
        p = self.base / "reviewed.json"
        p.write_text(json.dumps(plan))
        before = self.snapshot()
        result = self.cli("apply", "--plan", str(p), "--include", "AGENTS.md", "--receipt", str(self.base / "drift.jsonl"), kit=kit)
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, self.snapshot())

    def test_stale_head_and_forged_duplicate_or_unlisted_paths_stop_before_target_writes(self):
        plan = self.plan()
        for mode in ("traversal", "git-config", "duplicate", "oversized"):
            tampered = copy.deepcopy(plan)
            if mode == "duplicate":
                tampered["rows"][1] = tampered["rows"][0]
            elif mode == "oversized":
                tampered["rows"] *= 3
            else:
                tampered["rows"][0]["destination"] = "../outside" if mode == "traversal" else ".git/config"
            tampered["plan_sha256"] = setup.digest(setup.encoded({k: v for k, v in tampered.items() if k != "plan_sha256"}))
            before = self.snapshot()
            self.assert_failed(self.apply(tampered, ["AGENTS.md"], mode + ".jsonl"))
            self.assertEqual(before, self.snapshot())
        (self.target / "new.txt").write_text("new work")
        self.git("add", "new.txt")
        self.git("commit", "--quiet", "-m", "new state")
        self.assert_failed(self.apply(plan, ["AGENTS.md"], "stale.jsonl"))
        self.assertFalse((self.target / "AGENTS.md").exists())

    def test_whole_canonical_skill_extra_missing_and_changed_bytes_block_mirror(self):
        skill = "refresh-handoff"
        source = ROOT / "templates/project/.agents/skills" / skill
        canonical = self.target / ".agents/skills" / skill
        shutil.copytree(source, canonical)
        plan = self.plan()
        mirror = [r["destination"] for r in plan["rows"] if r["destination"].startswith(f".claude/skills/{skill}/")]
        extra = canonical / "private-extra-reference.txt"
        extra.write_text("private skill decision")
        self.assert_failed(self.apply(plan, mirror, "extra.jsonl"))
        self.assertFalse((self.target / ".claude/skills" / skill).exists())
        extra.unlink()
        content = (canonical / "SKILL.md").read_bytes()
        (canonical / "SKILL.md").unlink()
        self.assert_failed(self.apply(plan, mirror, "missing.jsonl"))
        (canonical / "SKILL.md").write_bytes(b"X" + content[1:])
        self.assert_failed(self.apply(plan, mirror, "changed.jsonl"))
        (canonical / "SKILL.md").write_bytes(content)
        result = self.apply(plan, mirror, "matching.jsonl")
        self.assertNotEqual("FAILED", result["status"], result)
        self.assertEqual(setup.tree_digest(canonical), setup.tree_digest(self.target / ".claude/skills" / skill))

    def test_mid_write_failure_keeps_partial_file_and_durable_prior_progress(self):
        plan = self.plan()
        original = setup.write_all
        def disk_full(fd, data):
            if data == (ROOT / "templates/project/ARTIFACTS.md").read_bytes():
                os.write(fd, data[:7])
                raise OSError(errno.ENOSPC, "injected disk full")
            original(fd, data)
        with mock.patch.object(setup, "write_all", disk_full):
            result = self.apply(plan, ["AGENTS.md", "ARTIFACTS.md", "DECISIONS.md"])
        self.assert_failed(result)
        self.assertEqual((ROOT / "templates/project/AGENTS.md").read_bytes(), (self.target / "AGENTS.md").read_bytes())
        self.assertEqual(7, (self.target / "ARTIFACTS.md").stat().st_size)
        self.assertFalse((self.target / "DECISIONS.md").exists())
        records = [json.loads(line) for line in (self.base / "receipt.jsonl").read_text().splitlines()]
        self.assertTrue(any(e["state"] == "PARTIAL_FILE" and e["bytes"] == 7 for e in records))

    def test_receipt_fsync_failure_stops_before_next_file_and_reports_durable_prefix(self):
        plan = self.plan()
        original = setup.write_all
        def receipt_failure(fd, data):
            if b'"state":"CREATED_FILE"' in bytes(data):
                raise OSError(errno.ENOSPC, "receipt device full")
            original(fd, data)
        with mock.patch.object(setup, "write_all", receipt_failure):
            result = self.apply(plan, ["AGENTS.md", "ARTIFACTS.md"])
        self.assert_failed(result)
        self.assertTrue(result["receipt_failure"])
        self.assertLess(result["durable_events"], len(result["events"]))
        self.assertTrue((self.target / "AGENTS.md").is_file())
        self.assertFalse((self.target / "ARTIFACTS.md").exists())
        records = [json.loads(line) for line in (self.base / "receipt.jsonl").read_text().splitlines()]
        self.assertEqual("PENDING_FILE", records[-1]["state"])

    def test_plan_is_bounded_and_rejects_duplicate_json_without_target_bytecode(self):
        malformed = self.base / "duplicate.json"
        malformed.write_text('{"version":1,"version":2}')
        before = self.snapshot()
        result = self.cli("apply", "--plan", str(malformed), "--include", "AGENTS.md", "--receipt", str(self.base / "bad.jsonl"))
        self.assertNotEqual(0, result.returncode)
        (self.target / "AGENTS.md").write_bytes(b"a" * (setup.MAX_FILE_BYTES + 1))
        plan = self.plan()
        self.assertEqual("BLOCKED", next(x for x in plan["rows"] if x["destination"] == "AGENTS.md")["state"])
        self.assertFalse(list(self.target.rglob("__pycache__")))
        self.assertTrue(all(self.snapshot()[name] == row for name, row in before.items()))

    def test_nonregular_parent_is_blocked_before_any_attempted_creation(self):
        (self.target / "scripts").write_text("owner's file, not directory")
        plan = self.plan()
        self.assertEqual("BLOCKED", next(x for x in plan["rows"] if x["destination"] == "scripts/path_safety.py")["state"])
        self.assert_failed(self.apply(plan, ["scripts/path_safety.py"]))

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation unavailable on this platform")
    def test_fifo_at_destination_never_blocks_planning(self):
        os.mkfifo(self.target / "AGENTS.md")
        plan = self.plan()
        self.assertEqual("BLOCKED", next(x for x in plan["rows"] if x["destination"] == "AGENTS.md")["state"])

    def test_parent_substitution_at_the_old_open_window_cannot_redirect_creation(self):
        outside = self.base / "outside"
        outside.mkdir()
        parent = self.target / "scripts"
        parent.mkdir()
        plan = self.plan()
        parked = self.target / "parked-scripts"
        def link():
            if os.name == "nt":
                z = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(parent), str(outside)], capture_output=True, timeout=10)
                if z.returncode:
                    self.skipTest("Windows junction creation unavailable")
            else:
                parent.symlink_to(outside, target_is_directory=True)
        original = setup._relative_open
        swapped = False
        attempted = False
        def replaced(handle, name, *, directory, create):
            nonlocal swapped, attempted
            if name == "path_safety.py" and create:
                attempted = True
                try:
                    parent.rename(parked)
                except PermissionError:
                    self.assertEqual("nt", os.name)  # A held Windows read handle prevents rename.
                else:
                    link()
                    swapped = True
            return original(handle, name, directory=directory, create=create)
        try:
            with mock.patch.object(setup, "_relative_open", replaced):
                result = self.apply(plan, ["scripts/path_safety.py"], "namespace.jsonl")
            self.assertTrue(attempted)
            self.assertEqual([], list(outside.iterdir()))
            if swapped:
                self.assert_failed(result)  # POSIX wrote to the held, still in-target directory.
                self.assertEqual((ROOT / "scripts/path_safety.py").read_bytes(), (parked / "path_safety.py").read_bytes())
            else:
                self.assertNotEqual("FAILED", result["status"], result)
                self.assertEqual((ROOT / "scripts/path_safety.py").read_bytes(), (parent / "path_safety.py").read_bytes())
        finally:
            if setup.is_link_like(parent):
                parent.rmdir() if os.name == "nt" else parent.unlink()

    @unittest.skipUnless(os.name == "nt", "Windows in-place reparse mutation")
    def test_in_place_reparse_cannot_redirect_directory_file_or_external_output_creation(self):
        """Attribute writers bypass sharing restrictions, so every creator must be relative."""
        c, w, kernel = setup.c, setup.w, setup._kernel
        kernel.DeviceIoControl.argtypes = [w.HANDLE, w.DWORD, c.c_void_p, w.DWORD,
                                          c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.c_void_p]
        kernel.DeviceIoControl.restype = w.BOOL
        kernel.GetCurrentProcess.restype = w.HANDLE
        kernel.GetProcessHandleCount.argtypes = [w.HANDLE, c.POINTER(w.DWORD)]
        def count():
            value = w.DWORD()
            self.assertTrue(kernel.GetProcessHandleCount(kernel.GetCurrentProcess(), c.byref(value)))
            return value.value
        def control(handle, code, data):
            buffer, n = c.create_string_buffer(data), w.DWORD()
            self.assertTrue(kernel.DeviceIoControl(handle, code, buffer, len(data), None, 0, c.byref(n), None), c.get_last_error())
        for mode in ("directory", "file", "plan", "receipt"):
            with self.subTest(mode=mode):
                outside = self.base / ("outside-" + mode)
                outside.mkdir()
                parent = self.target / (".agents" if mode == "directory" else "scripts") if mode in ("directory", "file") else self.base / ("outputs-" + mode)
                parent.mkdir(exist_ok=True)
                plan = self.plan()
                leaf = {"directory": "skills", "file": "path_safety.py", "plan": "plan.json", "receipt": "receipt.jsonl"}[mode]
                original = setup._relative_open
                writer, attempted = None, False
                def replace(handle, name, *, directory, create):
                    nonlocal writer, attempted
                    if name == leaf and create:
                        attempted = True
                        writer = kernel.CreateFileW(str(parent), 0x100, 7, None, 3, 0x02000000 | 0x00200000, None)
                        self.assertNotEqual(c.c_void_p(-1).value, writer)
                        substitute = ("\\??\\" + str(outside)).encode("utf-16-le")
                        display = str(outside).encode("utf-16-le")
                        data = struct.pack("<HHHH", 0, len(substitute), len(substitute) + 2, len(display)) + substitute + b"\0\0" + display + b"\0\0"
                        control(writer, 0x900A4, struct.pack("<IHH", 0xA0000003, len(data), 0) + data)
                    return original(handle, name, directory=directory, create=create)
                before_handles = count()
                try:
                    with mock.patch.object(setup, "_relative_open", replace):
                        if mode == "plan":
                            with self.assertRaises(OSError):
                                setup.external_fd(parent / leaf, self.target)
                        else:
                            receipt = parent / leaf if mode == "receipt" else self.base / (mode + ".jsonl")
                            selected = [".agents/skills/refresh-handoff/SKILL.md"] if mode == "directory" else ["scripts/path_safety.py"]
                            result = setup.apply_plan(self.target, plan, selected, False, receipt)
                            self.assert_failed(result)
                    self.assertTrue(attempted)
                    self.assertEqual([], list(outside.iterdir()))
                finally:
                    if writer is not None:
                        control(writer, 0x900AC, struct.pack("<IHH", 0xA0000003, 0, 0))
                        self.assertTrue(kernel.CloseHandle(writer))
                self.assertEqual(before_handles, count(), "All success/error-path directory and file handles must close")

    def test_second_source_read_drift_is_held_before_receipt_or_target_creation(self):
        plan = self.plan()
        original, calls = setup.materialization, 0
        def changed():
            nonlocal calls
            calls += 1
            rows, content = original()
            if calls == 2:
                content["AGENTS.md"] = b"X" + content["AGENTS.md"][1:]
                next(x for x in rows if x["destination"] == "AGENTS.md")["sha256"] = setup.digest(content["AGENTS.md"])
            return rows, content
        before = self.snapshot()
        with mock.patch.object(setup, "materialization", changed):
            result = self.apply(plan, ["AGENTS.md"])
        self.assertEqual("SOURCE_CHANGED_BEFORE_WRITE", result["reason"])
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.base / "receipt.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
