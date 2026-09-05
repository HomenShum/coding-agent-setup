from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_preflight  # noqa: E402


class SevenLayerPreflightScenarios(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "src").mkdir()
        (self.root / "receipts").mkdir()
        schema = {
            "version": 1,
            "artifact": "shape-receipt",
            "receipt_version": 1,
            "required_receipt_fields": [
                "version",
                "artifact",
                "status",
                "schema_digest",
            ],
        }
        schema_bytes = json.dumps(schema, sort_keys=True).encode("utf-8")
        (self.root / "schema.json").write_bytes(schema_bytes)
        self.shape_receipt = {
            "version": 1,
            "artifact": "shape-receipt",
            "status": "complete",
            "schema_digest": hashlib.sha256(schema_bytes).hexdigest(),
        }
        self._write_shape_receipt()
        (self.root / "policy.md").write_text("CANONICAL-RULE\n", encoding="utf-8")
        (self.root / "implementation.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.root / "review-input.md").write_text("Review scope\n", encoding="utf-8")
        (self.root / "src" / "worker.py").write_text(
            "def work():\n    return 'observed'\n",
            encoding="utf-8",
        )
        self.paths = ["implementation.py", "review-input.md"]
        digest, errors, normalized = agent_preflight.compute_bound_digest(
            self.root,
            self.paths,
        )
        self.assertEqual([], errors)
        self.review_receipt = {
            "version": 1,
            "artifact": "self-review",
            "status": "complete",
            "paths": normalized,
            "digest": digest,
            "answers": {
                name: f"Observed answer for {name}."
                for name in agent_preflight.SELF_REVIEW_QUESTIONS
            },
        }
        self._write_review_receipt()
        self.config = {
            "version": 2,
            "configured": True,
            "checks": {
                "shape_version": {
                    "pairs": [{"schema": "schema.json", "receipt": "receipts/shape.json"}]
                },
                "silent_handlers": {"patterns": ["src/*.py"]},
                "convention_sync": {
                    "rules": [{"path": "policy.md", "contains": ["CANONICAL-RULE"]}]
                },
                "runtime": {
                    "minimum_python": "3.10",
                    "imports": [],
                    "probe_timeout_seconds": 5,
                },
                "selftests": {
                    "commands": [
                        {
                            "argv": ["{python}", "-c", "import json"],
                            "timeout_seconds": 5,
                        }
                    ]
                },
                "visual": {
                    "mode": "not_applicable",
                    "reason": "The fixture exercises configuration behavior and renders no interface.",
                },
                "self_review": {
                    "artifact": "self-review",
                    "paths": self.paths,
                    "receipt": "receipts/review.json",
                },
            },
        }

    def _write_shape_receipt(self) -> None:
        (self.root / "receipts" / "shape.json").write_text(
            json.dumps(self.shape_receipt),
            encoding="utf-8",
        )

    def _write_review_receipt(self) -> None:
        (self.root / "receipts" / "review.json").write_text(
            json.dumps(self.review_receipt),
            encoding="utf-8",
        )

    def _commit_shape_change_without_a_version_bump(self) -> str:
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "add", "schema.json", "receipts/shape.json"],
            check=True,
        )
        commit = [
            "git",
            "-C",
            str(self.root),
            "-c",
            "user.name=Scenario User",
            "-c",
            "user.email=scenario@example.invalid",
            "commit",
            "--quiet",
            "-m",
        ]
        subprocess.run([*commit, "shape-v1"], check=True)
        schema = json.loads((self.root / "schema.json").read_text(encoding="utf-8"))
        schema["new_semantic_rule"] = "must-be-reviewed"
        schema_bytes = json.dumps(schema, sort_keys=True).encode("utf-8")
        (self.root / "schema.json").write_bytes(schema_bytes)
        self.shape_receipt["schema_digest"] = hashlib.sha256(schema_bytes).hexdigest()
        self._write_shape_receipt()
        subprocess.run(
            ["git", "-C", str(self.root), "add", "schema.json", "receipts/shape.json"],
            check=True,
        )
        subprocess.run([*commit, "shape-without-bump"], check=True)
        return subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()

    def _status(self, payload: dict[str, object], name: str) -> str:
        checks = payload["checks"]
        assert isinstance(checks, list)
        return next(check["status"] for check in checks if check["name"] == name)

    def test_release_owner_gets_a_clean_deterministic_baseline(self) -> None:
        """A sustained release job needs the same complete proof without accumulating state."""
        payloads = [
            agent_preflight.run_preflight(self.root, copy.deepcopy(self.config))
            for _ in range(12)
        ]
        first = payloads[0]
        self.assertEqual("PASS", first["status"])
        self.assertTrue(all(payload == first for payload in payloads[1:]))
        self.assertEqual(list(agent_preflight.CHECK_NAMES), [item["name"] for item in first["checks"]])

    def _assert_mutation(
        self,
        layer: str,
        expected: str,
        mutate: Callable[[dict[str, object]], None],
    ) -> None:
        config = copy.deepcopy(self.config)
        mutate(config)
        payload = agent_preflight.run_preflight(self.root, config)
        self.assertEqual(expected, self._status(payload, layer))
        self.assertNotEqual("PASS", payload["status"])
        for peer in agent_preflight.CHECK_NAMES:
            if peer != layer:
                self.assertEqual("PASS", self._status(payload, peer), f"coupled failure: {peer}")

    def test_release_owner_is_stopped_by_unversioned_shape_drift(self) -> None:
        """A release owner cannot accept a changed shape whose version was not bumped."""
        def mutate(config: dict[str, object]) -> None:
            del config
            schema = json.loads((self.root / "schema.json").read_text(encoding="utf-8"))
            schema["new_semantic_rule"] = "must-be-reviewed"
            (self.root / "schema.json").write_text(
                json.dumps(schema, sort_keys=True),
                encoding="utf-8",
            )

        self._assert_mutation("shape_version", "FAIL", mutate)

    def test_shape_and_receipt_digest_cannot_change_without_a_schema_version_bump(self) -> None:
        """A coordinated digest refresh cannot disguise changed public schema semantics."""
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "schema.json"], check=True)
        subprocess.run(
            [
                "git", "-C", str(self.root), "-c", "user.name=Scenario User",
                "-c", "user.email=scenario@example.invalid", "commit", "--quiet", "-m", "shape-v1",
            ],
            check=True,
        )
        schema = json.loads((self.root / "schema.json").read_text(encoding="utf-8"))
        schema["new_semantic_rule"] = "must-be-reviewed"
        schema_bytes = json.dumps(schema, sort_keys=True).encode("utf-8")
        (self.root / "schema.json").write_bytes(schema_bytes)
        self.shape_receipt["schema_digest"] = hashlib.sha256(schema_bytes).hexdigest()
        self._write_shape_receipt()

        stale = agent_preflight.run_preflight(self.root, self.config)
        shape_check = next(item for item in stale["checks"] if item["name"] == "shape_version")
        self.assertEqual("FAIL", shape_check["status"])
        self.assertTrue(
            any("without a higher schema version" in error for error in shape_check["errors"])
        )

        schema["version"] = 2
        schema_bytes = json.dumps(schema, sort_keys=True).encode("utf-8")
        (self.root / "schema.json").write_bytes(schema_bytes)
        self.shape_receipt["schema_digest"] = hashlib.sha256(schema_bytes).hexdigest()
        self._write_shape_receipt()
        advanced = agent_preflight.run_preflight(self.root, self.config)
        self.assertEqual("PASS", self._status(advanced, "shape_version"))

    def test_replace_ref_cannot_hide_a_committed_shape_parent(self) -> None:
        """A replacement object cannot turn an unversioned change into a root baseline."""

        head = self._commit_shape_change_without_a_version_bump()
        tree = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", f"{head}^{{tree}}"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
        replacement = subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "-c",
                "user.name=Scenario User",
                "-c",
                "user.email=scenario@example.invalid",
                "commit-tree",
                tree,
            ],
            input="replacement root\n",
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "-C", str(self.root), "replace", head, replacement],
            check=True,
        )

        result = agent_preflight._check_shape_version(
            self.root,
            self.config["checks"]["shape_version"],
            agent_preflight.ReadBudget(),
        )

        self.assertEqual("FAIL", result["status"])
        self.assertTrue(
            any("without a higher schema version" in error for error in result["errors"]),
            result,
        )

    def test_suppressed_legacy_graft_cannot_hide_a_committed_shape_parent(self) -> None:
        """A grafted root cannot erase the baseline used for schema evolution."""

        head = self._commit_shape_change_without_a_version_bump()
        git_directory = Path(
            subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "--absolute-git-dir"],
                capture_output=True,
                check=True,
                text=True,
            ).stdout.strip()
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "config",
                "advice.graftFileDeprecated",
                "false",
            ],
            check=True,
        )
        (git_directory / "info" / "grafts").write_text(f"{head}\n", encoding="ascii")

        result = agent_preflight._check_shape_version(
            self.root,
            self.config["checks"]["shape_version"],
            agent_preflight.ReadBudget(),
        )

        self.assertEqual("FAIL", result["status"])
        self.assertTrue(any("graft path is present" in error for error in result["errors"]), result)

    def test_shallow_clone_cannot_hide_a_committed_no_bump_shape_change(self) -> None:
        """A depth-one CI checkout cannot erase the parent needed to prove schema evolution."""

        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "schema.json", "receipts/shape.json"], check=True)
        commit = [
            "git", "-C", str(self.root), "-c", "user.name=Scenario User",
            "-c", "user.email=scenario@example.invalid", "commit", "--quiet", "-m",
        ]
        subprocess.run([*commit, "shape-v1"], check=True)
        schema = json.loads((self.root / "schema.json").read_text(encoding="utf-8"))
        schema["new_semantic_rule"] = "must-be-reviewed"
        schema_bytes = json.dumps(schema, sort_keys=True).encode("utf-8")
        (self.root / "schema.json").write_bytes(schema_bytes)
        self.shape_receipt["schema_digest"] = hashlib.sha256(schema_bytes).hexdigest()
        self._write_shape_receipt()
        subprocess.run(["git", "-C", str(self.root), "add", "schema.json", "receipts/shape.json"], check=True)
        subprocess.run([*commit, "shape-without-bump"], check=True)

        with tempfile.TemporaryDirectory() as clone_directory:
            shallow = Path(clone_directory) / "shallow"
            subprocess.run(
                ["git", "clone", "--quiet", "--depth", "1", self.root.as_uri(), str(shallow)],
                check=True,
            )
            result = agent_preflight._check_shape_version(
                shallow,
                self.config["checks"]["shape_version"],
                agent_preflight.ReadBudget(),
            )

        self.assertEqual("FAIL", result["status"])
        self.assertTrue(any("parent commit is unavailable" in error for error in result["errors"]))

    def test_root_commit_schema_must_start_at_version_one(self) -> None:
        """A new repository cannot publish a fabricated later schema generation as its baseline."""

        schema = json.loads((self.root / "schema.json").read_text(encoding="utf-8"))
        schema["version"] = 2
        schema_bytes = json.dumps(schema, sort_keys=True).encode("utf-8")
        (self.root / "schema.json").write_bytes(schema_bytes)
        self.shape_receipt["schema_digest"] = hashlib.sha256(schema_bytes).hexdigest()
        self._write_shape_receipt()
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "schema.json", "receipts/shape.json"], check=True)
        subprocess.run(
            [
                "git", "-C", str(self.root), "-c", "user.name=Scenario User",
                "-c", "user.email=scenario@example.invalid", "commit", "--quiet",
                "-m", "invalid-root-shape",
            ],
            check=True,
        )

        result = agent_preflight._check_shape_version(
            self.root,
            self.config["checks"]["shape_version"],
            agent_preflight.ReadBudget(),
        )

        self.assertEqual("FAIL", result["status"])
        self.assertIn("pair 0 first committed schema version must equal 1", result["errors"])

    def test_release_owner_is_stopped_by_malformed_shape_identity(self) -> None:
        """A release owner cannot accept a shape receipt with an empty identity or invalid version."""
        def mutate(config: dict[str, object]) -> None:
            del config
            self.shape_receipt["artifact"] = ""
            self.shape_receipt["version"] = 0
            self._write_shape_receipt()

        self._assert_mutation("shape_version", "FAIL", mutate)

    def test_release_owner_is_stopped_by_a_silent_handler(self) -> None:
        """A release owner cannot accept a worker that hides a realistic failure."""
        def mutate(config: dict[str, object]) -> None:
            del config
            (self.root / "src" / "worker.py").write_text(
                "def work():\n    try:\n        raise RuntimeError\n    except RuntimeError:\n        pass\n",
                encoding="utf-8",
            )

        self._assert_mutation("silent_handlers", "FAIL", mutate)

    def test_release_owner_is_stopped_by_convention_drift(self) -> None:
        """A release owner cannot accept an adapter that lost its canonical rule."""
        def mutate(config: dict[str, object]) -> None:
            del config
            (self.root / "policy.md").write_text("DRIFTED\n", encoding="utf-8")

        self._assert_mutation("convention_sync", "FAIL", mutate)

    def test_release_owner_is_stopped_by_a_missing_runtime_dependency(self) -> None:
        """A release owner cannot accept a setup whose declared runtime cannot start."""
        def mutate(config: dict[str, object]) -> None:
            config["checks"]["runtime"]["imports"] = ["synthetic_module_that_cannot_exist"]

        self._assert_mutation("runtime", "FAIL", mutate)

    def test_release_owner_is_stopped_by_a_failing_selftest(self) -> None:
        """A release owner cannot accept a setup after its executable proof fails."""
        def mutate(config: dict[str, object]) -> None:
            config["checks"]["selftests"]["commands"][0]["argv"] = [
                "{python}",
                "-c",
                "raise SystemExit(7)",
            ]

        self._assert_mutation("selftests", "FAIL", mutate)

    def test_release_owner_sees_no_gate_when_visual_proof_is_missing(self) -> None:
        """A release owner sees NO_GATE when visual work has neither proof nor an exemption."""
        def mutate(config: dict[str, object]) -> None:
            config["checks"]["visual"] = {"mode": "required"}

        self._assert_mutation("visual", "NO_GATE", mutate)

    def test_release_owner_can_run_a_required_visual_gate(self) -> None:
        """A UI release owner can require a real command to leave a non-empty artifact."""
        config = copy.deepcopy(self.config)
        config["checks"]["visual"] = {
            "mode": "required",
            "command": {
                "argv": [
                    "{python}",
                    "-c",
                    "from pathlib import Path; Path('visual-proof.txt').write_text('observed', encoding='utf-8')",
                ],
                "timeout_seconds": 5,
            },
            "artifacts": ["visual-proof.txt"],
        }
        payload = agent_preflight.run_preflight(self.root, config)
        self.assertEqual("PASS", self._status(payload, "visual"))
        self.assertEqual("observed", (self.root / "visual-proof.txt").read_text(encoding="utf-8"))

    def test_release_owner_is_stopped_by_a_stale_visual_artifact(self) -> None:
        """A UI release owner cannot mistake yesterday's artifact for a gate run today."""
        (self.root / "visual-proof.txt").write_text("stale", encoding="utf-8")
        config = copy.deepcopy(self.config)
        config["checks"]["visual"] = {
            "mode": "required",
            "command": {
                "argv": ["{python}", "-c", "pass"],
                "timeout_seconds": 5,
            },
            "artifacts": ["visual-proof.txt"],
        }
        payload = agent_preflight.run_preflight(self.root, config)
        self.assertEqual("FAIL", self._status(payload, "visual"))

    def test_burst_inputs_stop_at_file_and_command_caps(self) -> None:
        """A busy release job rejects a burst before files or commands grow without bound."""
        for index in range(agent_preflight.MAX_FILES + 1):
            (self.root / "src" / f"worker-{index:03d}.py").write_text(
                "value = 'bounded'\n",
                encoding="utf-8",
            )
        config = copy.deepcopy(self.config)
        config["checks"]["selftests"]["commands"] = [
            {"argv": ["{python}", "-c", "pass"], "timeout_seconds": 5}
            for _ in range(agent_preflight.MAX_COMMANDS + 1)
        ]
        payload = agent_preflight.run_preflight(self.root, config)
        self.assertEqual("FAIL", self._status(payload, "silent_handlers"))
        self.assertEqual("FAIL", self._status(payload, "selftests"))

    def test_degraded_commands_stop_at_output_and_time_budgets(self) -> None:
        """A release owner sees bounded failures when a tool floods output or never returns."""
        output_config = copy.deepcopy(self.config)
        output_config["checks"]["selftests"]["commands"][0] = {
            "argv": [
                "{python}",
                "-c",
                f"import sys; sys.stdout.write('x' * {agent_preflight.MAX_COMMAND_OUTPUT_BYTES + 1})",
            ],
            "timeout_seconds": 5,
        }
        output_payload = agent_preflight.run_preflight(self.root, output_config)
        output_check = next(
            item for item in output_payload["checks"] if item["name"] == "selftests"
        )
        self.assertEqual("FAIL", output_check["status"])
        self.assertTrue(any("output exceeded" in error for error in output_check["errors"]))

        timeout_config = copy.deepcopy(self.config)
        timeout_config["checks"]["selftests"]["commands"][0] = {
            "argv": ["{python}", "-c", "import time; time.sleep(2)"],
            "timeout_seconds": 1,
        }
        timeout_payload = agent_preflight.run_preflight(self.root, timeout_config)
        timeout_check = next(
            item for item in timeout_payload["checks"] if item["name"] == "selftests"
        )
        self.assertEqual("FAIL", timeout_check["status"])
        self.assertTrue(any("second budget" in error for error in timeout_check["errors"]))

    def test_timeout_terminates_descendants_that_inherit_output(self) -> None:
        """A timed-out tool cannot leave a child running to mutate the workspace later."""
        child_code = (
            "import time; from pathlib import Path; time.sleep(2); "
            "Path('orphan-marker.txt').write_text('survived', encoding='utf-8')"
        )
        parent_code = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
            "time.sleep(5)"
        )
        config = copy.deepcopy(self.config)
        config["checks"]["selftests"]["commands"][0] = {
            "argv": ["{python}", "-c", parent_code],
            "timeout_seconds": 1,
        }
        started = time.monotonic()
        payload = agent_preflight.run_preflight(self.root, config)
        elapsed = time.monotonic() - started
        self.assertEqual("FAIL", self._status(payload, "selftests"))
        self.assertLess(elapsed, 2.0)
        time.sleep(1.5)
        self.assertFalse((self.root / "orphan-marker.txt").exists())

    def test_runtime_probe_finds_a_package_without_importing_it(self) -> None:
        """A setup check can observe a package without running its initialization code."""
        package = self.root / "sideeffectpkg"
        package.mkdir()
        (package / "__init__.py").write_text(
            "from pathlib import Path\nPath('import-side-effect.txt').write_text('ran')\n",
            encoding="utf-8",
        )
        config = copy.deepcopy(self.config)
        config["checks"]["runtime"]["imports"] = ["sideeffectpkg"]
        payload = agent_preflight.run_preflight(self.root, config)
        self.assertEqual("PASS", self._status(payload, "runtime"))
        self.assertFalse((self.root / "import-side-effect.txt").exists())

    def test_adversarial_configuration_returns_failures_not_tracebacks(self) -> None:
        """A malformed local adapter cannot turn a release check into an uncaught exception."""
        config = copy.deepcopy(self.config)
        config["checks"]["silent_handlers"]["patterns"] = ["src/\x00*.py"]
        config["checks"]["selftests"]["commands"][0]["argv"] = ["\x00"]
        payload = agent_preflight.run_preflight(self.root, config)
        self.assertEqual("FAIL", payload["status"])
        self.assertEqual("FAIL", self._status(payload, "silent_handlers"))
        self.assertEqual("FAIL", self._status(payload, "selftests"))

    def test_path_escape_is_rejected_without_reading_the_target(self) -> None:
        """A copied gate cannot use a relative path to inspect a file outside its repository."""
        outside = self.root.with_name(f"{self.root.name}-outside-policy.md")
        outside.write_text("CANONICAL-RULE\n", encoding="utf-8")
        self.addCleanup(outside.unlink, missing_ok=True)
        config = copy.deepcopy(self.config)
        config["checks"]["convention_sync"]["rules"][0]["path"] = "../outside-policy.md"
        payload = agent_preflight.run_preflight(self.root, config)
        self.assertEqual("FAIL", self._status(payload, "convention_sync"))

    def test_checked_file_swap_to_a_link_is_rejected_before_content_read(self) -> None:
        """A concurrent writer cannot replace a checked gate file with an outside file."""
        outside = self.root.with_name(f"{self.root.name}-outside-sentinel.md")
        outside.write_text("SYNTHETIC_OUTSIDE_SENTINEL\n", encoding="utf-8")
        self.addCleanup(outside.unlink, missing_ok=True)
        target = self.root / "policy.md"
        original_safe_path = agent_preflight._safe_path

        def swap_after_check(
            root: Path, raw: object, *, must_exist: bool = True
        ) -> tuple[Path | None, str | None]:
            result = original_safe_path(root, raw, must_exist=must_exist)
            if raw == "policy.md" and result[1] is None:
                target.unlink()
                try:
                    target.symlink_to(outside)
                except OSError as exc:
                    self.skipTest(f"symlink creation unavailable: {type(exc).__name__}")
            return result

        with mock.patch.object(agent_preflight, "_safe_path", side_effect=swap_after_check):
            data, error = agent_preflight._read_bytes(
                self.root, "policy.md", agent_preflight.ReadBudget()
            )

        self.assertIsNone(data)
        self.assertIsNotNone(error)
        self.assertNotIn("SYNTHETIC_OUTSIDE_SENTINEL", error or "")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is not available")
    def test_preflight_reader_rejects_a_fifo_without_blocking(self) -> None:
        """A local named pipe cannot hold the proof gate open waiting for a writer."""
        fifo = self.root / "blocked-input"
        os.mkfifo(fifo)
        started = time.monotonic()
        data, error = agent_preflight._read_bytes(
            self.root, "blocked-input", agent_preflight.ReadBudget()
        )

        self.assertIsNone(data)
        self.assertIn("cannot read file", error or "")
        self.assertLess(time.monotonic() - started, 1)

    def test_review_digest_refuses_credential_named_files_without_reading_them(self) -> None:
        """A reviewer cannot bind a credential store into a public preflight receipt."""
        (self.root / ".env").write_text("SYNTHETIC_SECRET=value\n", encoding="utf-8")
        budget = agent_preflight.ReadBudget()

        digest, errors, normalized = agent_preflight.compute_bound_digest(
            self.root,
            [".env"],
            budget,
        )

        self.assertIsNone(digest)
        self.assertEqual([], normalized)
        self.assertEqual(0, budget.files)
        self.assertTrue(any("credential or runtime-state" in error for error in errors))

    def test_config_loader_rejects_sensitive_and_outside_paths(self) -> None:
        """A preflight cannot treat a credential file or an outside file as its gate config."""
        (self.root / ".env").write_text("{}\n", encoding="utf-8")
        outside = self.root.with_name(f"{self.root.name}-outside-config.json")
        outside.write_text("{}\n", encoding="utf-8")
        self.addCleanup(outside.unlink, missing_ok=True)

        with self.assertRaisesRegex(ValueError, "credential or runtime-state"):
            agent_preflight.load_config(self.root, ".env")
        with self.assertRaisesRegex(ValueError, "repository-relative"):
            agent_preflight.load_config(self.root, outside)

    def test_missing_configuration_is_reported_as_no_gate(self) -> None:
        """An operator sees NO_GATE, not a fabricated test failure, when no gate can load."""
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "agent_preflight.py"),
                "--root",
                str(self.root),
                "--config",
                "missing.json",
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(2, completed.returncode)
        self.assertEqual("NO_GATE", payload["status"])

    def test_unconfigured_target_is_honestly_no_gate_without_reading_kit_receipts(self) -> None:
        """A new project cannot inherit a green receipt from the setup kit it copied."""
        config = json.loads(
            (ROOT / "templates" / "harness" / "preflight.target.json").read_text(
                encoding="utf-8"
            )
        )

        payload = agent_preflight.run_preflight(self.root, config)

        self.assertEqual("NO_GATE", payload["status"])
        self.assertEqual(0, payload["observed"]["files_read"])
        self.assertEqual(0, payload["observed"]["bytes_read"])
        self.assertTrue(all(item["status"] == "NO_GATE" for item in payload["checks"]))
        self.assertTrue(payload["remedy"])

    def test_target_configuration_requires_an_explicit_boolean_boundary(self) -> None:
        """A malformed copy cannot omit or blur the target-versus-kit proof boundary."""
        missing = copy.deepcopy(self.config)
        del missing["configured"]
        missing_payload = agent_preflight.run_preflight(self.root, missing)
        self.assertEqual("FAIL", missing_payload["status"])
        self.assertIn("configured must be boolean", missing_payload["errors"])

        mixed = copy.deepcopy(self.config)
        mixed["configured"] = False
        mixed["remedy"] = ["configure target-owned proof"]
        mixed_payload = agent_preflight.run_preflight(self.root, mixed)
        self.assertEqual("FAIL", mixed_payload["status"])
        self.assertIn(
            "an unconfigured target must use an empty checks object",
            mixed_payload["errors"],
        )

    def test_release_owner_is_stopped_by_a_stale_self_review(self) -> None:
        """A release owner cannot reuse review answers after their bound input changes."""
        def mutate(config: dict[str, object]) -> None:
            del config
            (self.root / "implementation.py").write_text("VALUE = 2\n", encoding="utf-8")

        self._assert_mutation("self_review", "FAIL", mutate)

    def test_public_receipt_covers_the_preflight_implementation_and_proof(self) -> None:
        """A maintainer cannot accidentally narrow the shipped review to decorative metadata."""
        config = json.loads(
            (ROOT / "templates" / "harness" / "preflight.json").read_text(encoding="utf-8")
        )
        if config.get("configured") is False:
            self.assertEqual({}, config["checks"])
            return
        paths = set(config["checks"]["self_review"]["paths"])
        self.assertTrue(
            {
                "scripts/agent_preflight.py",
                "scripts/bounded_process.py",
                "scripts/git_safety.py",
                "scripts/path_safety.py",
                "scripts/prove_preflight_mutations.py",
                "templates/harness/preflight.json",
                "tests/test_preflight_mutations.py",
            }.issubset(paths)
        )


if __name__ == "__main__":
    unittest.main()
