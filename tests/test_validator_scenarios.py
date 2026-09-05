from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_repo  # noqa: E402
import bounded_process  # noqa: E402
import path_safety  # noqa: E402


class ValidatorAdversarialScenarios(unittest.TestCase):
    def copy_repository(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        target = Path(temporary.name) / "repo"
        shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        return temporary, target

    @staticmethod
    def install_synthetic_marker_policy(target: Path, marker: str) -> None:
        payload = {
            "algorithm": "sha256-lower-nfkc",
            "markers": [
                {
                    "length": len(marker),
                    "digest": hashlib.sha256(marker.encode("utf-8")).hexdigest(),
                }
            ],
        }
        (target / "sources/private-marker-hashes.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def test_publisher_sees_redacted_content_marker_failure(self) -> None:
        """A publisher is stopped when a digest-listed term is embedded in a larger token."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        marker = "violet7"
        self.install_synthetic_marker_policy(target, marker)
        fullwidth = "".join(
            chr(ord(character) + 0xFEE0)
            for character in ("prefix" + marker.upper() + "suffix")
        )
        (target / "synthetic-note.txt").write_text(
            fullwidth + "\n", encoding="utf-8"
        )

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("private-source marker present in content" in error for error in errors))
        self.assertNotIn(marker, "\n".join(errors).lower())

    def test_publisher_sees_redacted_path_marker_failure(self) -> None:
        """A publisher is stopped by a digest-listed path while the matching path stays hidden."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        marker = "violet7"
        self.install_synthetic_marker_policy(target, marker)
        (target / f"prefix-{marker}-suffix.json").write_text("{", encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("publication path: id=" in error for error in errors))
        self.assertNotIn(marker, "\n".join(errors).lower())

    def test_publisher_is_stopped_by_split_and_zero_width_markers(self) -> None:
        """A publisher cannot disguise a blocked marker with separators or format characters."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        marker = "violet7"
        self.install_synthetic_marker_policy(target, marker)
        disguised = " \u200b-".join(marker)
        (target / "synthetic-note.txt").write_text(disguised, encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("private-source marker present in content" in error for error in errors))
        self.assertNotIn(marker, "\n".join(errors).lower())

    def test_portable_invariant_numbering_cannot_silently_drift(self) -> None:
        """A copied contract keeps the promised twenty-two-item closed sequence."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        path = target / "templates/project/AGENT_INVARIANTS.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "22. **Make communication policy explicit.**",
                "23. **Make communication policy explicit.**",
            ),
            encoding="utf-8",
        )

        errors = validate_repo.validate_repo(target)

        self.assertIn(
            "portable invariants must be numbered exactly 1 through 22",
            errors,
        )

    def test_copy_by_default_adapters_must_remain_inert(self) -> None:
        """A newcomer cannot accidentally activate MCP servers or hooks by copying the kit."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        active_server = {
            "mcpServers": {
                "unexpected": {"command": "python", "args": ["-m", "unexpected"]}
            }
        }
        (target / "templates/project/.mcp.json").write_text(
            json.dumps(active_server), encoding="utf-8"
        )
        (target / "templates/cursor/mcp.json").write_text(
            json.dumps(active_server), encoding="utf-8"
        )
        claude_path = target / "templates/claude/settings.json"
        claude = json.loads(claude_path.read_text(encoding="utf-8"))
        claude["hooks"] = {"Stop": [{"hooks": [{"type": "command", "command": "python"}]}]}
        claude_path.write_text(json.dumps(claude), encoding="utf-8")
        codex_path = target / "templates/codex/project.config.toml"
        codex_path.write_text(
            codex_path.read_text(encoding="utf-8").replace("enabled = false", "enabled = true"),
            encoding="utf-8",
        )
        personal_codex_path = target / "templates/codex/config.toml"
        personal_codex_path.write_text(
            personal_codex_path.read_text(encoding="utf-8").replace(
                "enabled = false", "enabled = true"
            ),
            encoding="utf-8",
        )

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("templates/project/.mcp.json" in error for error in errors))
        self.assertTrue(any("templates/cursor/mcp.json" in error for error in errors))
        self.assertTrue(any("templates/claude/settings.json" in error for error in errors))
        self.assertTrue(any("templates/codex/project.config.toml" in error for error in errors))
        self.assertTrue(any("templates/codex/config.toml" in error for error in errors))

    def test_publication_ignores_cover_private_and_generated_claude_state(self) -> None:
        """A fresh target cannot expose local instructions or generated worktrees as changes."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        for relative in (".gitignore", "templates/project/.gitignore"):
            path = target / relative
            content = path.read_text(encoding="utf-8")
            content = content.replace(".claude/worktrees/\n", "")
            content = content.replace("CLAUDE.local.md\n", "")
            path.write_text(content, encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        for relative in (".gitignore", "templates/project/.gitignore"):
            self.assertTrue(
                any(".claude/worktrees/" in error and relative in error for error in errors)
            )
            self.assertTrue(
                any("CLAUDE.local.md" in error and relative in error for error in errors)
            )

    def test_publication_ignores_a_worktree_git_pointer_file_without_reading_it(self) -> None:
        """A reviewer can validate from a Git worktree without scanning its private gitdir path."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        pointer = target / ".git"
        credential_like = "sk-" + (chr(65) * 24)
        pointer.write_text(
            f"gitdir: C:/path/{credential_like}/.git/worktrees/example\n",
            encoding="utf-8",
        )
        ignored_directory_sentinels = (target / ".codex", target / "node_modules")
        for sentinel in ignored_directory_sentinels:
            sentinel.write_text("SYNTHETIC_LOCAL_SENTINEL\n", encoding="utf-8")
        observed_reads: list[Path] = []
        original_read = validate_repo.read_text

        def recording_read(path: Path) -> str:
            observed_reads.append(path)
            return original_read(path)

        with mock.patch.object(validate_repo, "read_text", side_effect=recording_read):
            errors = validate_repo.validate_repo(target)

        self.assertEqual([], errors)
        self.assertNotIn(pointer, observed_reads)
        self.assertFalse(
            any(sentinel in observed_reads for sentinel in ignored_directory_sentinels)
        )

    def test_publication_inventory_never_opens_ignored_runtime_or_host_state(self) -> None:
        """A publisher scans only files that could enter the repository, with or without Git."""
        for use_git in (False, True):
            with self.subTest(use_git=use_git), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / "repo"
                shutil.copytree(
                    ROOT,
                    target,
                    ignore=shutil.ignore_patterns(".git", "__pycache__"),
                )
                ignored = (
                    target / ".claude" / "worktrees" / "demo" / ".git",
                    target / ".claude" / "skills" / "generated" / "SKILL.md",
                    target / ".agent-local" / "state.json",
                    target / ".codex" / "config.toml",
                    target / ".env.local",
                )
                for path in ignored:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("SYNTHETIC_LOCAL_SENTINEL\n", encoding="utf-8")
                public_environment = target / ".env.example"
                public_environment.write_text("PUBLIC_SETTING=example\n", encoding="utf-8")
                if use_git:
                    subprocess.run(["git", "init", "--quiet", str(target)], check=True)
                    subprocess.run(["git", "-C", str(target), "add", "."], check=True)

                observed_reads: list[Path] = []
                original_read = validate_repo.read_text

                def recording_read(path: Path) -> str:
                    observed_reads.append(path)
                    return original_read(path)

                with mock.patch.object(validate_repo, "read_text", side_effect=recording_read):
                    errors = validate_repo.validate_repo(target)

                self.assertEqual([], errors)
                self.assertIn(public_environment, observed_reads)
                self.assertFalse(any(path in observed_reads for path in ignored))

    def test_publication_inventory_excludes_a_tracked_file_deleted_from_the_worktree(self) -> None:
        """A pending tracked deletion is not reopened as though its old content were publishable."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tracked = root / "retired-note.md"
            tracked.write_text("retired public note\n", encoding="utf-8")
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            tracked.unlink()
            errors = validate_repo.BoundedErrors()

            paths = validate_repo._git_public_paths(root, errors)

            self.assertEqual([], errors)
            self.assertEqual([], paths)

    def test_personal_path_scan_covers_both_windows_separators_and_keeps_placeholders(self) -> None:
        """A publisher cannot leak a concrete drive path by changing slash direction."""
        drive = chr(68) + ":"
        concrete = (
            drive + "\\" + "private\\work\\project",
            drive + "/" + "private/work/project",
            (chr(67) + ":/") + "company/project",
            ("\\" * 2) + "private-host\\department\\project",
            "/" + "Users/example/project",
        )
        placeholders = (
            r"C:\path\to\project",
            "C:/path/to/project",
            r"C:\Users\USERNAME\project",
            "C:/Users/USERNAME/project",
            r"\\server\share\project",
            "/Users/USERNAME/project",
        )

        for value in concrete:
            with self.subTest(value=value):
                self.assertTrue(
                    any(pattern.search(value) for pattern in validate_repo.PERSONAL_PATH_PATTERNS)
                )
        for value in placeholders:
            with self.subTest(value=value):
                self.assertFalse(
                    any(pattern.search(value) for pattern in validate_repo.PERSONAL_PATH_PATTERNS)
                )

    def test_release_job_stops_consuming_an_over_cap_generator(self) -> None:
        """A generated URL stream cannot allocate the full adversarial input before failing."""

        consumed = 0
        base = "https://" + "github.com/example/"

        def generated_urls():
            nonlocal consumed
            for index in range(validate_repo.MAX_EXTERNAL_URLS + 100):
                consumed += 1
                yield f"{base}source-{index}"

        with self.assertRaisesRegex(ValueError, "cap exceeded"):
            validate_repo.check_external_urls(generated_urls(), lambda _: (True, "unused"))

        self.assertEqual(validate_repo.MAX_EXTERNAL_URLS + 1, consumed)

    def test_release_job_stops_an_unbounded_duplicate_stream(self) -> None:
        """Repeated duplicate URLs cannot keep a scheduled checker consuming forever."""

        consumed = 0

        def duplicate_urls():
            nonlocal consumed
            while True:
                consumed += 1
                yield "https://" + "github.com/example/repeated"

        with self.assertRaisesRegex(ValueError, "input cap exceeded"):
            validate_repo.check_external_urls(duplicate_urls(), lambda _: (True, "unused"))

        self.assertEqual(validate_repo.MAX_EXTERNAL_URL_ITEMS + 1, consumed)

    def test_bounded_reader_rejects_a_file_that_grows_after_discovery(self) -> None:
        """A concurrent writer cannot make the publication scan allocate an unbounded file."""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "growing.txt"
            path.write_bytes(b"x" * validate_repo.MAX_PUBLIC_FILE_BYTES)
            original_read = path_safety.os.read
            appended = False

            def read_then_grow(descriptor: int, count: int) -> bytes:
                nonlocal appended
                chunk = original_read(descriptor, count)
                if chunk and not appended:
                    appended = True
                    with path.open("ab") as growing_file:
                        growing_file.write(b"x")
                return chunk

            with mock.patch.object(path_safety.os, "read", side_effect=read_then_grow):
                with self.assertRaisesRegex(ValueError, "grew beyond"):
                    validate_repo.read_text(path)
            self.assertTrue(appended)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is not available")
    def test_publication_reader_rejects_a_fifo_without_blocking(self) -> None:
        """A local named pipe cannot stall a publication scan while it waits for a writer."""

        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory) / "blocked-input"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, "regular file"):
                validate_repo.read_text(fifo)

    def test_external_fetch_has_a_killable_process_deadline(self) -> None:
        """A stuck resolver cannot outlive the link check's declared wall-clock budget."""

        timeout = validate_repo.subprocess.TimeoutExpired(
            cmd=["python", "validator"], timeout=validate_repo.TIMEOUT_SECONDS + 3
        )
        with mock.patch.object(validate_repo, "run_bounded", side_effect=timeout):
            ok, detail = validate_repo.fetch_external_bounded(
                "https://" + "github.com/example/source"
            )

        self.assertFalse(ok)
        self.assertEqual("fetch exceeded its bounded process deadline", detail)

    def test_cross_origin_redirect_strips_sensitive_request_headers(self) -> None:
        """A vendor redirect cannot carry a source-host token to another allowed host."""

        handler = validate_repo.SafeRedirectHandler()
        source = validate_repo.Request(
            "https://" + "github.com/example/source",
            headers={
                "Authorization": "Bearer secret",
                "Cookie": "session=secret",
                "User-Agent": "setup-validator",
            },
        )
        with mock.patch.object(validate_repo, "validate_public_destination"):
            cross_origin = handler.redirect_request(
                source,
                None,
                302,
                "Found",
                {},
                "https://cursor.com/docs/skills",
            )
            same_origin = handler.redirect_request(
                source,
                None,
                302,
                "Found",
                {},
                "https://" + "github.com/example/renamed",
            )

        assert cross_origin is not None
        assert same_origin is not None
        self.assertIsNone(cross_origin.get_header("Authorization"))
        self.assertIsNone(cross_origin.get_header("Cookie"))
        self.assertEqual("setup-validator", cross_origin.get_header("User-agent"))
        self.assertEqual("Bearer secret", same_origin.get_header("Authorization"))
        self.assertEqual("session=secret", same_origin.get_header("Cookie"))

    def test_external_batch_cancels_queued_work_at_its_aggregate_deadline(self) -> None:
        """A slow source fleet cannot serialize two hundred timeouts past the CI budget."""

        calls = 0
        lock = threading.Lock()

        def blocking_fetch(url: str) -> tuple[bool, str]:
            del url
            nonlocal calls
            with lock:
                calls += 1
            time.sleep(0.15)
            return True, "late"

        base = "https://" + "github.com/example/source-"
        urls = [f"{base}{index:03d}" for index in range(200)]
        started = time.monotonic()
        results = validate_repo.check_external_urls(
            urls,
            blocking_fetch,
            aggregate_seconds=0.02,
        )
        elapsed = time.monotonic() - started

        self.assertEqual(200, len(results))
        self.assertLessEqual(calls, validate_repo.MAX_WORKERS)
        self.assertTrue(all(not ok for _, ok, _ in results))
        self.assertTrue(all("aggregate deadline" in detail for _, _, detail in results))
        self.assertLess(elapsed, 1)

    def test_external_child_inherits_the_remaining_aggregate_budget(self) -> None:
        """An in-flight resolver is killed at the shared batch deadline, not its later local limit."""

        observed: list[float] = []

        def timeout_child(*args: object, **kwargs: object) -> object:
            del args
            observed.append(float(kwargs["timeout_seconds"]))
            raise subprocess.TimeoutExpired(cmd=["python"], timeout=observed[-1])

        with mock.patch.object(validate_repo, "run_bounded", side_effect=timeout_child):
            ok, detail = validate_repo.fetch_external_bounded(
                "https://" + "github.com/example/source",
                deadline=time.monotonic() + 0.25,
            )

        self.assertFalse(ok)
        self.assertEqual(1, len(observed))
        self.assertGreater(observed[0], 0)
        self.assertLessEqual(observed[0], 0.25)
        self.assertEqual("fetch exceeded its bounded process deadline", detail)

    def test_bounded_process_kills_a_streaming_child_at_the_output_cap(self) -> None:
        """A noisy local dependency is killed while streaming, before it can fill temp storage."""
        started = time.monotonic()
        with self.assertRaises(bounded_process.OutputLimitExceeded):
            bounded_process.run_bounded(
                [
                    sys.executable,
                    "-c",
                    "import sys\nwhile True:\n sys.stdout.buffer.write(b'x' * 4096)\n sys.stdout.buffer.flush()",
                ],
                cwd=ROOT,
                timeout_seconds=10,
                output_limit=8_192,
            )
        self.assertLess(time.monotonic() - started, 3)

    def test_bounded_process_returns_a_small_successful_receipt(self) -> None:
        """A normal local proof command completes through the same bounded runner."""

        completed = bounded_process.run_bounded(
            [sys.executable, "-c", "print('bounded-ok')"],
            cwd=ROOT,
            timeout_seconds=5,
            output_limit=1_024,
        )

        self.assertEqual(0, completed.returncode)
        self.assertEqual(b"bounded-ok\r\n" if os.name == "nt" else b"bounded-ok\n", completed.output)

    @unittest.skipUnless(os.name == "nt", "Windows job-object success path")
    def test_windows_bounded_process_job_accepts_64_bit_handles(self) -> None:
        """A Windows maintainer can execute proof commands inside the kill-on-close job."""

        completed = bounded_process.run_bounded(
            [sys.executable, "-c", "raise SystemExit(0)"],
            cwd=ROOT,
            timeout_seconds=5,
            output_limit=1_024,
        )

        self.assertEqual(0, completed.returncode)

    def test_git_inventory_propagates_the_streaming_output_limit(self) -> None:
        """The publication gate cannot downgrade a Git inventory overflow into a partial list."""
        with mock.patch.object(
            validate_repo,
            "run_bounded",
            side_effect=bounded_process.OutputLimitExceeded("synthetic overflow"),
        ):
            with self.assertRaises(bounded_process.OutputLimitExceeded):
                validate_repo._run_git_inventory(ROOT, ["status"], 8)

    def test_directory_only_publication_tree_stops_at_the_entry_cap(self) -> None:
        """An empty-directory flood cannot keep a publication scan walking forever."""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = [f"empty-{index:04d}" for index in range(validate_repo.MAX_PUBLIC_FILES + 1)]
            errors = validate_repo.BoundedErrors()
            with mock.patch.object(validate_repo.os, "walk", return_value=iter([(root, names, [])])):
                files = validate_repo.collect_public_files(root, errors)

        self.assertEqual([], files)
        self.assertTrue(any("public file cap exceeded" in error for error in errors))

    @unittest.skipUnless(os.name == "nt", "Windows junction semantics")
    def test_publication_walk_rejects_a_windows_junction_without_reading_outside(self) -> None:
        """A publisher cannot redirect the bounded repository walk into another directory."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        with tempfile.TemporaryDirectory() as outside:
            outside_root = Path(outside)
            outside_file = outside_root / "outside.txt"
            outside_file.write_text("external sentinel\n", encoding="utf-8")
            junction = target / "linked-outside"
            result = validate_repo.subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside_root)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                self.skipTest(f"junction creation unavailable: exit {result.returncode}")
            observed_reads: list[Path] = []
            original_read = validate_repo.read_text

            def recording_read(path: Path) -> str:
                observed_reads.append(path)
                return original_read(path)

            with mock.patch.object(validate_repo, "read_text", side_effect=recording_read):
                errors = validate_repo.validate_repo(target)

            self.assertTrue(any("linked directory" in error for error in errors))
            self.assertFalse(
                any(path.resolve() == outside_file.resolve() for path in observed_reads)
            )

    def test_malformed_catalogs_become_diagnostics_instead_of_tracebacks(self) -> None:
        """A maintainer receives actionable failures even when every machine catalog is malformed."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        (target / "sources/private-marker-hashes.json").write_text("[]", encoding="utf-8")
        (target / "sources/host-capabilities.json").write_text(
            json.dumps({"hosts": "not-an-array"}), encoding="utf-8"
        )
        (target / "sources/skills.json").write_text(
            json.dumps({"skills": {"not": "an-array"}}), encoding="utf-8"
        )
        (target / "sources/external-projects.json").write_text("[]", encoding="utf-8")
        (target / "sources/official-docs.json").write_text(
            json.dumps({"sources": [7]}), encoding="utf-8"
        )

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("private marker policy" in error for error in errors))
        self.assertTrue(any("host capability catalog" in error for error in errors))
        self.assertTrue(any("skill catalog" in error for error in errors))
        self.assertTrue(any("external project catalog" in error for error in errors))
        self.assertTrue(any("official source 0 must be an object" in error for error in errors))

    def test_three_host_capability_drift_is_rejected(self) -> None:
        """A team cannot silently lose or rename one supported coding host."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        path = target / "sources/host-capabilities.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["hosts"][0]["name"] = "fourth-host"
        path.write_text(json.dumps(payload), encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("host capability drift" in error for error in errors))

    def test_root_claude_compatibility_file_cannot_leak_host_only_rules(self) -> None:
        """A Cursor session cannot inherit Claude-only settings from the shared root file."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        (target / "CLAUDE.md").write_text(
            "@AGENTS.md\n\nUse a Claude-only setting.\n", encoding="utf-8"
        )

        errors = validate_repo.validate_repo(target)

        self.assertTrue(
            any("root-level Claude compatibility file is forbidden" in error for error in errors),
            errors,
        )

    def test_cursor_personal_rule_must_remain_mdc_and_match_the_canonical_body(self) -> None:
        """A Cursor user cannot receive a stale personal rule or invalid discovery metadata."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        rule = target / "templates" / "cursor" / "working-agreements.mdc"
        rule.write_text(
            rule.read_text(encoding="utf-8").replace(
                "alwaysApply: true",
                "alwaysApply: false",
            ),
            encoding="utf-8",
        )

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("Cursor personal rule must be an .mdc file" in error for error in errors), errors)

    def test_every_host_capability_mapping_is_exact_and_closed(self) -> None:
        """A maintainer cannot publish a plausible host name with a wrong native adapter path."""
        source_path = ROOT / "sources" / "host-capabilities.json"
        original = json.loads(source_path.read_text(encoding="utf-8"))
        capability_fields = (
            "instructions",
            "skills",
            "agents",
            "mcp",
            "hooks",
            "permissions",
            "parallel_workers",
        )
        for host_index, host in enumerate(original["hosts"]):
            for field in capability_fields:
                with self.subTest(host=host["name"], field=field):
                    payload = copy.deepcopy(original)
                    payload["hosts"][host_index][field] = (
                        False if field == "parallel_workers" else f"wrong-{field}"
                    )
                    errors = validate_repo.BoundedErrors()
                    validate_repo.validate_host_capabilities(
                        ROOT,
                        {source_path: json.dumps(payload)},
                        errors,
                    )
                    self.assertTrue(
                        any(f"{host['name']}.{field}" in error for error in errors),
                        errors,
                    )

        for mutation, expected in (
            ("missing", "missing fields"),
            ("extra", "extra fields"),
        ):
            with self.subTest(mutation=mutation):
                payload = copy.deepcopy(original)
                if mutation == "missing":
                    del payload["hosts"][0]["skills"]
                else:
                    payload["hosts"][0]["unexpected"] = "value"
                errors = validate_repo.BoundedErrors()
                validate_repo.validate_host_capabilities(
                    ROOT,
                    {source_path: json.dumps(payload)},
                    errors,
                )
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_external_ledger_requires_platform_tools_and_exact_human_semantics(self) -> None:
        """A publisher cannot omit a direct prerequisite or show a stale access date."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        catalog_path = target / "sources" / "external-projects.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog["methodology"]["current_kit_direct"] = [
            value
            for value in catalog["methodology"]["current_kit_direct"]
            if value != "https://github.com/git/git"
        ]
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        ledger_path = target / "docs" / "external-projects.md"
        cpython = next(
            project
            for project in catalog["projects"]
            if project["repository"] == "https://github.com/python/cpython"
        )
        current_row = validate_repo.render_external_project_row(cpython)
        stale = copy.deepcopy(cpython)
        stale["accessed"] = "2000-01-01"
        ledger_path.write_text(
            ledger_path.read_text(encoding="utf-8").replace(
                current_row,
                validate_repo.render_external_project_row(stale),
            ),
            encoding="utf-8",
        )

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("required current-kit repository missing" in error for error in errors))
        self.assertTrue(any("exact row drifts" in error for error in errors))

    def test_external_catalog_rejects_a_deeper_github_page_as_a_repository(self) -> None:
        """A source row must link to the repository root, not an issue or query masquerading as one."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        path = target / "sources" / "external-projects.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["projects"][0]["repository"] += "/issues/1?view=all"
        path.write_text(json.dumps(payload), encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("external project 0 has invalid repository" in error for error in errors), errors)

    def test_historical_source_and_action_baselines_cannot_silently_shrink(self) -> None:
        """A public provenance pass cannot omit a known prior source or reusable action."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        catalog_path = target / "sources" / "external-projects.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog["methodology"]["required_historical_sources"].pop()
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        actions_path = target / "sources" / "historical-action-uses.json"
        actions = json.loads(actions_path.read_text(encoding="utf-8"))
        actions["actions"].pop()
        actions_path.write_text(json.dumps(actions), encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("required historical source baseline drift" in error for error in errors), errors)
        self.assertTrue(any("historical action source baseline drift" in error for error in errors), errors)

    def test_human_source_rows_must_preserve_machine_ledger_order(self) -> None:
        """A generated provenance table cannot reorder rows while retaining valid-looking cells."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        catalog = json.loads(
            (target / "sources" / "external-projects.json").read_text(encoding="utf-8")
        )
        first_row = validate_repo.render_external_project_row(catalog["projects"][0])
        second_row = validate_repo.render_external_project_row(catalog["projects"][1])
        ledger_path = target / "docs" / "external-projects.md"
        content = ledger_path.read_text(encoding="utf-8")
        first_index = content.index(first_row)
        second_index = content.index(second_row)
        self.assertLess(first_index, second_index)
        placeholder = "| [Synthetic row swap placeholder](https://example.invalid) |"
        content = content.replace(first_row, placeholder, 1)
        content = content.replace(second_row, first_row, 1)
        content = content.replace(placeholder, second_row, 1)
        ledger_path.write_text(content, encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        self.assertIn("external project row order drifts from machine ledger", errors)

    def test_source_ledgers_fail_closed_after_semantic_tampering(self) -> None:
        """A maintainer cannot publish incomplete provenance or cosmetically valid source rows."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        catalog_path = target / "sources/external-projects.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        projects = catalog["projects"]
        del projects[0]["category"]
        del projects[0]["evidence"]
        del projects[0]["confidence"]
        projects[1]["category"] = "python"
        projects[2]["evidence"] = "tampered evidence"
        projects[3]["confidence"] = "absolute"
        projects[4]["category"] = "unknown"
        notes_indexes = [index for index, project in enumerate(projects) if "notes" in project]
        revision_indexes = [
            index for index, project in enumerate(projects) if "revision" in project
        ]
        self.assertGreaterEqual(len(notes_indexes), 2)
        self.assertGreaterEqual(len(revision_indexes), 2)
        projects[notes_indexes[0]]["notes"] = 7
        projects[notes_indexes[1]]["notes"] = "tampered note"
        projects[revision_indexes[0]]["revision"] = []
        projects[revision_indexes[1]]["revision"] = "tampered revision"
        unchecked = next(project for project in projects[1:] if "notes" not in project)
        unchecked["check"] = False
        catalog["methodology"]["historical_evidence"] = []
        catalog["methodology"]["excluded"] = [7]
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

        official_path = target / "sources/official-docs.json"
        official = json.loads(official_path.read_text(encoding="utf-8"))
        official["accessed"] = "tomorrow"
        official["sources"][0]["vendor"] = ""
        official["sources"][1]["topic"] = ""
        official["sources"].append(copy.deepcopy(official["sources"][2]))
        official_path.write_text(json.dumps(official), encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        missing = next(error for error in errors if "external project 0 missing" in error)
        self.assertIn("category", missing)
        self.assertIn("evidence", missing)
        self.assertIn("confidence", missing)
        for expected in (
            "category drifts from human ledger",
            "exact row drifts from human ledger",
            "invalid confidence",
            "invalid category",
            "invalid notes",
            "invalid revision",
            "skips checks without a note",
            "methodology historical_evidence must be a non-empty string array",
            "methodology excluded must be a non-empty string array",
            "official document catalog has an invalid or future access date",
            "field vendor must be a non-empty string",
            "field topic must be a non-empty string",
            "duplicate official document",
        ):
            self.assertTrue(any(expected in error for error in errors), (expected, errors))

    def test_source_catalogs_reject_extra_fields_impossible_dates_and_vendor_spoofing(self) -> None:
        """A source receipt cannot look valid while carrying ambiguous or mislabelled metadata."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        external_path = target / "sources" / "external-projects.json"
        external = json.loads(external_path.read_text(encoding="utf-8"))
        external["unexpected"] = True
        external["accessed"] = "9999-99-99"
        external["projects"][0]["unexpected"] = "unreviewed"
        external_path.write_text(json.dumps(external), encoding="utf-8")
        official_path = target / "sources" / "official-docs.json"
        official = json.loads(official_path.read_text(encoding="utf-8"))
        official["unexpected"] = True
        official["accessed"] = "9999-12-31"
        official["sources"][0]["vendor"] = "Cursor"
        official["sources"][1]["unexpected"] = "unreviewed"
        official_path.write_text(json.dumps(official), encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        for expected in (
            "external project catalog has an unexpected shape",
            "external project catalog has an invalid or future access date",
            "external project 0 has unknown fields",
            "official document catalog has an unexpected shape",
            "official document catalog has an invalid or future access date",
            "official source 0 vendor does not match its URL host",
            "official source 1 has unknown fields",
        ):
            self.assertTrue(any(expected in error for error in errors), (expected, errors))

    def test_declared_python_floor_matches_the_stdlib_used_by_the_kit(self) -> None:
        """A maintainer cannot advertise Python 3.10 for scripts that import tomllib."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        path = target / "templates/harness/preflight.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["checks"]["runtime"]["minimum_python"] = "3.10"
        path.write_text(json.dumps(payload), encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("minimum_python must equal 3.11" in error for error in errors))

    def test_skill_manifest_and_directory_drift_is_rejected(self) -> None:
        """A maintainer cannot claim the full portable skill set after dropping a manifest row."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        path = target / "sources/skills.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["skills"].pop()
        path.write_text(json.dumps(payload), encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("must contain exactly 16 skills" in error for error in errors))
        self.assertTrue(any("skill manifest drift" in error for error in errors))

    def test_skill_frontmatter_size_and_metadata_contracts_are_rejected(self) -> None:
        """A skill author gets one diagnostic per broken discovery and maintenance contract."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        skill_name = json.loads(
            (target / "sources/skills.json").read_text(encoding="utf-8")
        )["skills"][0]
        skill_root = target / "templates/project/.agents/skills" / skill_name
        body = "---\nname: wrong-name\ndescription:\n---\n" + ("line\n" * 100)
        (skill_root / "SKILL.md").write_text(body, encoding="utf-8")
        (skill_root / "agents/openai.yaml").write_text(
            json.dumps({"interface": {"default_prompt": "No explicit invocation."}}),
            encoding="utf-8",
        )

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("under 100 lines" in error for error in errors))
        self.assertTrue(any("name does not match folder" in error for error in errors))
        self.assertTrue(any("needs a description" in error for error in errors))
        self.assertTrue(any("default_prompt must invoke" in error for error in errors))

    def test_standalone_skill_scaffold_cannot_drift_from_the_receipt_contract(self) -> None:
        """A skill author cannot copy a scaffold that the shared validator would reject."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        contract_path = target / "templates/skill/references/contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["receipt"] = ["status"]
        contract_path.write_text(json.dumps(contract), encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("skill scaffold contract" in error for error in errors))
        self.assertTrue(any("canonical five fields" in error for error in errors))

    def test_standalone_skill_scaffold_keeps_portable_discovery_bounds(self) -> None:
        """A skill author cannot copy a scaffold lacking bounded discovery metadata."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        skill_path = target / "templates/skill/SKILL.md"
        skill_path.write_text(
            "---\nname: example-proof\ndescription:\n---\n" + ("line\n" * 100),
            encoding="utf-8",
        )

        errors = validate_repo.validate_repo(target)

        self.assertTrue(
            any("scaffold SKILL.md must be under 100 lines" in error for error in errors)
        )
        self.assertTrue(
            any("scaffold frontmatter needs a description" in error for error in errors)
        )

    def test_json_examples_and_skill_metadata_are_parsed(self) -> None:
        """A setup consumer cannot receive malformed copy-paste JSON or skill metadata."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        (target / "templates/cursor/hooks.json.example").write_text("{", encoding="utf-8")
        skill_name = json.loads(
            (target / "sources/skills.json").read_text(encoding="utf-8")
        )["skills"][0]
        (target / "templates/project/.agents/skills" / skill_name / "agents/openai.yaml").write_text(
            "not-json", encoding="utf-8"
        )

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("hooks.json.example" in error for error in errors))
        self.assertTrue(any("invalid JSON-subset YAML" in error for error in errors))

    def test_cursor_cli_examples_cannot_enable_blanket_execution(self) -> None:
        """A newcomer cannot copy a global or project CLI policy that starts unrestricted."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        global_path = target / "templates/cursor/cli-config.json.example"
        global_config = json.loads(global_path.read_text(encoding="utf-8"))
        global_config["permissions"]["allow"] = ["Shell(*)"]
        global_config["approvalMode"] = "unrestricted"
        global_path.write_text(json.dumps(global_config), encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("allowlist must start empty" in error for error in errors), errors)
        self.assertTrue(
            any("global example must use allowlist approval mode" in error for error in errors),
            errors,
        )

    def test_cursor_desktop_policy_examples_are_closed_and_inert(self) -> None:
        """A desktop user starts with no auto-run tools, no extra paths, and no network."""

        relative_paths = (
            "templates/cursor/permissions.json.example",
            "templates/cursor/sandbox.json.example",
        )
        texts = {
            ROOT / relative: (ROOT / relative).read_text(encoding="utf-8")
            for relative in relative_paths
        }
        errors = validate_repo.BoundedErrors()

        validate_repo.validate_inert_templates(ROOT, texts, errors)

        self.assertEqual([], list(errors))

    def test_cursor_desktop_permissions_reject_auto_run_and_missing_secret_blocks(self) -> None:
        """A desktop user cannot copy a policy that silently auto-runs tools or exposes secrets."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        path = target / "templates/cursor/permissions.json.example"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["mcpAllowlist"] = ["*:*"]
        payload["terminalAllowlist"] = ["powershell"]
        payload["autoRun"]["allow_instructions"] = ["Run any command without review."]
        payload["autoRun"]["block_instructions"].pop()
        payload["ignoredByCursor"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("permissions template has an unexpected shape" in error for error in errors), errors)
        self.assertTrue(any("permission allowlists must start empty" in error for error in errors), errors)
        self.assertTrue(any("autoRun allow instructions must start empty" in error for error in errors), errors)
        self.assertTrue(any("missing baseline secret blocks" in error for error in errors), errors)

    def test_cursor_desktop_sandbox_rejects_escape_paths_and_open_network(self) -> None:
        """A desktop user cannot copy a sandbox that writes outside the repo or opens the network."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        path = target / "templates/cursor/sandbox.json.example"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["type"] = "insecure_none"
        payload["additionalReadwritePaths"] = ["[OUTSIDE_WORKSPACE]"]
        payload["disableTmpWrite"] = "false"
        payload["enableSharedBuildCache"] = True
        payload["networkPolicy"] = {
            "default": "allow",
            "allow": ["*"],
            "deny": [],
        }
        payload["ignoredByCursor"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("sandbox template has an unexpected shape" in error for error in errors), errors)
        self.assertTrue(any("sandbox must stay workspace-scoped" in error for error in errors), errors)
        self.assertTrue(any("must not grant extra filesystem paths" in error for error in errors), errors)
        self.assertTrue(any("disableTmpWrite must be boolean false" in error for error in errors), errors)
        self.assertTrue(any("shared build cache must start disabled" in error for error in errors), errors)
        self.assertTrue(any("network policy must start deny-by-default" in error for error in errors), errors)

    def test_cursor_desktop_policy_examples_are_required_and_parseable(self) -> None:
        """A setup publisher cannot omit one desktop policy while corrupting the other."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        (target / "templates/cursor/permissions.json.example").unlink()
        (target / "templates/cursor/sandbox.json.example").write_text("{", encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        self.assertIn(
            "missing required file: templates/cursor/permissions.json.example",
            errors,
        )
        self.assertTrue(
            any("invalid JSON templates\\cursor\\sandbox.json.example" in error
                or "invalid JSON templates/cursor/sandbox.json.example" in error
                for error in errors),
            errors,
        )

    def test_host_permission_examples_protect_nested_project_secrets(self) -> None:
        """A monorepo app cannot fall outside the baseline environment-file denials."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        cursor_path = target / "templates/cursor/cli.json.example"
        cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
        cursor["permissions"]["deny"].remove("Write(**/.env*)")
        cursor_path.write_text(json.dumps(cursor), encoding="utf-8")
        claude_path = target / "templates/claude/settings.json"
        claude = json.loads(claude_path.read_text(encoding="utf-8"))
        claude["permissions"]["deny"].remove("Read(/**/.env*)")
        claude_path.write_text(json.dumps(claude), encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        self.assertTrue(any("Cursor CLI example is missing baseline denials" in error for error in errors), errors)
        self.assertTrue(any("Claude settings example is missing recursive" in error for error in errors), errors)

    def test_cursor_official_docs_are_catalogued_and_network_allowlisted(self) -> None:
        """A release checker can recognize and safely inspect the third host's official docs."""

        official = json.loads((ROOT / "sources/official-docs.json").read_text(encoding="utf-8"))
        catalogued = {entry["url"] for entry in official["sources"]}
        urls = {
            "https://cursor.com/docs/skills",
            "https://cursor.com/docs/reference/permissions",
            "https://cursor.com/docs/reference/sandbox",
            "https://forum.cursor.com/t/agent-tools-fail-on-wsl-workspace-opened-via-wsl-localhost-path-resolves-to-c-home-glob-times-out-shell-intermittent-cursor-3-9-16/165471/5",
        }
        self.assertTrue({"cursor.com", "forum.cursor.com"} <= validate_repo.ALLOWED_EXTERNAL_HOSTS)
        self.assertTrue(urls <= catalogued)
        for url in urls:
            with self.subTest(url=url):
                self.assertIsNotNone(validate_repo.VENDOR_DOC_URL.fullmatch(url))

    def test_newcomer_gets_reviewable_installers_with_a_closed_redirect_allowlist(self) -> None:
        """A newcomer can inspect every vendor bootstrap while the live checker follows only named hosts."""

        official = json.loads((ROOT / "sources/official-docs.json").read_text(encoding="utf-8"))
        catalogued = {entry["url"] for entry in official["sources"]}
        entrypoints = {
            "https://chatgpt.com/codex/install.sh",
            "https://chatgpt.com/codex/install.ps1",
            "https://claude.ai/install.sh",
            "https://claude.ai/install.ps1",
            "https://claude.ai/install.cmd",
            "https://cursor.com/install",
            "https://cursor.com/install?win32=true",
        }
        redirect_targets = {
            "https://releases.openai.com/codex/install.sh",
            "https://releases.openai.com/codex/install.ps1",
            "https://downloads.claude.ai/claude-code-releases/bootstrap.sh",
            "https://downloads.claude.ai/claude-code-releases/bootstrap.ps1",
            "https://downloads.claude.ai/claude-code-releases/bootstrap.cmd",
        }
        redirect_hosts = {
            "chatgpt.com",
            "releases.openai.com",
            "claude.ai",
            "downloads.claude.ai",
            "cursor.com",
        }

        self.assertTrue(entrypoints <= catalogued)
        self.assertTrue(redirect_targets <= catalogued)
        self.assertTrue(redirect_hosts <= validate_repo.ALLOWED_EXTERNAL_HOSTS)
        for url in entrypoints | redirect_targets:
            with self.subTest(url=url):
                self.assertIsNotNone(validate_repo.VENDOR_DOC_URL.fullmatch(url))
        setup_guidance = "\n".join(
            (ROOT / relative).read_text(encoding="utf-8")
            for relative in ("README.md", "docs/setup.md")
        )
        self.assertNotRegex(
            setup_guidance,
            r"https://[^\s]+[^\n]*\|\s*(?:iex|bash|sh)\b",
        )
        self.assertIn("RUN REVIEWED INSTALLERS", setup_guidance)

    def test_ci_cannot_shallow_or_timeout_the_publication_gates(self) -> None:
        """A publisher cannot weaken history depth or give the source batch too little time."""

        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        workflow_path = target / ".github" / "workflows" / "validate.yml"
        workflow = workflow_path.read_text(encoding="utf-8")
        workflow = workflow.replace("fetch-depth: 0", "fetch-depth: 1", 1)
        workflow = workflow.replace("timeout-minutes: 8", "timeout-minutes: 2", 1)
        workflow_path.write_text(workflow, encoding="utf-8")

        errors = validate_repo.validate_repo(target)

        self.assertIn("reachable-history job must use a full checkout", errors)
        self.assertIn(
            "external-links job timeout is below the bounded batch budget", errors
        )

    def test_optional_vendor_only_tool_docs_are_catalogued_without_a_fake_repo(self) -> None:
        """A maintainer can cite a vendor command without inventing an OSS implementation."""
        url = "https://graphite.com/docs/command-reference"
        official = json.loads((ROOT / "sources/official-docs.json").read_text(encoding="utf-8"))
        external = json.loads((ROOT / "sources/external-projects.json").read_text(encoding="utf-8"))

        self.assertIn("graphite.com", validate_repo.ALLOWED_EXTERNAL_HOSTS)
        self.assertIsNotNone(validate_repo.VENDOR_DOC_URL.fullmatch(url))
        self.assertIn(url, {entry["url"] for entry in official["sources"]})
        self.assertFalse(
            any("graphite" in entry["name"].lower() for entry in external["projects"])
        )


if __name__ == "__main__":
    unittest.main()
