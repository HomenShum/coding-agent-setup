from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_private_history  # noqa: E402


class ReachableHistoryScenarios(unittest.TestCase):
    marker = "violet7"
    rules = ((len(marker), hashlib.sha256(marker.encode("utf-8")).hexdigest()),)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "--quiet", str(self.root)], check=True)
        sources = self.root / "sources"
        sources.mkdir()
        policy = {
            "algorithm": "sha256-lower-nfkc",
            "markers": [{"length": self.rules[0][0], "digest": self.rules[0][1]}],
        }
        (sources / "private-marker-hashes.json").write_text(
            json.dumps(policy), encoding="utf-8"
        )
        (self.root / "public.txt").write_text("clean baseline\n", encoding="utf-8")
        self.commit("clean baseline")

    def commit(self, message: str) -> None:
        subprocess.run(["git", "-C", str(self.root), "add", "--all"], check=True)
        subprocess.run(
            [
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
                message,
            ],
            capture_output=True,
            text=True,
            check=True,
        )

    def test_deleted_private_marker_still_blocks_publication_without_echoing_it(self) -> None:
        """A maintainer cannot erase a sensitive term from the tip while leaving its blob reachable."""

        (self.root / "public.txt").write_text(
            f"temporary {self.marker} content\n", encoding="utf-8"
        )
        self.commit("temporary content")
        (self.root / "public.txt").write_text("clean current content\n", encoding="utf-8")
        self.commit("remove temporary content")

        errors = check_private_history.validate_reachable_history(self.root, self.rules)

        self.assertTrue(any("reachable history object" in error for error in errors), errors)
        self.assertNotIn(self.marker, "\n".join(errors).lower())

    def test_same_blob_alias_cannot_hide_a_private_historical_filename(self) -> None:
        """A reused safe blob cannot make Git's deduplicated object display hide a later path."""

        shared_content = "identical public bytes\n"
        (self.root / "a-safe.txt").write_text(shared_content, encoding="utf-8")
        self.commit("add safe alias source")
        private_alias = self.root / f"z-{self.marker}.txt"
        private_alias.write_text(shared_content, encoding="utf-8")
        self.commit("add second alias")
        private_alias.unlink()
        self.commit("remove second alias")

        errors = check_private_history.validate_reachable_history(self.root, self.rules)

        self.assertTrue(any("reachable history path" in error for error in errors), errors)
        self.assertNotIn(self.marker, "\n".join(errors).lower())

    def test_merge_only_same_blob_alias_cannot_hide_a_historical_filename(self) -> None:
        """A filename added and removed only by merge resolutions remains in path proof."""

        shared_content = "identical public bytes\n"
        (self.root / "a-safe.txt").write_text(shared_content, encoding="utf-8")
        self.commit("add safe alias source")
        primary_branch = subprocess.run(
            ["git", "-C", str(self.root), "branch", "--show-current"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
        self.assertTrue(primary_branch)
        subprocess.run(
            ["git", "-C", str(self.root), "branch", "alias-side"], check=True
        )
        (self.root / "main-one.txt").write_text("main one\n", encoding="utf-8")
        self.commit("main one")
        subprocess.run(
            ["git", "-C", str(self.root), "checkout", "--quiet", "alias-side"],
            check=True,
        )
        (self.root / "side-one.txt").write_text("side one\n", encoding="utf-8")
        self.commit("side one")
        subprocess.run(
            ["git", "-C", str(self.root), "checkout", "--quiet", primary_branch],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "-c",
                "user.name=Scenario User",
                "-c",
                "user.email=scenario@example.invalid",
                "merge",
                "--no-ff",
                "--no-commit",
                "alias-side",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        private_alias = self.root / f"z-{self.marker}.txt"
        private_alias.write_text(shared_content, encoding="utf-8")
        self.commit("merge with alias resolution")

        subprocess.run(
            ["git", "-C", str(self.root), "branch", "removal-side"], check=True
        )
        (self.root / "main-two.txt").write_text("main two\n", encoding="utf-8")
        self.commit("main two")
        subprocess.run(
            ["git", "-C", str(self.root), "checkout", "--quiet", "removal-side"],
            check=True,
        )
        (self.root / "side-two.txt").write_text("side two\n", encoding="utf-8")
        self.commit("side two")
        subprocess.run(
            ["git", "-C", str(self.root), "checkout", "--quiet", primary_branch],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "-c",
                "user.name=Scenario User",
                "-c",
                "user.email=scenario@example.invalid",
                "merge",
                "--no-ff",
                "--no-commit",
                "removal-side",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        private_alias.unlink()
        self.commit("merge without alias resolution")

        errors = check_private_history.validate_reachable_history(self.root, self.rules)

        self.assertTrue(any("reachable history path" in error for error in errors), errors)
        self.assertNotIn(self.marker, "\n".join(errors).lower())

    def test_clean_history_passes_with_deterministic_budgets(self) -> None:
        """A small clean repository can produce a repeatable zero-error history receipt."""

        first = check_private_history.validate_reachable_history(self.root, self.rules)
        second = check_private_history.validate_reachable_history(self.root, self.rules)

        self.assertEqual([], first)
        self.assertEqual(first, second)

    def test_replace_refs_cannot_hide_a_reachable_private_object(self) -> None:
        """A local replacement ref cannot substitute clean history for the scanned object."""

        (self.root / "public.txt").write_text(
            f"temporary {self.marker} content\n",
            encoding="utf-8",
        )
        self.commit("temporary content")
        marked_commit = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
        (self.root / "public.txt").write_text("clean replacement\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "public.txt"], check=True)
        clean_tree = subprocess.run(
            ["git", "-C", str(self.root), "write-tree"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
        clean_commit = subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "-c",
                "user.name=Scenario User",
                "-c",
                "user.email=scenario@example.invalid",
                "commit-tree",
                clean_tree,
            ],
            input="clean replacement\n",
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "-C", str(self.root), "replace", marked_commit, clean_commit],
            check=True,
        )

        with mock.patch.dict(
            "os.environ",
            {"GIT_NO_REPLACE_OBJECTS": "0", "GIT_DIR": str(self.root / "elsewhere")},
            clear=False,
        ):
            errors = check_private_history.validate_reachable_history(
                self.root,
                self.rules,
            )

        self.assertTrue(any("reachable history object" in error for error in errors), errors)
        self.assertNotIn(self.marker, "\n".join(errors).lower())

    def test_suppressed_legacy_graft_cannot_hide_a_reachable_private_parent(self) -> None:
        """A local graft cannot remove a marked parent from a release owner's proof."""

        (self.root / "public.txt").write_text(
            f"temporary {self.marker} content\n",
            encoding="utf-8",
        )
        self.commit("temporary content")
        (self.root / "public.txt").write_text("clean current content\n", encoding="utf-8")
        self.commit("remove temporary content")
        head = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout.strip()
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

        errors = check_private_history.validate_reachable_history(self.root, self.rules)

        self.assertTrue(any("graft path is present" in error for error in errors), errors)
        self.assertNotIn(self.marker, "\n".join(errors).lower())

    def test_cli_loads_the_shipped_policy_algorithm_before_scanning(self) -> None:
        """A release run proves policy parsing and history traversal as one integration path."""
        with mock.patch.object(
            sys,
            "argv",
            ["check_private_history.py", "--root", str(self.root)],
        ), mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            exit_code = check_private_history.main()

        self.assertEqual(0, exit_code, output.getvalue())
        self.assertIn("PASS: bounded reachable-history marker validation", output.getvalue())

    def test_shallow_checkout_cannot_claim_complete_reachable_history(self) -> None:
        """A release worker cannot certify history from a clone that omitted older objects."""

        (self.root / "public.txt").write_text("second clean version\n", encoding="utf-8")
        self.commit("second clean commit")
        with tempfile.TemporaryDirectory() as clone_directory:
            shallow = Path(clone_directory) / "shallow"
            subprocess.run(
                ["git", "clone", "--quiet", "--depth", "1", self.root.as_uri(), str(shallow)],
                check=True,
            )
            errors = check_private_history.validate_reachable_history(shallow, self.rules)

        self.assertEqual(["reachable-history gate refuses a shallow checkout"], errors)

    def test_ref_commit_path_and_blob_growth_each_fail_at_their_named_cap(self) -> None:
        """A hostile repository cannot turn history proof into unbounded inventory work."""

        subprocess.run(["git", "-C", str(self.root), "branch", "second-ref"], check=True)
        with mock.patch.object(check_private_history, "MAX_HISTORY_REFS", 1):
            ref_errors = check_private_history.validate_reachable_history(self.root, self.rules)
        self.assertTrue(any("ref cap exceeded" in error for error in ref_errors), ref_errors)

        (self.root / "public.txt").write_text("second clean version\n", encoding="utf-8")
        self.commit("second clean commit")
        with mock.patch.object(check_private_history, "MAX_HISTORY_COMMITS", 1):
            commit_errors = check_private_history.validate_reachable_history(
                self.root, self.rules
            )
        self.assertTrue(
            any("commit cap exceeded" in error for error in commit_errors), commit_errors
        )

        with mock.patch.object(check_private_history, "MAX_HISTORY_PATHS", 1):
            path_errors = check_private_history.validate_reachable_history(self.root, self.rules)
        self.assertTrue(any("path cap exceeded" in error for error in path_errors), path_errors)

        with mock.patch.object(check_private_history, "MAX_HISTORY_BLOBS", 1):
            blob_errors = check_private_history.validate_reachable_history(self.root, self.rules)
        self.assertTrue(any("blob cap exceeded" in error for error in blob_errors), blob_errors)

    def test_large_historical_object_fails_closed_instead_of_partial_scanning(self) -> None:
        """A large old artifact cannot be silently truncated into an apparently clean scan."""

        (self.root / "large.txt").write_text("clean-value\n", encoding="utf-8")
        self.commit("large bounded fixture")
        with mock.patch.object(check_private_history, "MAX_HISTORY_OBJECT_BYTES", 8):
            errors = check_private_history.validate_reachable_history(self.root, self.rules)

        self.assertTrue(any("object exceeds" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
