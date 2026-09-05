"""A release maintainer can inspect cumulative revisions without hiding old content."""
from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_private_history as history


class CumulativeHistoryScenarios(unittest.TestCase):
    marker = "violet7"
    rules = ((len(marker), hashlib.sha256(marker.encode()).hexdigest()),)

    def setUp(self):
        # Resolve OS temporary-directory aliases; linked-path tests own link fixtures.
        self.temporary = tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve())
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "--quiet")

    def git(self, *arguments):
        return subprocess.run(
            ["git", "-C", str(self.root), *arguments], check=True,
            capture_output=True, timeout=10,
        ).stdout

    def commit_revision(self, revision, suffix=""):
        # Four distinct versions each fit the per-value budget, but their total
        # candidate work exceeds the clean-tree budget without exceeding byte caps.
        content = "publiccomponentrequirements" * 13_000 + f"revision{revision}" + suffix
        (self.root / "guide.txt").write_text(content, encoding="utf-8")
        self.git("add", "guide.txt")
        self.git("-c", "user.name=Scenario User", "-c",
                 "user.email=scenario@example.invalid", "commit", "--quiet",
                 "-m", f"Document revision {revision}")

    def test_maintainer_can_review_clean_cumulative_revisions_without_a_partial_scan(self):
        for revision in range(4):
            self.commit_revision(revision)
        before = self.git("rev-list", "--objects", "--all")
        self.assertEqual([], history.validate_reachable_history(self.root, self.rules))
        self.assertEqual(before, self.git("rev-list", "--objects", "--all"))
        self.assertEqual(b"", self.git("status", "--porcelain"))

    def test_maintainer_cannot_hide_a_late_obfuscated_marker_by_removing_it_at_the_tip(self):
        for revision in range(4):
            self.commit_revision(revision)
        # The sensitive value occurs only at the end of a substantial old blob.
        full_width = [chr(ord(character) + 0xFEE0) for character in self.marker.upper()]
        self.commit_revision(4, ".".join(full_width))
        self.commit_revision(5)
        errors = history.validate_reachable_history(self.root, self.rules)
        self.assertTrue(any("reachable history object" in error for error in errors), errors)
        self.assertFalse(any("window budget" in error for error in errors), errors)
        self.assertNotIn(self.marker, "\n".join(errors).lower())
        self.assertEqual(b"", self.git("status", "--porcelain"))

    def test_hostile_single_values_and_aggregate_growth_still_fail_closed(self):
        self.commit_revision(0)
        with mock.patch.object(history, "MAX_PRIVATE_MARKER_WINDOWS", 128):
            errors = history.validate_reachable_history(self.root, self.rules)
        self.assertTrue(any("window budget" in error for error in errors), errors)
        with mock.patch.object(history, "MAX_HISTORY_TOTAL_BYTES", 128):
            errors = history.validate_reachable_history(self.root, self.rules)
        self.assertTrue(any("byte cap exceeded" in error for error in errors), errors)
        with mock.patch.object(history, "MAX_HISTORY_SECONDS", 0):
            errors = history.validate_reachable_history(self.root, self.rules)
        self.assertTrue(any("aggregate budget" in error for error in errors), errors)

    def test_cpu_scan_cannot_report_success_after_the_aggregate_deadline(self):
        with mock.patch.object(history.time, "monotonic", side_effect=[9.0, 11.0]):
            with self.assertRaises(subprocess.TimeoutExpired):
                history._scan_text("public", self.rules, 10.0)
        with self.assertRaises(subprocess.TimeoutExpired):
            history._scan_text("public", self.rules, time.monotonic() - 1)


if __name__ == "__main__":
    unittest.main()
