from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import tomllib
import unittest
from unittest import mock
import sys


ROOT = Path(__file__).resolve().parents[1]
# Physical fixture paths keep OS aliases outside link-rejection scenarios.
TEMP_ROOT = Path(tempfile.gettempdir()).resolve(strict=True)
sys.path.insert(0, str(ROOT / "scripts"))

import agent_preflight  # noqa: E402
import check_branch_stack  # noqa: E402
import check_claim_language  # noqa: E402
import self_review_hook  # noqa: E402
import setup_doctor  # noqa: E402
import sync_skills  # noqa: E402
import validate_agent_state  # noqa: E402
import validate_skill_receipt  # noqa: E402


class _BinaryInput:
    def __init__(self, value: bytes) -> None:
        self.buffer = io.BytesIO(value)


class AgentStateScenarios(unittest.TestCase):
    def template(self, name: str) -> dict[str, object]:
        return json.loads((ROOT / "templates" / "harness" / name).read_text(encoding="utf-8"))

    def validate(
        self, state: dict[str, object], project_root: Path | None = ROOT
    ) -> list[str]:
        return validate_agent_state.validate_state(state, project_root)

    def test_maintainer_can_replay_valid_loop_and_graph_routes(self) -> None:
        """A maintainer can distinguish a small loop from a justified worker graph."""
        self.assertEqual([], self.validate(self.template("agent-state-loop.json")))
        self.assertEqual([], self.validate(self.template("agent-state-graph.json")))

    def test_planner_cannot_bypass_the_graph_judge_or_use_one_reason(self) -> None:
        """A planner cannot deliver graph work directly after gathering its own evidence."""
        state = self.template("agent-state-graph.json")
        state["why_graph"] = ["fan-out-fan-in"]
        state["path"] = ["human", "planner", "human"]
        errors = self.validate(state)
        self.assertTrue(any("at least two" in error for error in errors))
        self.assertTrue(any("planner -> human" in error for error in errors))

    def test_delivered_routes_reject_skipped_reordered_and_wrong_mode_nodes(self) -> None:
        """A maintainer cannot label a role-skipping or reordered route as delivered proof."""
        cases = (
            (
                "loop-skips-planner",
                "agent-state-loop.json",
                ["human", "gate", "human"],
                "LOOP forbids transition human -> gate",
            ),
            (
                "graph-skips-worker",
                "agent-state-graph.json",
                ["human", "planner", "gate", "judge", "human"],
                "GRAPH delivery requires human -> planner -> worker",
            ),
            (
                "graph-reorders-worker-and-gate",
                "agent-state-graph.json",
                ["human", "planner", "worker", "gate", "judge", "human"],
                "GRAPH forbids transition worker -> gate",
            ),
            (
                "loop-uses-graph-judge",
                "agent-state-loop.json",
                ["human", "planner", "judge", "human"],
                "LOOP forbids transition planner -> judge",
            ),
        )
        for label, template, path, expected in cases:
            with self.subTest(label=label):
                state = self.template(template)
                state["path"] = path
                state["current"] = path[-1]
                errors = self.validate(state)
                self.assertTrue(any(expected in error for error in errors), errors)

    def test_graph_delivery_needs_worker_evidence_and_partial_state_stays_open(self) -> None:
        """A graph cannot claim delivery without evidence or hide a closed route as partial."""
        graph = self.template("agent-state-graph.json")
        graph["receipts"] = []
        errors = self.validate(graph)
        self.assertIn("GRAPH delivery requires at least one evidenced worker receipt", errors)

        graph = self.template("agent-state-graph.json")
        receipts = graph["receipts"]
        assert isinstance(receipts, list)
        receipts[0]["certainty"] = "UNVERIFIED"
        errors = self.validate(graph)
        self.assertIn("GRAPH delivery requires at least one evidenced worker receipt", errors)

        partial = self.template("agent-state-loop.json")
        partial["delivered"] = False
        partial["disposition"] = "REVISE"
        errors = self.validate(partial)
        self.assertIn("a completed route ending at human must be marked delivered", errors)

        partial["path"] = ["human", "planner", "gate"]
        partial["current"] = "gate"
        self.assertEqual([], self.validate(partial))

        partial["path"] = ["human", "planner"]
        partial["current"] = "planner"
        partial["disposition"] = "PASS"
        errors = self.validate(partial)
        self.assertIn("PASS disposition must be delivered", errors)

        graph = self.template("agent-state-graph.json")
        graph["path"] = ["human", "planner", "gate"]
        graph["current"] = "gate"
        graph["delivered"] = False
        graph["disposition"] = "REVISE"
        errors = self.validate(graph)
        self.assertIn("GRAPH gate requires an earlier worker stage", errors)

    def test_routes_start_at_human_and_do_not_reenter_human_midflight(self) -> None:
        """A state receipt cannot splice two unrelated human-owned runs into one route."""
        state = self.template("agent-state-loop.json")
        state["path"] = ["planner", "gate", "human"]
        errors = self.validate(state)
        self.assertIn("path must start at human", errors)

        state["path"] = ["human", "planner", "gate", "human", "planner"]
        state["current"] = "planner"
        state["delivered"] = False
        state["disposition"] = "REVISE"
        errors = self.validate(state)
        self.assertIn("human may appear only at route boundaries", errors)

    def test_adversarial_state_values_return_errors_instead_of_crashing(self) -> None:
        """An untrusted state receipt cannot turn validation into a traceback."""
        state = self.template("agent-state-graph.json")
        state["path"] = ["human", {"unexpected": True}]
        receipts = state["receipts"]
        assert isinstance(receipts, list)
        receipts[0]["certainty"] = ["MEASURED"]
        errors = self.validate(state)
        self.assertTrue(any("unknown node" in error for error in errors))
        self.assertTrue(any("non-empty strings" in error for error in errors))

    def test_state_caps_and_receipts_are_closed_typed_objects(self) -> None:
        """A consumer cannot silently disagree about unreviewed extension fields."""
        state = self.template("agent-state-graph.json")
        state["unexpected"] = "ignored by a permissive consumer"
        state["caps"]["unexpected"] = 1
        state["receipts"][0]["unexpected"] = "unreviewed receipt payload"

        errors = self.validate(state)

        self.assertTrue(any("state has unknown fields" in error for error in errors), errors)
        self.assertTrue(any("caps has unknown fields" in error for error in errors), errors)
        self.assertTrue(any("receipt 0 has unknown fields" in error for error in errors), errors)

    def test_host_switch_events_require_one_exact_safe_handoff_shape(self) -> None:
        """A cross-host audit cannot pass with an empty, ambiguous, or private event."""
        template_events = self.template("agent-state-graph.json")["events"]
        assert isinstance(template_events, list)
        handoff_sha256 = template_events[0]["handoff_sha256"]
        cases = (
            ({}, "event 0 missing"),
            (
                {
                    "type": "host-switch",
                    "from": "codex",
                    "to": "claude",
                    "handoff": "handoffs/0001/HANDOFF.md",
                    "handoff_sha256": handoff_sha256,
                    "unreviewed": True,
                },
                "unknown fields",
            ),
            (
                {
                    "type": "host-switch",
                    "from": "codex",
                    "to": "codex",
                    "handoff": "handoffs/0001/HANDOFF.md",
                    "handoff_sha256": handoff_sha256,
                },
                "different hosts",
            ),
            (
                {
                    "type": "host-switch",
                    "from": "codex",
                    "to": "claude",
                    "handoff": "../HANDOFF.md",
                    "handoff_sha256": handoff_sha256,
                },
                "immutable handoffs/NNNN/HANDOFF.md snapshot",
            ),
            (
                {
                    "type": "host-switch",
                    "from": "codex",
                    "to": "claude",
                    "handoff": "HANDOFF.md",
                    "handoff_sha256": handoff_sha256,
                },
                "immutable handoffs/NNNN/HANDOFF.md snapshot",
            ),
            (
                {
                    "type": "host-switch",
                    "from": "codex",
                    "to": "claude",
                    "handoff": ".git/HANDOFF.md",
                    "handoff_sha256": handoff_sha256,
                },
                "immutable handoffs/NNNN/HANDOFF.md snapshot",
            ),
            (
                {
                    "type": "note",
                    "from": "codex",
                    "to": "claude",
                    "handoff": "handoffs/0001/HANDOFF.md",
                    "handoff_sha256": handoff_sha256,
                },
                "type must equal host-switch",
            ),
            (
                {
                    "type": "host-switch",
                    "from": "codex",
                    "to": "claude",
                    "handoff": "handoffs/0001/HANDOFF.md",
                    "handoff_sha256": "not-a-digest",
                },
                "64-hex SHA-256",
            ),
        )
        for event, expected in cases:
            with self.subTest(expected=expected):
                state = self.template("agent-state-graph.json")
                state["events"] = [event]
                errors = self.validate(state)
                self.assertTrue(any(expected in error for error in errors), errors)

        valid = self.template("agent-state-graph.json")
        events = valid["events"]
        assert isinstance(events, list)
        events[0]["from"] = "codex"
        events[0]["to"] = "claude"
        self.assertEqual([], self.validate(valid))

    def test_host_switch_receipt_binds_the_current_handoff_content(self) -> None:
        """A reviewer cannot accept a missing, stale, or rootless cross-host handoff."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            handoff = root / "handoffs" / "0001" / "HANDOFF.md"
            handoff.parent.mkdir(parents=True)
            original = b"# Current handoff\n\nMeasured proof is attached.\n"
            handoff.write_bytes(original)
            state = self.template("agent-state-graph.json")
            state["events"] = [
                {
                    "type": "host-switch",
                    "from": "codex",
                    "to": "claude",
                    "handoff": "handoffs/0001/HANDOFF.md",
                    "handoff_sha256": hashlib.sha256(original).hexdigest(),
                }
            ]

            self.assertEqual([], self.validate(state, root))
            self.assertIn(
                "eventful state requires an explicit project root",
                validate_agent_state.validate_state(state),
            )

            handoff.write_text("# Replaced handoff\n", encoding="utf-8")
            errors = self.validate(state, root)
            self.assertIn("event 0 handoff_sha256 does not match current content", errors)

            handoff.unlink()
            errors = self.validate(state, root)
            self.assertTrue(any("handoff cannot be verified" in error for error in errors), errors)

            handoff.write_bytes(b"x" * (validate_agent_state.MAX_HANDOFF_BYTES + 1))
            errors = self.validate(state, root)
            self.assertTrue(any("exceeds" in error for error in errors), errors)

    def test_host_switch_receipt_does_not_follow_a_handoff_link(self) -> None:
        """A malicious project cannot redirect a handoff receipt outside its repository."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as outside:
            root = Path(directory)
            content = b"# Outside handoff\n"
            outside_handoff = Path(outside) / "HANDOFF.md"
            outside_handoff.write_bytes(content)
            linked = root / "handoffs" / "0001" / "HANDOFF.md"
            linked.parent.mkdir(parents=True)
            try:
                linked.symlink_to(outside_handoff)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {type(exc).__name__}")
            state = self.template("agent-state-graph.json")
            state["events"] = [
                {
                    "type": "host-switch",
                    "from": "codex",
                    "to": "claude",
                    "handoff": "handoffs/0001/HANDOFF.md",
                    "handoff_sha256": hashlib.sha256(content).hexdigest(),
                }
            ]

            errors = self.validate(state, root)
            self.assertTrue(any("link" in error for error in errors), errors)

    def test_state_cli_requires_and_uses_the_explicit_event_root(self) -> None:
        """A maintainer gets a closed failure until the CLI can verify the handoff root."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            handoff = root / "handoffs" / "0001" / "HANDOFF.md"
            handoff.parent.mkdir(parents=True)
            content = b"# CLI handoff\n"
            handoff.write_bytes(content)
            state = self.template("agent-state-graph.json")
            state["events"] = [
                {
                    "type": "host-switch",
                    "from": "codex",
                    "to": "cursor",
                    "handoff": "handoffs/0001/HANDOFF.md",
                    "handoff_sha256": hashlib.sha256(content).hexdigest(),
                }
            ]
            state_path = root / "state.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            command = [sys.executable, str(ROOT / "scripts" / "validate_agent_state.py")]

            rootless = subprocess.run(
                [*command, str(state_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(1, rootless.returncode, rootless.stdout + rootless.stderr)
            self.assertIn("explicit project root", rootless.stdout)

            verified = subprocess.run(
                [*command, str(state_path), "--project-root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, verified.returncode, verified.stdout + verified.stderr)
            self.assertIn("PASS: bounded agent state", verified.stdout)

    def test_each_host_switch_binds_a_distinct_immutable_snapshot(self) -> None:
        """A two-switch run cannot reuse one mutable handoff as both audit events."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            first = root / "handoffs" / "0001" / "HANDOFF.md"
            second = root / "handoffs" / "0002" / "HANDOFF.md"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first_bytes = b"# Switch one\n\nCodex yielded to Claude.\n"
            second_bytes = b"# Switch two\n\nClaude yielded to Cursor.\n"
            first.write_bytes(first_bytes)
            second.write_bytes(second_bytes)
            state = self.template("agent-state-graph.json")
            state["events"] = [
                {
                    "type": "host-switch",
                    "from": "codex",
                    "to": "claude",
                    "handoff": "handoffs/0001/HANDOFF.md",
                    "handoff_sha256": hashlib.sha256(first_bytes).hexdigest(),
                },
                {
                    "type": "host-switch",
                    "from": "claude",
                    "to": "cursor",
                    "handoff": "handoffs/0002/HANDOFF.md",
                    "handoff_sha256": hashlib.sha256(second_bytes).hexdigest(),
                },
            ]

            self.assertEqual([], self.validate(state, root))

            state["events"][1]["handoff"] = "handoffs/0001/HANDOFF.md"
            state["events"][1]["handoff_sha256"] = hashlib.sha256(first_bytes).hexdigest()
            errors = self.validate(state, root)
            self.assertTrue(any("immutable per-switch snapshot" in error for error in errors), errors)

    def test_state_loader_rejects_growing_or_linked_inputs(self) -> None:
        """An operator cannot make the state validator follow a link or read beyond its cap."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as outside:
            root = Path(directory)
            oversized = root / "oversized.json"
            oversized.write_bytes(b"x" * (validate_agent_state.MAX_STATE_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "exceeds"):
                validate_agent_state.load_state(oversized)

            outside_state = Path(outside) / "state.json"
            outside_state.write_text("{}\n", encoding="utf-8")
            linked = root / "linked.json"
            try:
                linked.symlink_to(outside_state)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {type(exc).__name__}")
            with self.assertRaisesRegex(ValueError, "non-symlink"):
                validate_agent_state.load_state(linked)


class SkillSynchronizationScenarios(unittest.TestCase):
    def make_source(self, root: Path) -> Path:
        source = root / ".agents" / "skills"
        skill = source / "inspect-change"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: inspect-change\ndescription: Inspect one change.\n---\n", encoding="utf-8")
        return source

    def test_newcomer_gets_a_copy_safe_idempotent_claude_skill_tree(self) -> None:
        """A newcomer can synchronize once and rerun without creating divergent copies."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            source = self.make_source(root)
            target = root / ".claude" / "skills"
            self.assertEqual(["copied:inspect-change"], sync_skills.sync(source, target, force=False))
            self.assertEqual(["unchanged:inspect-change"], sync_skills.sync(source, target, force=False))
            self.assertEqual([], sync_skills.check(source, target))

    def test_maintainer_must_explicitly_replace_or_preserve_skill_drift(self) -> None:
        """A maintainer cannot silently overwrite edits in a host-specific mirror."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            source = self.make_source(root)
            target = root / ".claude" / "skills"
            sync_skills.sync(source, target, force=False)
            (target / "inspect-change" / "SKILL.md").write_text("local divergence\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "divergent target preserved"):
                sync_skills.sync(source, target, force=False)
            self.assertEqual(["replaced:inspect-change"], sync_skills.sync(source, target, force=True))
            self.assertEqual([], sync_skills.check(source, target))

    def test_forced_replacement_preserves_the_previous_skill_on_stage_failure(self) -> None:
        """A failed forced sync cannot erase the last usable generated skill."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            source = self.make_source(root)
            target = root / ".claude" / "skills"
            sync_skills.sync(source, target, force=False)
            destination = target / "inspect-change" / "SKILL.md"
            previous = b"locally reviewed previous copy\n"
            destination.write_bytes(previous)

            def fail_after_partial_copy(_source: Path, staged: Path) -> None:
                staged.mkdir(parents=True)
                (staged / "SKILL.md").write_text("partial replacement\n", encoding="utf-8")
                raise OSError("synthetic staging failure")

            with mock.patch.object(sync_skills, "copy_skill", side_effect=fail_after_partial_copy):
                with self.assertRaisesRegex(OSError, "synthetic staging failure"):
                    sync_skills.sync(source, target, force=True)

            self.assertEqual(previous, destination.read_bytes())
            self.assertEqual(["drift:inspect-change"], sync_skills.check(source, target))
            self.assertFalse(any(path.name.startswith(".inspect-change.stage-") for path in target.iterdir()))

    def test_extra_target_skills_are_bounded_reported_and_never_removed(self) -> None:
        """A maintainer sees local-only skills while sync and removal leave them untouched."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            source = self.make_source(root)
            target = root / ".claude" / "skills"
            extra = target / "local-only"
            extra.mkdir(parents=True)
            (extra / "SKILL.md").write_text("local skill\n", encoding="utf-8")

            actions = sync_skills.sync(source, target, force=False)
            self.assertCountEqual(
                ["copied:inspect-change", "preserved-extra:local-only"],
                actions,
            )
            self.assertEqual(["extra:local-only"], sync_skills.check(source, target))

            canonical = target / "inspect-change" / "SKILL.md"
            canonical.write_text("divergent generated copy\n", encoding="utf-8")
            actions = sync_skills.sync(source, target, force=True)
            self.assertCountEqual(
                ["replaced:inspect-change", "preserved-extra:local-only"],
                actions,
            )
            self.assertTrue(extra.is_dir())

            actions = sync_skills.remove(source, target)
            self.assertCountEqual(
                ["removed:inspect-change", "preserved-extra:local-only"],
                actions,
            )
            self.assertTrue(extra.is_dir())

    def test_target_inventory_stops_before_an_unbounded_extra_skill_flood(self) -> None:
        """A generated mirror with excessive unknown entries fails before an unbounded scan."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            source = self.make_source(root)
            target = root / ".claude" / "skills"
            target.mkdir(parents=True)
            for index in range(sync_skills.MAX_TARGET_ENTRIES + 1):
                (target / f"extra-{index:03d}").mkdir()
            with self.assertRaisesRegex(ValueError, "target entry cap exceeded"):
                sync_skills.check(source, target)

    def test_linked_target_root_is_rejected_before_sync_check_or_remove(self) -> None:
        """An operator cannot make the generated mirror follow a target-root directory link."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as outside:
            root = Path(directory)
            source = self.make_source(root)
            claude = root / ".claude"
            claude.mkdir()
            target = claude / "skills"
            outside_target = Path(outside) / "skills"
            outside_target.mkdir()
            try:
                target.symlink_to(outside_target, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {type(exc).__name__}")

            for operation in (
                lambda: sync_skills.sync(source, target, force=True),
                lambda: sync_skills.check(source, target),
                lambda: sync_skills.remove(source, target),
            ):
                with self.subTest(operation=operation):
                    with self.assertRaisesRegex(ValueError, "symlinked target skill root"):
                        operation()

    def test_linked_target_parent_cannot_redirect_direct_sync_outside_project(self) -> None:
        """A direct library call cannot follow a linked host directory outside the project."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as outside:
            root = Path(directory)
            source = self.make_source(root)
            outside_claude = Path(outside) / ".claude"
            outside_claude.mkdir()
            linked_parent = root / ".claude"
            try:
                linked_parent.symlink_to(outside_claude, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {type(exc).__name__}")
            target = linked_parent / "skills"

            for operation in (
                lambda: sync_skills.sync(source, target, force=True),
                lambda: sync_skills.check(source, target),
                lambda: sync_skills.remove(source, target),
            ):
                with self.subTest(operation=operation):
                    with self.assertRaisesRegex(ValueError, "linked target path component"):
                        operation()
            self.assertFalse((outside_claude / "skills").exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction semantics")
    def test_windows_junctions_cannot_redirect_source_or_target_trees(self) -> None:
        """A Windows user gets the same confinement for junctions as for symbolic links."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as outside:
            root = Path(directory)
            outside_root = Path(outside)

            outside_claude = outside_root / "claude"
            outside_claude.mkdir()
            target_parent = root / ".claude"
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(target_parent), str(outside_claude)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                self.skipTest(f"junction creation unavailable: exit {result.returncode}")

            source = self.make_source(root)
            target = target_parent / "skills"
            self.assertTrue(sync_skills.is_link_like(target_parent))
            with self.assertRaisesRegex(ValueError, "linked target path component"):
                sync_skills.sync(source, target, force=True)
            self.assertFalse((outside_claude / "skills").exists())

            outside_source = self.make_source(outside_root / "source")
            linked_source = root / "linked" / ".agents" / "skills"
            linked_source.parent.mkdir(parents=True)
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(linked_source), str(outside_source)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                self.skipTest(f"source junction creation unavailable: exit {result.returncode}")
            self.assertTrue(sync_skills.is_link_like(linked_source))
            with self.assertRaisesRegex(ValueError, "canonical skill root is linked"):
                sync_skills.canonical_skills(linked_source)

    def test_skill_discovery_stops_directory_and_file_floods_before_materializing_them(self) -> None:
        """A large generated skill tree cannot consume unbounded discovery memory."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            source = root / "skills"
            source.mkdir()
            for index in range(sync_skills.MAX_SKILLS + 1):
                (source / f"skill-{index:03d}").mkdir()
            with self.assertRaisesRegex(ValueError, "skill cap exceeded"):
                sync_skills.canonical_skills(source)

            shutil.rmtree(source)
            skill = source / "bounded-skill"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: bounded-skill\n---\n", encoding="utf-8")
            for index in range(sync_skills.MAX_ENTRIES_PER_SKILL + 1):
                (skill / f"empty-{index:03d}").mkdir()
            with self.assertRaisesRegex(ValueError, "entry cap exceeded"):
                sync_skills.skill_files(skill)

    def test_skill_discovery_rejects_nested_links_and_growing_files(self) -> None:
        """A skill author cannot hide external content behind a link or exceed the read cap."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as outside:
            root = Path(directory)
            source = self.make_source(root)
            skill = source / "inspect-change"
            outside_directory = Path(outside) / "external"
            outside_directory.mkdir()
            linked = skill / "linked"
            try:
                linked.symlink_to(outside_directory, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {type(exc).__name__}")
            with self.assertRaisesRegex(ValueError, "symlinked skill entry"):
                sync_skills.skill_files(skill)

            linked.unlink()
            growing = skill / "large.txt"
            growing.write_bytes(b"x" * (sync_skills.MAX_FILE_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "too large"):
                sync_skills.read_bounded_bytes(growing)

    def test_linked_canonical_source_is_rejected_before_cli_resolution(self) -> None:
        """The CLI cannot launder an external source tree through early path resolution."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as outside:
            root = Path(directory)
            agents = root / ".agents"
            agents.mkdir()
            outside_source = self.make_source(Path(outside))
            linked_source = agents / "skills"
            try:
                linked_source.symlink_to(outside_source, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {type(exc).__name__}")

            with self.assertRaisesRegex(ValueError, "canonical skill root is linked"):
                sync_skills.canonical_skills(linked_source)
            with mock.patch.object(
                sys,
                "argv",
                ["sync_skills.py", "sync", "--project-root", str(root)],
            ), mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(1, sync_skills.main())
            self.assertIn("canonical skill root is linked", output.getvalue())
            self.assertFalse((root / ".claude" / "skills").exists())


class HookContinuityScenarios(unittest.TestCase):
    def test_review_digest_changes_when_an_already_changed_file_changes_again(self) -> None:
        """A developer cannot evade another review nudge by editing the same dirty path."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            (root / "HANDOFF.md").write_text("Current handoff\n", encoding="utf-8")
            source = root / "worker.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            first = self_review_hook.tree_digest(root)
            source.write_text("VALUE = 2\n", encoding="utf-8")
            second = self_review_hook.tree_digest(root)

            self.assertNotEqual(first, second)

    def test_review_digest_covers_public_environment_templates_but_not_local_values(self) -> None:
        """A config-template edit triggers review without fingerprinting local environment values."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            public_template = root / ".env.example"
            local_values = root / ".env.local"
            public_template.write_text("PUBLIC_SETTING=one\n", encoding="utf-8")
            local_values.write_text("LOCAL_SETTING=one\n", encoding="utf-8")
            first = self_review_hook.tree_digest(root)
            public_template.write_text("PUBLIC_SETTING=two\n", encoding="utf-8")
            second = self_review_hook.tree_digest(root)
            local_values.write_text("LOCAL_SETTING=two\n", encoding="utf-8")
            third = self_review_hook.tree_digest(root)

            self.assertNotEqual(first, second)
            self.assertEqual(second, third)

    def test_review_digest_covers_files_after_the_previous_512_file_boundary(self) -> None:
        """A developer in an ordinary larger repository cannot edit a late file without a nudge."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            for index in range(513):
                (root / f"f-{index:04d}.txt").write_text("before\n", encoding="utf-8")
            first = self_review_hook.tree_digest(root)
            (root / "f-0000.txt").write_text("after\n", encoding="utf-8")
            second = self_review_hook.tree_digest(root)

            self.assertNotEqual(first, second)

    def test_review_digest_reports_bounds_instead_of_returning_a_sampled_pass(self) -> None:
        """An oversized public tree fails closed instead of reusing one partial fingerprint."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            for index in range(3):
                (root / f"file-{index}.txt").write_text("bounded\n", encoding="utf-8")
            with mock.patch.object(self_review_hook, "MAX_TREE_ENTRIES", 2):
                with self.assertRaisesRegex(ValueError, "entry count exceeds"):
                    self_review_hook.tree_digest(root)

            oversized = root / "oversized.txt"
            oversized.write_bytes(b"x" * 9)
            with mock.patch.object(self_review_hook, "MAX_TREE_FILE_BYTES", 8):
                with self.assertRaisesRegex(ValueError, "tree file exceeds"):
                    self_review_hook.tree_digest(root)

    def test_review_digest_does_not_read_credential_named_content(self) -> None:
        """A continuity reminder fingerprints public work without processing a local secret."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            secret = root / ".env"
            secret.write_text("SYNTHETIC_VALUE=one\n", encoding="utf-8")
            first = self_review_hook.tree_digest(root)
            secret.write_text("SYNTHETIC_VALUE=two\n", encoding="utf-8")
            second = self_review_hook.tree_digest(root)

            self.assertEqual(first, second)

    def test_review_digest_excludes_private_instructions_and_generated_worktrees(self) -> None:
        """A main session does not react to private instructions or sibling worktree edits."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            private_instruction = root / "CLAUDE.local.md"
            private_instruction.write_text("private one\n", encoding="utf-8")
            worktree_file = root / ".claude" / "worktrees" / "worker" / "change.py"
            worktree_file.parent.mkdir(parents=True)
            worktree_file.write_text("VALUE = 1\n", encoding="utf-8")
            first = self_review_hook.tree_digest(root)
            private_instruction.write_text("private two\n", encoding="utf-8")
            worktree_file.write_text("VALUE = 2\n", encoding="utf-8")
            second = self_review_hook.tree_digest(root)

            self.assertEqual(first, second)

    def test_review_digest_includes_shared_codex_config_and_excludes_generated_host_state(self) -> None:
        """A target reviews shared Codex adapters without reacting to generated host mirrors."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            codex_config = root / ".codex" / "config.toml"
            codex_config.parent.mkdir()
            codex_config.write_text("approval_policy = 'on-request'\n", encoding="utf-8")
            generated_skill = root / ".claude" / "skills" / "generated" / "SKILL.md"
            generated_skill.parent.mkdir(parents=True)
            generated_skill.write_text("generated one\n", encoding="utf-8")
            runtime_state = root / ".codex-run" / "state.json"
            runtime_state.parent.mkdir()
            runtime_state.write_text("one\n", encoding="utf-8")

            first = self_review_hook.tree_digest(root)
            codex_config.write_text("approval_policy = 'never'\n", encoding="utf-8")
            second = self_review_hook.tree_digest(root)
            generated_skill.write_text("generated two\n", encoding="utf-8")
            runtime_state.write_text("two\n", encoding="utf-8")
            third = self_review_hook.tree_digest(root)

            self.assertNotEqual(first, second)
            self.assertEqual(second, third)

    @unittest.skipUnless(os.name == "nt", "Windows junction semantics")
    def test_hook_state_cannot_write_through_a_windows_junction(self) -> None:
        """A hook cannot redirect its project-local checkpoint write to an outside directory."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as outside:
            root = Path(directory)
            outside_root = Path(outside)
            linked_state = root / ".agent-local"
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(linked_state), str(outside_root)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                self.skipTest(f"junction creation unavailable: exit {result.returncode}")

            with self.assertRaisesRegex(ValueError, "local directories"):
                self_review_hook.atomic_write(root, "state.json", "{}")

            self.assertFalse((outside_root / "self-review" / "state.json").exists())

    def test_hook_rejects_oversized_and_malformed_vendor_input(self) -> None:
        """A malformed host event produces a bounded error instead of retained prompt data."""
        with self.assertRaisesRegex(ValueError, "exceeds"):
            self_review_hook.read_payload(_BinaryInput(b"x" * (self_review_hook.MAX_INPUT_BYTES + 1)))
        with self.assertRaises(json.JSONDecodeError):
            self_review_hook.read_payload(_BinaryInput(b"{not-json"))

        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/self_review_hook.py"),
                "--host",
                "claude",
                "--event",
                "session-start",
            ],
            input="{not-json",
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(1, completed.returncode)
        self.assertEqual("", completed.stdout)
        self.assertIn("JSONDecodeError", completed.stderr)
        self.assertLessEqual(
            len(completed.stderr.encode("utf-8")),
            self_review_hook.MAX_HOOK_OUTPUT_BYTES,
        )

    def test_session_start_refuses_oversized_or_external_checkpoint_content(self) -> None:
        """A resumed host cannot ingest an oversized checkpoint or one linked outside the project."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as outside:
            root = Path(directory)
            state = root / self_review_hook.STATE_DIR
            state.mkdir(parents=True)
            checkpoint = state / "CHECKPOINT.md"
            checkpoint.write_text(
                "x" * (self_review_hook.MAX_CHECKPOINT_BYTES + 1),
                encoding="utf-8",
            )
            oversized = self_review_hook.start_output("cursor", root)["additional_context"]
            self.assertIn("unavailable or invalid", oversized)

            checkpoint.unlink()
            sentinel = "SYNTHETIC_EXTERNAL_CREDENTIAL_SENTINEL"
            outside_checkpoint = Path(outside) / "CHECKPOINT.md"
            outside_checkpoint.write_text(sentinel, encoding="utf-8")
            try:
                checkpoint.symlink_to(outside_checkpoint)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {type(exc).__name__}")
            linked = self_review_hook.start_output("cursor", root)["additional_context"]
            self.assertNotIn(sentinel, linked)
            self.assertIn("unavailable or invalid", linked)

    def test_session_start_reconstructs_only_a_strict_generated_checkpoint(self) -> None:
        """A local checkpoint edit cannot inject arbitrary instructions into a resumed host."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            state = root / self_review_hook.STATE_DIR
            state.mkdir(parents=True)
            sentinel = "SYNTHETIC_UNTRUSTED_CHECKPOINT_INSTRUCTION"
            (state / "CHECKPOINT.md").write_text(
                self_review_hook.checkpoint_text("a" * 16, "b" * 64) + sentinel,
                encoding="utf-8",
            )

            resumed = self_review_hook.start_output("claude", root)
            context = resumed["hookSpecificOutput"]["additionalContext"]

            self.assertNotIn(sentinel, context)
            self.assertIn("unavailable or invalid", context)

    def test_corrupt_resume_state_fails_closed_without_overwriting_evidence(self) -> None:
        """A malformed local state file is preserved for diagnosis instead of reset to empty."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            state = root / self_review_hook.STATE_DIR
            state.mkdir(parents=True)
            state_path = state / "state.json"
            malformed = b'{"sessions":{"not-a-fingerprint":{"count":999,"digest":"bad"}}}'
            state_path.write_bytes(malformed)
            payload = {
                "conversation_id": "resume-after-corruption",
                "status": "completed",
                "loop_count": 0,
            }

            with mock.patch.object(self_review_hook, "tree_digest", return_value="c" * 64):
                with self.assertRaisesRegex(ValueError, "state.json is unavailable or invalid"):
                    self_review_hook.stop_output("cursor", root, payload)

            self.assertEqual(malformed, state_path.read_bytes())
            self.assertFalse((state / "state.lock").exists())

    def test_compaction_checkpoint_uses_fingerprints_not_raw_session_content(self) -> None:
        """A person resuming work gets continuity without replaying sensitive conversation text."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            payload = {"session_id": "synthetic-sensitive-session-text"}
            with mock.patch.object(self_review_hook, "tree_digest", return_value="a" * 64):
                self_review_hook.write_checkpoint("claude", root, payload)
            content = (root / self_review_hook.STATE_DIR / "CHECKPOINT.md").read_text(encoding="utf-8")
            self.assertNotIn(payload["session_id"], content)
            self.assertIn("Session fingerprint", content)
            resumed = self_review_hook.start_output("cursor", root)
            self.assertIn("additional_context", resumed)
            codex_resumed = self_review_hook.start_output("codex", root)
            self.assertEqual(
                "SessionStart",
                codex_resumed["hookSpecificOutput"]["hookEventName"],
            )

    def test_concurrent_stop_events_emit_one_nudge_for_one_change_set(self) -> None:
        """Several hosts stopping together cannot corrupt state or multiply one review request."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            payload = {
                "conversation_id": "shared-conversation",
                "status": "completed",
                "loop_count": 0,
            }
            barrier = threading.Barrier(24)

            def concurrent_stop(_: int) -> dict[str, object]:
                barrier.wait()
                return self_review_hook.stop_output("cursor", root, payload)

            with mock.patch.object(self_review_hook, "tree_digest", return_value="b" * 64):
                with ThreadPoolExecutor(max_workers=24) as pool:
                    outputs = list(pool.map(concurrent_stop, range(24)))
            nudges = [output for output in outputs if "followup_message" in output]
            self.assertEqual(1, len(nudges))
            state = json.loads(self_review_hook.state_path(root).read_text(encoding="utf-8"))
            self.assertEqual(1, next(iter(state["sessions"].values()))["count"])

    def test_cursor_stop_uses_real_conversation_ids_as_separate_nudge_windows(self) -> None:
        """Two Cursor conversations cannot exhaust each other's self-review limit."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            first = {"conversation_id": "cursor-conversation-a", "status": "completed", "loop_count": 0}
            second = {"conversation_id": "cursor-conversation-b", "status": "completed", "loop_count": 0}
            digests = [f"{index:064x}" for index in range(1, 7)]
            with mock.patch.object(self_review_hook, "tree_digest", side_effect=digests):
                first_outputs = [
                    self_review_hook.stop_output("cursor", root, first)
                    for _ in range(self_review_hook.MAX_NUDGES_PER_SESSION)
                ]
                second_output = self_review_hook.stop_output("cursor", root, second)

            self.assertTrue(all("followup_message" in item for item in first_outputs))
            self.assertIn("followup_message", second_output)
            state = json.loads(self_review_hook.state_path(root).read_text(encoding="utf-8"))
            self.assertEqual(2, len(state["sessions"]))
            self.assertEqual(
                {
                    self_review_hook.session_key("cursor", first),
                    self_review_hook.session_key("cursor", second),
                },
                set(state["sessions"]),
            )

    def test_cursor_session_identity_ignores_ephemeral_generation_and_vendor_session_ids(self) -> None:
        """One Cursor conversation keeps one window while unrelated conversations stay isolated."""
        first = {
            "conversation_id": "cursor-conversation-a",
            "session_id": "shared-vendor-session",
            "generation_id": "generation-one",
        }
        same_conversation = {
            "conversation_id": "cursor-conversation-a",
            "session_id": "shared-vendor-session",
            "generation_id": "generation-two",
        }
        other_conversation = {
            "conversation_id": "cursor-conversation-b",
            "session_id": "shared-vendor-session",
            "generation_id": "generation-one",
        }

        self.assertEqual(
            self_review_hook.session_key("cursor", first),
            self_review_hook.session_key("cursor", same_conversation),
        )
        self.assertNotEqual(
            self_review_hook.session_key("cursor", first),
            self_review_hook.session_key("cursor", other_conversation),
        )

    def test_hook_identity_rejects_non_utf8_surrogates(self) -> None:
        """Malformed vendor identifiers cannot collapse into a replacement-character collision."""
        with self.assertRaises(UnicodeEncodeError):
            self_review_hook.session_key("cursor", {"conversation_id": "bad-\ud800"})

    def test_claude_hook_tracks_changes_inside_its_generated_git_worktree(self) -> None:
        """A Claude worker receives continuity proof for its active worktree, not the main checkout."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT, prefix="claude hook repo ") as directory:
            main_root = Path(directory) / "main project"
            scripts = main_root / "scripts"
            scripts.mkdir(parents=True)
            shutil.copy2(ROOT / "scripts" / "self_review_hook.py", scripts)
            shutil.copy2(ROOT / "scripts" / "path_safety.py", scripts)
            shutil.copy2(ROOT / "scripts" / "bounded_process.py", scripts)
            tracked = main_root / "tracked.txt"
            tracked.write_text("main\n", encoding="utf-8")
            subprocess.run(["git", "init", "--quiet", str(main_root)], check=True)
            subprocess.run(["git", "-C", str(main_root), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(main_root), "-c", "user.name=Scenario User",
                    "-c", "user.email=scenario@example.invalid", "commit", "--quiet", "-m", "base",
                ],
                check=True,
            )
            worktree = main_root / ".claude" / "worktrees" / "worker-one"
            worktree.parent.mkdir(parents=True)
            subprocess.run(
                ["git", "-C", str(main_root), "worktree", "add", "--quiet", "-b", "worker-one", str(worktree)],
                check=True,
            )
            nested = worktree / "src" / "nested"
            nested.mkdir(parents=True)
            payload = json.dumps({"session_id": "claude-session", "cwd": str(nested)})
            command = [
                sys.executable,
                str(scripts / "self_review_hook.py"),
                "--host", "claude", "--event", "stop",
            ]

            first = subprocess.run(command, input=payload, capture_output=True, text=True, timeout=10)
            (worktree / "tracked.txt").write_text("worktree edit\n", encoding="utf-8")
            second = subprocess.run(command, input=payload, capture_output=True, text=True, timeout=10)
            compact = subprocess.run(
                command[:-1] + ["pre-compact"],
                input=payload,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            self.assertEqual(0, second.returncode, second.stdout + second.stderr)
            self.assertEqual(0, compact.returncode, compact.stdout + compact.stderr)
            self.assertLessEqual(len(first.stdout.encode("utf-8")), self_review_hook.MAX_HOOK_OUTPUT_BYTES)
            self.assertEqual("block", json.loads(first.stdout)["decision"])
            self.assertEqual("block", json.loads(second.stdout)["decision"])
            self.assertTrue((worktree / self_review_hook.STATE_DIR / "CHECKPOINT.md").is_file())
            self.assertFalse((main_root / self_review_hook.STATE_DIR).exists())

    def test_claude_ordinary_non_git_cwd_keeps_the_configured_project_root(self) -> None:
        """A non-Git project can use the hook until it enters the reserved worktree namespace."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            nested = root / "src" / "nested"
            nested.mkdir(parents=True)

            self.assertEqual(
                root.resolve(),
                self_review_hook.resolve_event_root(
                    "claude", {"cwd": str(nested)}, project_root=root
                ),
            )

    def test_claude_rejects_a_linked_directory_in_the_worktree_namespace(self) -> None:
        """A crafted worktree path cannot redirect checkpoint state outside the project."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as outside:
            main_root = Path(directory)
            namespace = main_root / ".claude" / "worktrees"
            namespace.mkdir(parents=True)
            linked = namespace / "linked-worker"
            outside_root = Path(outside) / "outside-worker"
            outside_root.mkdir()
            try:
                linked.symlink_to(outside_root, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {type(exc).__name__}")
            with self.assertRaisesRegex(ValueError, "link"):
                self_review_hook.resolve_event_root(
                    "claude", {"cwd": str(linked)}, project_root=main_root
                )
            self.assertFalse((outside_root / self_review_hook.STATE_DIR).exists())

    def test_claude_rejects_an_unrelated_repository_in_the_worktree_namespace(self) -> None:
        """A nested repository cannot impersonate a generated worktree for this project."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            main_root = Path(directory)
            subprocess.run(["git", "init", "--quiet", str(main_root)], check=True)
            (main_root / "tracked.txt").write_text("main\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(main_root), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(main_root), "-c", "user.name=Scenario User",
                    "-c", "user.email=scenario@example.invalid", "commit", "--quiet", "-m", "base",
                ],
                check=True,
            )
            namespace = main_root / ".claude" / "worktrees"
            namespace.mkdir(parents=True)
            imposter = namespace / "imposter"
            imposter.mkdir()
            subprocess.run(["git", "init", "--quiet", str(imposter)], check=True)
            with self.assertRaisesRegex(ValueError, "does not share"):
                self_review_hook.resolve_event_root(
                    "claude", {"cwd": str(imposter)}, project_root=main_root
                )
            self.assertFalse((imposter / self_review_hook.STATE_DIR).exists())

    def test_claude_worktree_identity_ignores_poisoned_git_environment(self) -> None:
        """Inherited Git routing variables cannot move a valid hook into another repository."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            main_root = Path(directory) / "main"
            main_root.mkdir()
            (main_root / "tracked.txt").write_text("main\n", encoding="utf-8")
            subprocess.run(["git", "init", "--quiet", str(main_root)], check=True)
            subprocess.run(["git", "-C", str(main_root), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(main_root), "-c", "user.name=Scenario User",
                    "-c", "user.email=scenario@example.invalid", "commit", "--quiet", "-m", "base",
                ],
                check=True,
            )
            worktree = main_root / ".claude" / "worktrees" / "worker"
            worktree.parent.mkdir(parents=True)
            subprocess.run(
                ["git", "-C", str(main_root), "worktree", "add", "--quiet", "-b", "worker", str(worktree)],
                check=True,
            )

            with mock.patch.dict(
                os.environ,
                {"GIT_DIR": str(main_root / "missing"), "GIT_WORK_TREE": str(main_root / "wrong")},
            ):
                selected = self_review_hook.resolve_event_root(
                    "claude", {"cwd": str(worktree)}, project_root=main_root
                )

            self.assertEqual(worktree.resolve(), selected)

    def test_git_identity_probe_enforces_one_deadline_and_output_cap(self) -> None:
        """A stuck or noisy Git process cannot hold a hook open or fill memory."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            with mock.patch.object(
                self_review_hook,
                "run_bounded",
                side_effect=subprocess.TimeoutExpired(["git"], 0.01),
            ):
                with self.assertRaisesRegex(TimeoutError, "budget exhausted"):
                    self_review_hook._git_path(root, "--show-toplevel", float("inf"))

            with mock.patch.object(
                self_review_hook,
                "run_bounded",
                side_effect=self_review_hook.OutputLimitExceeded("synthetic overflow"),
            ):
                with self.assertRaisesRegex(ValueError, "output exceeded"):
                    self_review_hook._git_path(root, "--show-toplevel", float("inf"))

    def test_sustained_sessions_remain_bounded(self) -> None:
        """A long-running workstation does not accumulate an unbounded session history."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            with mock.patch.object(self_review_hook, "tree_digest", return_value="c" * 64):
                for index in range(96):
                    self_review_hook.stop_output("claude", root, {"session_id": f"session-{index:03d}"})
            state_path = self_review_hook.state_path(root)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(64, len(state["sessions"]))
            self.assertLessEqual(state_path.stat().st_size, self_review_hook.MAX_CHECKPOINT_BYTES)

    def test_active_session_keeps_its_nudge_cap_under_eviction_pressure(self) -> None:
        """A busy workstation cannot reset one active session's cap by evicting each update."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            active_payload: dict[str, object] | None = None
            active_key = ""
            for index in range(1_000):
                candidate = {
                    "conversation_id": f"active-{index}",
                    "status": "completed",
                    "loop_count": 0,
                }
                candidate_key = self_review_hook.session_key("cursor", candidate)
                if candidate_key.startswith("0"):
                    active_payload = candidate
                    active_key = candidate_key
                    break
            self.assertIsNotNone(active_payload)
            peers = {
                f"f{index:015x}": {"count": 1, "digest": "e" * 64}
                for index in range(64)
            }
            self_review_hook.atomic_write(
                root,
                "state.json",
                json.dumps({"sessions": peers}, sort_keys=True),
            )
            digests = [f"{index:064x}" for index in range(10)]
            with mock.patch.object(self_review_hook, "tree_digest", side_effect=digests):
                outputs = [
                    self_review_hook.stop_output("cursor", root, active_payload or {})
                    for _ in range(10)
                ]

            self.assertEqual(5, sum("followup_message" in output for output in outputs))
            state = json.loads(self_review_hook.state_path(root).read_text(encoding="utf-8"))
            self.assertEqual(64, len(state["sessions"]))
            self.assertEqual(5, state["sessions"][active_key]["count"])

    def test_each_host_gets_its_native_stop_continuation_shape(self) -> None:
        """Each host receives a review nudge in the output shape its hook runner accepts."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            with mock.patch.object(self_review_hook, "tree_digest", return_value="d" * 64):
                cursor = self_review_hook.stop_output(
                    "cursor",
                    root,
                    {
                        "conversation_id": "cursor",
                        "status": "completed",
                        "loop_count": 0,
                    },
                )
                codex = self_review_hook.stop_output("codex", root, {"session_id": "codex"})
                claude = self_review_hook.stop_output("claude", root, {"session_id": "claude"})
            self.assertIn("followup_message", cursor)
            self.assertEqual("block", codex["decision"])
            self.assertEqual("block", claude["decision"])
            self.assertIn("Self-review before yielding", claude["reason"])
            self.assertEqual(
                {},
                self_review_hook.stop_output(
                    "codex", root, {"session_id": "blocked", "stop_hook_active": True}
                ),
            )
            with self.assertRaisesRegex(ValueError, "conversation_id"):
                self_review_hook.stop_output(
                    "cursor", root, {"status": "completed", "loop_count": 0}
                )

    def test_stop_hooks_do_not_continue_failed_or_still_running_work(self) -> None:
        """A failure or background task cannot be mistaken for an idle review boundary."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            self.assertEqual(
                {},
                self_review_hook.stop_output(
                    "cursor",
                    root,
                    {
                        "conversation_id": "failed-cursor-run",
                        "status": "error",
                        "loop_count": 0,
                    },
                ),
            )
            self.assertEqual(
                {},
                self_review_hook.stop_output(
                    "claude",
                    root,
                    {
                        "session_id": "busy-claude-run",
                        "background_tasks": [{"id": "task-1"}],
                        "session_crons": [],
                    },
                ),
            )
            with self.assertRaisesRegex(ValueError, "loop_count"):
                self_review_hook.stop_output(
                    "cursor",
                    root,
                    {
                        "conversation_id": "bad-loop-count",
                        "status": "completed",
                        "loop_count": "0",
                    },
                )


class SetupDoctorScenarios(unittest.TestCase):
    def build_project(self, root: Path) -> None:
        (root / "AGENTS.md").write_text("# Shared\n", encoding="utf-8")
        for relative in (
            ".agents/skills",
            ".codex/agents",
            ".claude/agents",
            ".claude/rules",
            ".claude/skills",
            ".cursor/agents",
        ):
            (root / relative).mkdir(parents=True)
        (root / ".claude" / "CLAUDE.md").write_text(
            "@../AGENTS.md\n", encoding="utf-8"
        )
        (root / ".codex" / "config.toml").write_text("approval_policy = \"on-request\"\n", encoding="utf-8")
        (root / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")
        (root / ".claude" / "rules" / "claude-code.md").write_text(
            "# Claude-only\n", encoding="utf-8"
        )
        (root / ".cursor" / "mcp.json").parent.mkdir(parents=True, exist_ok=True)
        (root / ".cursor" / "mcp.json").write_text("{\"mcpServers\": {}}\n", encoding="utf-8")
        (root / ".mcp.json").write_text("{\"mcpServers\": {}}\n", encoding="utf-8")

    def test_newcomer_sees_all_three_hosts_ready_without_credential_store_reads(self) -> None:
        """A newcomer can inspect setup shape before signing into any vendor."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            self.build_project(root)
            results = setup_doctor.inspect_project(root, ("codex", "claude", "cursor"), True)
            setup_doctor.parse_configs(root, results)
            self.assertTrue(results)
            self.assertFalse(any(item["status"] != "present" for item in results))

    def test_cursor_desktop_only_user_can_validate_project_adapters_without_agent_cli(self) -> None:
        """A desktop user can prove repository shape without installing the optional CLI."""

        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            self.build_project(root)
            with mock.patch.object(setup_doctor.shutil, "which", return_value=None):
                results = setup_doctor.inspect_project(root, ("cursor",), True)
            setup_doctor.parse_configs(root, results)

        self.assertFalse(any(item["host"] == "cursor" and item["check"] == "binary" for item in results))
        self.assertFalse([item for item in results if item["host"] == "cursor" and item["status"] != "present"])

    def test_claude_desktop_only_user_can_validate_adapters_without_cli(self) -> None:
        """A Desktop user can prove Claude adapter shape without the separate CLI."""

        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            self.build_project(root)
            with mock.patch.object(setup_doctor.shutil, "which", return_value=None):
                results = setup_doctor.inspect_project(root, ("claude",), True)
            setup_doctor.parse_configs(root, results)

        self.assertFalse(
            any(item["host"] == "claude" and item["check"] == "binary" for item in results)
        )
        self.assertFalse(
            [item for item in results if item["host"] == "claude" and item["status"] != "present"]
        )

    def test_codex_desktop_only_user_can_validate_adapters_without_cli(self) -> None:
        """An app user can prove Codex adapter shape without a separate terminal CLI."""

        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            self.build_project(root)
            with mock.patch.object(setup_doctor.shutil, "which", return_value=None):
                results = setup_doctor.inspect_project(root, ("codex",), True)
            setup_doctor.parse_configs(root, results)

        self.assertFalse(
            any(item["host"] == "codex" and item["check"] == "binary" for item in results)
        )
        self.assertFalse(
            [item for item in results if item["host"] == "codex" and item["status"] != "present"]
        )

    def test_setup_doctor_parses_optional_cursor_desktop_and_cli_policies(self) -> None:
        """A Cursor user gets a malformed-policy failure after opting into any policy lane."""

        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            self.build_project(root)
            for relative in (
                ".cursor/cli.json",
                ".cursor/permissions.json",
                ".cursor/sandbox.json",
            ):
                (root / relative).write_text("{\n", encoding="utf-8")
            results = setup_doctor.inspect_project(root, ("cursor",), True)
            setup_doctor.parse_configs(root, results)

        invalid = {
            item["check"]
            for item in results
            if item["status"] == "invalid"
        }
        self.assertEqual(
            {
                ".cursor/cli.json",
                ".cursor/permissions.json",
                ".cursor/sandbox.json",
            },
            invalid,
        )

    def test_documented_python_checks_leave_no_untracked_cache_debris(self) -> None:
        """A freshly staged project stays clean after the setup doctor imports its helpers."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            self.build_project(root)
            shutil.copy2(ROOT / "templates/project/.gitignore", root / ".gitignore")
            scripts = root / "scripts"
            scripts.mkdir()
            shutil.copy2(ROOT / "scripts/setup_doctor.py", scripts / "setup_doctor.py")
            shutil.copy2(ROOT / "scripts/path_safety.py", scripts / "path_safety.py")
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)

            completed = subprocess.run(
                [
                    sys.executable,
                    str(scripts / "setup_doctor.py"),
                    "--project-root",
                    str(root),
                    "--hosts",
                    "cursor",
                    "--skip-binaries",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            untracked = subprocess.run(
                ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout

        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual("", untracked)

    def test_newcomer_sees_missing_git_as_a_runtime_blocker(self) -> None:
        """A newcomer cannot receive a ready report when Git-dependent setup cannot run."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            self.build_project(root)
            with mock.patch.object(
                setup_doctor.shutil,
                "which",
                side_effect=lambda name: None if name == "git" else "available",
            ):
                results = setup_doctor.inspect_project(
                    root, ("codex", "claude", "cursor"), True
                )

            statuses = {item["check"]: item["status"] for item in results}
            self.assertEqual("missing", statuses["Git"])
            self.assertEqual("present", statuses["Python >= 3.11"])

    def test_operator_gets_distinct_missing_and_malformed_diagnostics(self) -> None:
        """An operator can tell an absent adapter from a broken one."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            self.build_project(root)
            (root / ".cursor" / "mcp.json").write_text("{broken", encoding="utf-8")
            (root / ".codex" / "agents").rmdir()
            results = setup_doctor.inspect_project(root, ("codex", "claude", "cursor"), True)
            setup_doctor.parse_configs(root, results)
        self.assertTrue(any(item["status"] == "missing" for item in results))
        self.assertTrue(any(item["status"] == "invalid" for item in results))

    def test_operator_is_stopped_by_config_directories_and_external_symlinks(self) -> None:
        """A setup audit cannot accept a directory or follow a config link outside the project."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as outside:
            root = Path(directory)
            self.build_project(root)
            cursor = root / ".cursor" / "mcp.json"
            cursor.unlink()
            cursor.mkdir()
            claude = root / ".claude" / "settings.json"
            claude.unlink()
            outside_config = Path(outside) / "settings.json"
            outside_config.write_text("{}\n", encoding="utf-8")
            try:
                claude.symlink_to(outside_config)
            except OSError as exc:
                self.skipTest(f"symlink creation unavailable: {type(exc).__name__}")

            results = setup_doctor.inspect_project(root, ("codex", "claude", "cursor"), True)
            setup_doctor.parse_configs(root, results)

            statuses = {item["check"]: item["status"] for item in results}
            self.assertEqual("invalid", statuses[".cursor/mcp.json"])
            self.assertEqual("invalid", statuses[".claude/settings.json"])

    @unittest.skipUnless(os.name == "nt", "Windows junction semantics")
    def test_setup_doctor_rejects_a_windows_junctioned_config_parent(self) -> None:
        """A setup diagnosis cannot validate host configuration stored outside the project."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, tempfile.TemporaryDirectory(dir=TEMP_ROOT) as outside:
            root = Path(directory)
            outside_claude = Path(outside) / "claude"
            outside_claude.mkdir()
            (outside_claude / "agents").mkdir()
            (outside_claude / "skills").mkdir()
            (outside_claude / "settings.json").write_text("{}\n", encoding="utf-8")
            result = subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(root / ".claude"), str(outside_claude)],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                self.skipTest(f"junction creation unavailable: exit {result.returncode}")

            results = setup_doctor.inspect_project(root, ("claude",), True)
            setup_doctor.parse_configs(root, results)
            statuses = {item["check"]: item["status"] for item in results}

            self.assertEqual("invalid", statuses[".claude/settings.json"])
            self.assertEqual("invalid", statuses[".claude/agents"])
            self.assertEqual("invalid", statuses[".claude/skills"])


class PublicTemplateScenarios(unittest.TestCase):
    def test_branch_stack_requires_a_relationship_instead_of_passing_vacuously(self) -> None:
        """A reviewer cannot receive a green stack receipt from only one branch ref."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "check_branch_stack.py"),
                    "HEAD",
                    "--project-root",
                    directory,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )

        self.assertEqual(2, completed.returncode)
        self.assertIn("at least two branch refs are required", completed.stdout)

    def test_branch_stack_rejects_an_overlong_ref_without_a_traceback(self) -> None:
        """An untrusted branch name cannot overflow the bounded process contract."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, mock.patch.object(
            sys,
            "argv",
            ["check_branch_stack.py", "x" * 9_000, "HEAD", "--project-root", directory],
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            exit_code = check_branch_stack.main()

        self.assertEqual(2, exit_code)
        self.assertEqual("branch ref is empty or exceeds its cap", json.loads(output.getvalue())["error"])

    def test_branch_stack_ignores_ambient_git_redirection(self) -> None:
        """A poisoned shell cannot redirect ancestry proof away from the explicit repository."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            tracked = root / "tracked.txt"
            tracked.write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(root), "-c", "user.name=Scenario User",
                    "-c", "user.email=scenario@example.invalid", "commit", "--quiet", "-m", "one",
                ],
                check=True,
            )
            tracked.write_text("two\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(root), "-c", "user.name=Scenario User",
                    "-c", "user.email=scenario@example.invalid", "commit", "--quiet", "-m", "two",
                ],
                check=True,
            )
            with mock.patch.dict(
                os.environ,
                {"GIT_DIR": str(root / "missing-git-dir"), "GIT_WORK_TREE": str(root / "missing-worktree")},
            ), mock.patch.object(
                sys,
                "argv",
                ["check_branch_stack.py", "HEAD^", "HEAD", "--project-root", str(root)],
            ), mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                exit_code = check_branch_stack.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(0, exit_code, payload)
        self.assertTrue(payload["ok"])

    def test_branch_stack_ignores_a_replacement_that_forges_ancestry(self) -> None:
        """A replacement object cannot make sibling branches look stacked."""

        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            tracked = root / "tracked.txt"
            tracked.write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            commit = [
                "git", "-C", str(root), "-c", "user.name=Scenario User",
                "-c", "user.email=scenario@example.invalid", "commit", "--quiet", "-m",
            ]
            subprocess.run([*commit, "base"], check=True)
            base = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True,
                check=True,
                text=True,
            ).stdout.strip()
            subprocess.run(["git", "-C", str(root), "switch", "-q", "-c", "left"], check=True)
            tracked.write_text("left\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run([*commit, "left"], check=True)
            left = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True,
                check=True,
                text=True,
            ).stdout.strip()
            subprocess.run(["git", "-C", str(root), "switch", "-q", "-c", "right", base], check=True)
            tracked.write_text("right\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run([*commit, "right"], check=True)
            right = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True,
                check=True,
                text=True,
            ).stdout.strip()
            tree = subprocess.run(
                ["git", "-C", str(root), "rev-parse", f"{right}^{{tree}}"],
                capture_output=True,
                check=True,
                text=True,
            ).stdout.strip()
            replacement = subprocess.run(
                [
                    "git", "-C", str(root), "-c", "user.name=Scenario User",
                    "-c", "user.email=scenario@example.invalid", "commit-tree", tree,
                    "-p", left,
                ],
                input="forged ancestry\n",
                capture_output=True,
                check=True,
                text=True,
            ).stdout.strip()
            subprocess.run(["git", "-C", str(root), "replace", right, replacement], check=True)
            with mock.patch.object(
                sys,
                "argv",
                ["check_branch_stack.py", "left", "right", "--project-root", str(root)],
            ), mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                exit_code = check_branch_stack.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(1, exit_code, payload)
        self.assertFalse(payload["ok"])

    def test_branch_stack_rejects_a_suppressed_legacy_graft(self) -> None:
        """A graft cannot make sibling branches look stacked."""

        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            tracked = root / "tracked.txt"
            tracked.write_text("base\n", encoding="utf-8")
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            commit = [
                "git", "-C", str(root), "-c", "user.name=Scenario User",
                "-c", "user.email=scenario@example.invalid", "commit", "--quiet", "-m",
            ]
            subprocess.run([*commit, "base"], check=True)
            base = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True,
                check=True,
                text=True,
            ).stdout.strip()
            subprocess.run(["git", "-C", str(root), "switch", "-q", "-c", "left"], check=True)
            tracked.write_text("left\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run([*commit, "left"], check=True)
            left = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True,
                check=True,
                text=True,
            ).stdout.strip()
            subprocess.run(["git", "-C", str(root), "switch", "-q", "-c", "right", base], check=True)
            tracked.write_text("right\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run([*commit, "right"], check=True)
            right = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "HEAD"],
                capture_output=True,
                check=True,
                text=True,
            ).stdout.strip()
            git_directory = Path(
                subprocess.run(
                    ["git", "-C", str(root), "rev-parse", "--absolute-git-dir"],
                    capture_output=True,
                    check=True,
                    text=True,
                ).stdout.strip()
            )
            subprocess.run(
                ["git", "-C", str(root), "config", "advice.graftFileDeprecated", "false"],
                check=True,
            )
            (git_directory / "info" / "grafts").write_text(
                f"{right} {left}\n",
                encoding="ascii",
            )
            with mock.patch.object(
                sys,
                "argv",
                ["check_branch_stack.py", "left", "right", "--project-root", str(root)],
            ), mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                exit_code = check_branch_stack.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(1, exit_code, payload)
        self.assertIn("graft path is present", payload["error"])

    def test_branch_stack_terminates_revision_options_before_user_refs(self) -> None:
        """A dash-prefixed ref is data, not another merge-base option."""

        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory, mock.patch.object(
            check_branch_stack,
            "effective_graft_error",
            return_value=None,
        ), mock.patch.object(
            check_branch_stack,
            "run",
            return_value=(1, "unknown revision"),
        ) as git_run, mock.patch.object(
            sys,
            "argv",
            [
                "check_branch_stack.py",
                "--project-root",
                directory,
                "--",
                "--synthetic-ref",
                "HEAD",
            ],
        ), mock.patch("sys.stdout", new_callable=io.StringIO):
            exit_code = check_branch_stack.main()

        self.assertEqual(1, exit_code)
        self.assertEqual("--", git_run.call_args.args[0][3])

    @unittest.skipUnless(os.name == "nt", "Windows command-wrapper semantics")
    def test_graphite_npm_wrapper_is_observation_only_on_windows(self) -> None:
        """A Windows npm wrapper failure cannot erase a valid Git ancestry receipt."""
        wrapper = str(Path(chr(67) + ":/") / "Program Files" / "nodejs" / "gt.CMD")
        command = check_branch_stack.graphite_command(wrapper)
        self.assertEqual(os.environ.get("COMSPEC"), command[0])
        self.assertEqual(["/d", "/s", "/c"], command[1:4])
        self.assertIn("gt.CMD", command[4])

        calls: list[list[str]] = []

        def observed_run(argv: list[str], root: Path) -> tuple[int, str]:
            calls.append(argv)
            if argv[0] == "git":
                return 0, ""
            raise FileNotFoundError("synthetic wrapper failure")

        with mock.patch.object(check_branch_stack.shutil, "which", return_value=wrapper), mock.patch.object(
            check_branch_stack, "graphite_initialized", return_value=True
        ), mock.patch.object(check_branch_stack, "run", side_effect=observed_run), mock.patch.object(
            sys,
            "argv",
            ["check_branch_stack.py", "HEAD^", "HEAD", "--observe-graphite"],
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            exit_code = check_branch_stack.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(0, exit_code)
        self.assertTrue(payload["ok"])
        self.assertEqual(
            {
                "requested": True,
                "available": True,
                "initialized": True,
                "ok": False,
                "error": "FileNotFoundError",
            },
            payload["graphite"],
        )
        self.assertEqual(2, len(calls))

    def test_graphite_status_never_initializes_a_fresh_repository(self) -> None:
        """Requesting optional stack status cannot create Graphite metadata in a new Git repository."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            tracked = root / "tracked.txt"
            tracked.write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(root), "-c", "user.name=Scenario User",
                    "-c", "user.email=scenario@example.invalid", "commit", "--quiet", "-m", "one",
                ],
                check=True,
            )
            tracked.write_text("two\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(root), "-c", "user.name=Scenario User",
                    "-c", "user.email=scenario@example.invalid", "commit", "--quiet", "-m", "two",
                ],
                check=True,
            )
            git_directory = Path(
                subprocess.run(
                    ["git", "-C", str(root), "rev-parse", "--absolute-git-dir"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
            )

            with mock.patch.object(check_branch_stack.shutil, "which", return_value="gt"):
                with mock.patch.object(
                    sys,
                    "argv",
                    [
                        "check_branch_stack.py",
                        "HEAD^",
                        "HEAD",
                        "--project-root",
                        str(root),
                        "--observe-graphite",
                    ],
                ), mock.patch("sys.stdout", new_callable=io.StringIO) as output:
                    exit_code = check_branch_stack.main()

            payload = json.loads(output.getvalue())
            self.assertEqual(0, exit_code)
            self.assertTrue(payload["ok"])
            self.assertEqual(
                {"requested": True, "available": True, "initialized": False},
                payload["graphite"],
            )
            self.assertEqual([], list(git_directory.glob(".graphite*")))

    def test_cross_host_guide_does_not_register_an_unrestricted_reverse_bridge(self) -> None:
        """A reviewer is not handed a write-capable Claude server as a read-only boundary."""
        guide = (ROOT / "docs" / "mcp-and-agent-bridges.md").read_text(encoding="utf-8")

        self.assertNotIn("codex mcp add claude-review -- claude mcp serve", guide)
        self.assertIn("/codex:status", guide)
        self.assertIn("/codex:result TASK_ID", guide)

    def test_remote_mcp_examples_are_copyable_without_committed_secrets(self) -> None:
        """A team can configure each host's remote transport without confusing scope."""

        guide = (ROOT / "docs/mcp-and-agent-bridges.md").read_text(encoding="utf-8")
        self.assertIn("`codex mcp add` writes the user's", guide)
        self.assertIn("--transport http --scope project", guide)
        self.assertIn("agent mcp login project-remote-token", guide)
        self.assertIn("agent mcp list", guide)
        self.assertIn("claude_desktop_config.json", guide)
        self.assertIn("claude mcp get", guide)
        self.assertIn("collision-free project IDs", guide)
        self.assertIn("--strict-mcp-config", guide)
        self.assertIn("cannot stop for the same prompt", guide)
        self.assertIn("desktop-only Codex lane", guide)
        self.assertIn("In Claude Code Desktop", guide)
        self.assertIn("Cursor desktop-only lane", guide)
        codex = tomllib.loads(
            (ROOT / "templates/codex/project.config.toml").read_text(encoding="utf-8")
        )
        self.assertEqual("[PYTHON_EXECUTABLE]", codex["mcp_servers"]["project_tools"]["command"])
        self.assertEqual(["-m", "[PROJECT_MCP_MODULE]"], codex["mcp_servers"]["project_tools"]["args"])
        self.assertEqual(
            "[ABSOLUTE_PROJECT_ROOT]",
            codex["mcp_servers"]["project_tools"]["cwd"],
        )
        self.assertFalse(codex["mcp_servers"]["project-remote"]["enabled"])
        self.assertEqual(
            "EXAMPLE_MCP_TOKEN",
            codex["mcp_servers"]["project-remote"]["bearer_token_env_var"],
        )
        claude = json.loads(
            (ROOT / "templates/project/.mcp.json.example").read_text(encoding="utf-8")
        )
        cursor = json.loads(
            (ROOT / "templates/cursor/mcp.json.example").read_text(encoding="utf-8")
        )
        self.assertEqual(
            ["${CLAUDE_PROJECT_DIR:-.}/[PROJECT_MCP_ENTRYPOINT]"],
            claude["mcpServers"]["[PROJECT_SLUG]-tools"]["args"],
        )
        self.assertEqual(
            ["${workspaceFolder}/[PROJECT_MCP_ENTRYPOINT]"],
            cursor["mcpServers"]["project-tools"]["args"],
        )
        self.assertIn("codex mcp login project-remote", guide)
        self.assertIn("mcp_optional_startup_grace_ms", guide)
        self.assertIn("open `/mcp`", guide)
        self.assertEqual(
            "Bearer ${EXAMPLE_MCP_TOKEN}",
            claude["mcpServers"]["[PROJECT_SLUG]-remote-token"]["headers"]["Authorization"],
        )
        self.assertEqual(
            "Bearer ${env:EXAMPLE_MCP_TOKEN}",
            cursor["mcpServers"]["project-remote-token"]["headers"]["Authorization"],
        )
        self.assertIn("does not bundle the reverse Codex-to-Claude MCP route", guide)
        self.assertIn("negative write/spawn scenarios", guide)

    def test_native_windows_codex_mcp_example_uses_parseable_toml_paths(self) -> None:
        """A Windows operator can paste the documented interpreter path without invalid escapes."""

        guide = (ROOT / "docs" / "mcp-and-agent-bridges.md").read_text(encoding="utf-8")
        self.assertIn(
            'command = "C:/Users/[WINDOWS_USER]/project/.venv/Scripts/python.exe"',
            guide,
        )
        self.assertIn('cwd = "C:/Users/[WINDOWS_USER]/project"', guide)
        parsed = tomllib.loads(
            "[mcp_servers.project_tools]\n"
            'command = "C:/Users/[WINDOWS_USER]/project/.venv/Scripts/python.exe"\n'
            'args = ["-m", "[PROJECT_MCP_MODULE]"]\n'
            'cwd = "C:/Users/[WINDOWS_USER]/project"\n'
            "enabled = false\n"
        )
        self.assertEqual(
            "C:/Users/[WINDOWS_USER]/project/.venv/Scripts/python.exe",
            parsed["mcp_servers"]["project_tools"]["command"],
        )

    def materialize_new_git_project(self, root: Path) -> None:
        """Exercise the documented CLI, not a second copy of its placement map."""
        subprocess.run(["git", "init", "--quiet", "--template=", str(root)], check=True, timeout=10)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as receipts:
            plan = Path(receipts) / "plan.json"
            for args in (
                ["plan", "--out", str(plan)],
                ["apply", "--plan", str(plan), "--all-missing", "--receipt", str(Path(receipts) / "progress.jsonl")],
            ):
                result = subprocess.run(
                    [sys.executable, "-B", str(ROOT / "scripts/setup_project.py"), *args, "--target", str(root)],
                    capture_output=True, text=True, timeout=60,
                )
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual("UNCONFIGURED", report["status"])
            self.assertFalse(report["activation"])

    def test_documented_bootstrap_stops_when_one_native_copy_is_missing(self) -> None:
        """A newcomer sees a missing native adapter after otherwise successful adoption."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            self.materialize_new_git_project(root)
            (root / ".cursor/mcp.json").unlink()
            completed = subprocess.run(
                [sys.executable, "-B", str(root / "scripts/setup_doctor.py"),
                 "--project-root", str(root), "--skip-binaries"],
                capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(2, completed.returncode, completed.stdout + completed.stderr)
            self.assertIn("MISSING: cursor .cursor/mcp.json", completed.stdout)
            setup = (ROOT / "docs/setup.md").read_text(encoding="utf-8")
            self.assertIn("set -eu", setup)
            self.assertIn("throw 'Setup diagnosis failed'", setup)

    def test_newcomer_gets_an_honest_no_gate_after_documented_materialization(self) -> None:
        """A newcomer cannot inherit the kit's green evidence as target-project proof."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            self.materialize_new_git_project(root)
            ignore = (root / ".gitignore").read_text(encoding="utf-8")
            self.assertIn(".claude/skills/", ignore)
            self.assertIn(".agent-local/", ignore)
            self.assertIn(".claude/settings.local.json", ignore)
            self.assertIn(".claude/worktrees/", ignore)
            self.assertIn("CLAUDE.local.md", ignore)
            self.assertIn("__pycache__/", ignore)
            self.assertIn("*.py[cod]", ignore)
            self.assertIn(".pytest_cache/", ignore)
            self.assertIn(".env.*", ignore)
            self.assertIn("!.env.example", ignore)
            invariants = (root / "AGENT_INVARIANTS.md").read_text(encoding="utf-8")
            self.assertEqual(22, sum(line[:1].isdigit() and ". **" in line for line in invariants.splitlines()))
            self.assertIn(
                "[portable invariants](AGENT_INVARIANTS.md)",
                (root / "AGENTS.md").read_text(encoding="utf-8"),
            )
            for relative in (
                "HANDOFF.md",
                "ARTIFACTS.md",
                "DECISIONS.md",
                "COMMUNICATION.md",
                "context-exchange/host-note.md",
                ".planning/placement.md",
                ".planning/generation-matrix.json",
            ):
                self.assertTrue((root / relative).is_file(), relative)

            doctor = setup_doctor.inspect_project(root, ("codex", "claude", "cursor"), True)
            setup_doctor.parse_configs(root, doctor)
            self.assertFalse([item for item in doctor if item["status"] != "present"])

            config = json.loads(
                (root / "templates" / "harness" / "preflight.json").read_text(encoding="utf-8")
            )
            report = agent_preflight.run_preflight(root, config)
            self.assertEqual("NO_GATE", report["status"], report)
            self.assertEqual({"files_read": 0, "bytes_read": 0}, report["observed"])
            self.assertTrue(all(item["status"] == "NO_GATE" for item in report["checks"]))
            runtime_statuses = {
                item["check"]: item["status"]
                for item in doctor
                if item["host"] == "runtime"
            }
            self.assertEqual(
                {"Git": "present", "Python >= 3.11": "present"}, runtime_statuses
            )
            for command in ("check", "demo"):
                learning = subprocess.run(
                    [sys.executable, "-B", "scripts/bootstrap_learning.py", command],
                    cwd=root, capture_output=True, text=True, timeout=15, check=False,
                )
                self.assertEqual(0, learning.returncode, learning.stdout + learning.stderr)
                result = json.loads(learning.stdout)
                if command == "demo":
                    self.assertEqual("NUMERICALLY_ELIGIBLE", result["verdict"])
                    self.assertTrue(result["synthetic"])
                    self.assertFalse(result["activated"])
                else:
                    self.assertEqual("VALID_SCAFFOLD", result["status"])
                    self.assertFalse(result["application_verified"])

    def test_each_host_adapter_parses_and_all_skills_have_discovery_metadata(self) -> None:
        """A maintainer can prove the distributed examples are parseable before copying them."""
        setup = (ROOT / "docs" / "setup.md").read_text(encoding="utf-8")
        self.assertIn("Get-Command py -ErrorAction Stop", setup)
        self.assertIn("$PythonPrefix = @('-3')", setup)
        self.assertGreaterEqual(setup.count("& $PythonExe @PythonPrefix"), 5)
        self.assertIn("installs the optional Cursor CLI (`agent`), not the", setup)
        self.assertIn("ChatGPT desktop app", setup)
        self.assertIn("choose Codex", setup)
        self.assertIn("choose WSL as the agent environment", setup)
        self.assertIn("restart ChatGPT", setup)
        self.assertIn("Claude Code Desktop", setup)
        self.assertIn("Choose **Local**", setup)
        self.assertIn("choose its WSL", setup)
        self.assertIn("https://code.claude.com/docs/en/desktop-quickstart", setup)
        self.assertIn("https://code.claude.com/docs/en/desktop-wsl", setup)
        self.assertIn("https://code.claude.com/docs/en/platforms", setup)
        self.assertIn("https://cursor.com/download", setup)
        self.assertIn("anysphere.remote-wsl", setup)
        self.assertIn("cursor .", setup)
        self.assertIn("WSL: [DISTRIBUTION]", setup)
        self.assertIn("\\\\wsl.localhost\\[DISTRIBUTION]", setup)
        self.assertIn("share config, auth, and sessions with WSL", setup)
        self.assertIn("command -v curl", setup)
        self.assertIn("command -v bash", setup)
        self.assertIn("Alpine or another musl-based Linux", setup)
        for package in ("`libgcc`", "`libstdc++`", "`ripgrep`"):
            self.assertIn(package, setup)
        self.assertIn('export PATH="$HOME/.local/bin:$PATH"', setup)
        self.assertIn("selected_commands='codex claude agent'", setup)
        self.assertIn("Close this PowerShell window and open a new terminal", setup)
        self.assertIn("cannot update the already-running parent process", setup)
        self.assertIn("codex login status", setup)
        self.assertIn("claude auth status", setup)
        self.assertIn("**Setting sources**", setup)
        self.assertIn("after using", setup)
        self.assertIn("agent status", setup)
        self.assertIn("read-only diagnostic", setup)
        self.assertNotIn("skips the workspace trust dialog and starts stdio servers", setup)
        self.assertIn("--hosts codex --skip-binaries", setup)
        self.assertIn('setup_project.py plan --target /path/to/project --out /path/to/review/setup-plan.json', setup)
        self.assertIn('--include AGENT_INVARIANTS.md --receipt /path/to/review/setup-progress.jsonl', setup)
        self.assertIn("templates/codex/config.toml", setup)
        self.assertIn("templates/claude/settings.local.json.example", setup)
        self.assertIn(".claude/settings.local.json", setup)
        self.assertFalse((ROOT / "CLAUDE.md").exists())
        self.assertFalse((ROOT / "templates/project/CLAUDE.md").exists())
        self.assertEqual(
            "@../AGENTS.md",
            (ROOT / ".claude/CLAUDE.md").read_text(encoding="utf-8").strip(),
        )
        self.assertEqual(
            "@../AGENTS.md",
            (ROOT / "templates/project/.claude/CLAUDE.md")
            .read_text(encoding="utf-8")
            .strip(),
        )
        self.assertTrue(
            (ROOT / "templates/project/.claude/rules/claude-code.md").is_file()
        )
        for host in ("codex", "cursor"):
            for name in ("evidence-worker", "adversarial-judge"):
                suffix = ".toml" if host == "codex" else ".md"
                agent_text = (
                    ROOT / "templates" / host / "agents" / f"{name}{suffix}"
                ).read_text(encoding="utf-8")
                self.assertIn("filesystem", agent_text.lower())
                self.assertIn("inherit", agent_text.lower())
                self.assertIn("MCP", agent_text)
                self.assertIn("effective tool list", agent_text)
        cursor_global = json.loads(
            (ROOT / "templates" / "cursor" / "cli-config.json.example").read_text(
                encoding="utf-8"
            )
        )
        cursor_project = json.loads(
            (ROOT / "templates" / "cursor" / "cli.json.example").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("allowlist", cursor_global["approvalMode"])
        self.assertEqual([], cursor_global["permissions"]["allow"])
        self.assertEqual([], cursor_project["permissions"]["allow"])
        self.assertEqual({"version", "permissions"}, set(cursor_project))
        for path in (ROOT / "templates").rglob("*"):
            if not path.is_file():
                continue
            if path.name.endswith((".json", ".json.example")) or ".snippet.json" in path.name:
                json.loads(path.read_text(encoding="utf-8"))
            elif path.suffix == ".toml":
                tomllib.loads(path.read_text(encoding="utf-8"))
        for name in ("evidence-worker.md", "adversarial-judge.md"):
            claude_agent = (ROOT / "templates" / "claude" / "agents" / name).read_text(
                encoding="utf-8"
            )
            self.assertIn("tools: Read, Glob, Grep", claude_agent)
            self.assertNotIn("Bash", claude_agent.split("---", 2)[1])
            self.assertNotIn("PowerShell", claude_agent.split("---", 2)[1])
        codex_hooks = json.loads(
            (ROOT / "templates" / "codex" / "hooks.json.example").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            "startup|resume|clear|compact",
            codex_hooks["hooks"]["SessionStart"][0]["matcher"],
        )
        claude_hooks = json.loads(
            (ROOT / "templates" / "claude" / "hooks.snippet.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            "startup|resume|clear|compact|fork",
            claude_hooks["hooks"]["SessionStart"][0]["matcher"],
        )
        for groups in claude_hooks["hooks"].values():
            for group in groups:
                for hook in group["hooks"]:
                    self.assertNotIn(" ", hook["command"])
                    launcher = copy.deepcopy(hook)
                    launcher["command"] = "py"
                    launcher["args"].insert(0, "-3")
                    self.assertEqual("py", launcher["command"])
                    self.assertEqual("-3", launcher["args"][0])
        for groups in codex_hooks["hooks"].values():
            for group in groups:
                for hook in group["hooks"]:
                    windows_command = hook["commandWindows"]
                    self.assertIn("git rev-parse --show-toplevel", windows_command)
                    self.assertIn("Set-Location -LiteralPath $r", windows_command)
                    self.assertIn("python scripts/self_review_hook.py", windows_command)
                    self.assertNotIn('"', windows_command)
                    self.assertNotIn("$(", windows_command)
        hook_guide = (ROOT / "docs" / "skills-plugins-hooks.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("filesystem-write restriction", hook_guide)
        self.assertIn("inherit every parent MCP tool", hook_guide)
        self.assertIn("open `/hooks`", hook_guide)
        self.assertIn("never put `py -3` in `command`", hook_guide)
        catalog = json.loads((ROOT / "sources" / "skills.json").read_text(encoding="utf-8"))
        skill_root = ROOT / catalog["canonical_root"]
        names = sorted(path.name for path in skill_root.iterdir() if path.is_dir())
        self.assertEqual(catalog["skills"], names)
        self.assertEqual(18, len(names))
        for name in names:
            skill = skill_root / name
            self.assertLess(len((skill / "SKILL.md").read_text(encoding="utf-8").splitlines()), 100)
            metadata = json.loads((skill / "agents" / "openai.yaml").read_text(encoding="utf-8"))
            self.assertIn(f"${name}", metadata["interface"]["default_prompt"])
            contract = json.loads(
                (skill / "references" / "contract.json").read_text(encoding="utf-8")
            )
            self.assertEqual(name, contract["skill"])
            self.assertEqual([], validate_skill_receipt.validate_contract(contract))
            receipt = {
                "skill": name,
                "status": "PASS",
                "inputs": {
                    input_name: f"scenario:{input_name}"
                    for input_name in contract["inputs"]
                },
                "evidence": ["scenario:representative-observation"],
                "verification": "Scenario replay exited 0.",
            }
            self.assertEqual([], validate_skill_receipt.validate_receipt(contract, receipt))

        scaffold = ROOT / "templates" / "skill"
        scaffold_contract = json.loads(
            (scaffold / "references" / "contract.json").read_text(encoding="utf-8")
        )
        scaffold_metadata = json.loads(
            (scaffold / "agents" / "openai.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual([], validate_skill_receipt.validate_contract(scaffold_contract))
        self.assertIn(
            "$example-proof",
            scaffold_metadata["interface"]["default_prompt"],
        )
        scaffold_text = (scaffold / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("references/contract.json", scaffold_text)
        self.assertIn("parameterized `verification.argv`", scaffold_text)

    def test_personal_contract_has_synced_and_local_cursor_destinations(self) -> None:
        """A solo developer can choose account-synced or machine-local Cursor guidance."""

        setup = (ROOT / "docs" / "setup.md").read_text(encoding="utf-8")
        personal = (ROOT / "templates" / "global" / "WORKING_AGREEMENTS.md").read_text(
            encoding="utf-8"
        )
        for expected in (
            "~/.codex/AGENTS.md",
            "~/.claude/CLAUDE.md",
            "Customize → Rules → User Rules",
            "~/.cursor/rules/working-agreements.mdc",
            "%USERPROFILE%\\.cursor\\rules\\working-agreements.mdc",
            "non-synced",
            "Agent (Chat)",
            "not Tab or Inline Edit",
        ):
            self.assertIn(expected, setup + personal)
        cursor_rule = (ROOT / "templates/cursor/working-agreements.mdc").read_text(
            encoding="utf-8"
        )
        self.assertTrue(cursor_rule.startswith("---\ndescription:"))
        self.assertIn("alwaysApply: true", cursor_rule)
        self.assertIn("## Modes", cursor_rule)

    @unittest.skipUnless(os.name == "nt", "Codex commandWindows runs only on Windows")
    def test_codex_windows_hook_resolves_a_metachar_git_root_from_a_nested_directory(self) -> None:
        """A Windows user can start below a metacharacter-bearing root without losing hooks."""

        with tempfile.TemporaryDirectory(dir=TEMP_ROOT, prefix="hook repo & ") as directory:
            target = Path(directory) / "project with spaces & marker"
            script_directory = target / "scripts"
            nested = target / "docs" / "nested"
            script_directory.mkdir(parents=True)
            nested.mkdir(parents=True)
            shutil.copy2(ROOT / "scripts" / "self_review_hook.py", script_directory)
            shutil.copy2(ROOT / "scripts" / "path_safety.py", script_directory)
            shutil.copy2(ROOT / "scripts" / "bounded_process.py", script_directory)
            subprocess.run(
                ["git", "init", "--quiet", str(target)],
                check=True,
                capture_output=True,
                text=True,
            )
            hooks = json.loads(
                (ROOT / "templates" / "codex" / "hooks.json.example").read_text(
                    encoding="utf-8"
                )
            )
            command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["commandWindows"]

            completed = subprocess.run(
                [os.environ.get("COMSPEC", "cmd.exe"), "/C", command],
                cwd=nested,
                input="{}",
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(0, completed.returncode, completed.stderr)
            output = json.loads(completed.stdout)
            self.assertEqual(
                "SessionStart", output["hookSpecificOutput"]["hookEventName"]
            )

    def test_skill_operator_can_validate_a_receipt_and_detect_a_missing_field(self) -> None:
        """A skill operator gets executable proof instead of trusting prose completion."""
        skill = ROOT / "templates" / "project" / ".agents" / "skills" / "refresh-handoff"
        contract_path = skill / "references" / "contract.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        receipt = {
            "skill": contract["skill"],
            "status": "PASS",
            "inputs": {name: f"fixture:{name}" for name in contract["inputs"]},
            "evidence": ["fixture:handoff-replay"],
            "verification": "The handoff scenario replay exited 0.",
        }
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            receipt_path = Path(directory) / "receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            advertised_argv = [
                token.replace("{python}", sys.executable)
                .replace("{skill_dir}", str(skill))
                .replace("{receipt}", str(receipt_path))
                for token in contract["verification"]["argv"]
            ]
            valid = subprocess.run(
                advertised_argv,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(0, valid.returncode, valid.stdout + valid.stderr)

            del receipt["evidence"]
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            invalid = subprocess.run(
                advertised_argv,
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            self.assertEqual(1, invalid.returncode)
            self.assertIn("canonical five fields", invalid.stdout)

    def test_claim_checker_requires_a_receipt_next_to_completion_language(self) -> None:
        """A reviewer sees unsupported delivery language before it reaches a handoff."""
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            path = Path(directory) / "HANDOFF.md"
            path.write_text("The migration is complete.\n", encoding="utf-8")
            self.assertTrue(check_claim_language.check(path))
            path.write_text("The migration is complete. Evidence: replay command passed.\n", encoding="utf-8")
            self.assertEqual([], check_claim_language.check(path))


if __name__ == "__main__":
    unittest.main()
