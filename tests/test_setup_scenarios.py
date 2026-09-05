from __future__ import annotations

import shutil
import tempfile
import threading
import time
from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
# Physical fixture paths keep OS aliases outside link-rejection scenarios.
TEMP_ROOT = Path(tempfile.gettempdir()).resolve(strict=True)
sys.path.insert(0, str(ROOT / "scripts"))

import validate_repo  # noqa: E402


class SetupPublicationScenarios(unittest.TestCase):
    def copy_repository(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        target = Path(temporary.name) / "repo"
        shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        return temporary, target

    def test_newcomer_can_validate_a_fresh_clone_offline(self) -> None:
        """A newcomer needs deterministic proof before adding any credentials."""
        self.assertEqual([], validate_repo.validate_repo(ROOT))

    def test_publisher_is_stopped_by_a_secret_or_broken_link(self) -> None:
        """A maintainer cannot publish a copied token or a dead local handoff."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        token = "sk-" + ("A" * 32)
        (target / "accidental.txt").write_text(token, encoding="utf-8")
        with (target / "README.md").open("a", encoding="utf-8") as stream:
            stream.write("\n[missing handoff](docs/does-not-exist.md)\n")
        errors = validate_repo.validate_repo(target)
        self.assertTrue(any("OpenAI-style token" in error for error in errors))
        self.assertTrue(any("broken local link" in error for error in errors))

    def test_publisher_is_stopped_by_a_private_key_in_an_unusual_extension(self) -> None:
        """A publisher cannot hide a credential outside the old text allowlist."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        marker = "-----BEGIN " + "PRIVATE KEY-----\nsynthetic-test-only\n"
        (target / "leaked-key.pem").write_text(marker, encoding="utf-8")
        errors = validate_repo.validate_repo(target)
        self.assertTrue(any("possible private key" in error for error in errors))

    def test_publisher_is_stopped_by_drive_root_and_unc_machine_paths(self) -> None:
        """A public guide cannot retain workstation-specific Windows locations."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        slash = chr(92)
        drive_path = f"D:{slash}Private{slash}project"
        unc_path = f"{slash}{slash}server{slash}Alice{slash}secret"
        (target / "machine-note.txt").write_text(
            f"drive={drive_path}\nshare={unc_path}\n",
            encoding="utf-8",
        )

        errors = validate_repo.validate_repo(target)

        path_errors = [error for error in errors if "personal absolute path" in error]
        self.assertGreaterEqual(len(path_errors), 2)

    def test_documented_windows_placeholders_remain_publication_safe(self) -> None:
        """Generic setup placeholders stay usable while concrete machine roots are blocked."""
        slash = chr(92)
        content = (
            f"C:{slash}path{slash}to{slash}kit\n"
            f"{slash}{slash}server{slash}share{slash}project\n"
            "C:/Users/[WINDOWS_USER]/project\n"
            "/Users/[WINDOWS_USER]/project\n"
            f"{slash}{slash}wsl.localhost{slash}[DISTRIBUTION]{slash}project\n"
        )
        self.assertFalse(
            any(pattern.search(content) for pattern in validate_repo.PERSONAL_PATH_PATTERNS)
        )

    def test_reviewer_is_stopped_by_an_unattributed_repository(self) -> None:
        """A reviewer needs the source and license before accepting borrowed work."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        with (target / "README.md").open("a", encoding="utf-8") as stream:
            stream.write("\nhttps://" + "github.com/example/unattributed-tool\n")
        errors = validate_repo.validate_repo(target)
        self.assertTrue(any("uncatalogued GitHub repository" in error for error in errors))

    def test_release_engineer_is_stopped_by_an_unattributed_action(self) -> None:
        """A release engineer needs every executable CI dependency in the ledger."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        workflow = target / ".github" / "workflows" / "unattributed.yml"
        workflow.write_text(
            "name: Unattributed\njobs:\n  check:\n    steps:\n      - uses: "
            + "example/unattributed-action@v1\n",
            encoding="utf-8",
        )
        errors = validate_repo.validate_repo(target)
        self.assertTrue(any("uncatalogued GitHub repository" in error for error in errors))

    def test_reader_is_stopped_when_machine_and_human_ledgers_diverge(self) -> None:
        """A reader must see every machine-catalogued project in the human ledger."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        ledger = target / "docs" / "external-projects.md"
        content = ledger.read_text(encoding="utf-8")
        ledger.write_text(
            content.replace(
                "https://github.com/actions/checkout",
                "https://example.invalid/actions/checkout",
            ),
            encoding="utf-8",
        )
        errors = validate_repo.validate_repo(target)
        self.assertTrue(any("missing from human ledger" in error for error in errors))

    def test_burst_link_check_is_bounded_and_deterministic(self) -> None:
        """A release job may check many sources without spawning unbounded work."""
        active = 0
        peak = 0
        lock = threading.Lock()

        def observed_fetch(url: str) -> tuple[bool, str]:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return True, "observed"

        base = "https://" + "github.com/example/"
        urls = [f"{base}repo-{index:02d}" for index in range(24)]
        first = validate_repo.check_external_urls(reversed(urls), observed_fetch)
        second = validate_repo.check_external_urls(urls, lambda _: (True, "observed"))
        self.assertLessEqual(peak, validate_repo.MAX_WORKERS)
        self.assertEqual(first, second)

    def test_degraded_source_is_reported_as_failure(self) -> None:
        """A researcher must see a timeout instead of a false successful citation check."""
        results = validate_repo.check_external_urls(
            ["https://" + "github.com/example/degraded"],
            lambda _: (False, "TimeoutError: budget exhausted"),
        )
        self.assertEqual([(results[0][0], False, "TimeoutError: budget exhausted")], results)

    def test_sustained_checks_do_not_accumulate_state_and_caps_are_honest(self) -> None:
        """A scheduled runner must stay stable over repeated maximum-size scans."""
        base = "https://" + "github.com/example/"
        urls = [
            f"{base}repo-{index:03d}"
            for index in range(validate_repo.MAX_EXTERNAL_URLS)
        ]
        expected = validate_repo.check_external_urls(urls, lambda _: (True, "ok"))
        repeated = validate_repo.check_external_urls(urls, lambda _: (True, "ok"))
        self.assertEqual(expected, repeated)
        with self.assertRaisesRegex(ValueError, "cap exceeded"):
            validate_repo.check_external_urls(urls + [base + "overflow"])

    def test_large_publication_tree_stops_once_at_a_bounded_file_cap(self) -> None:
        """A publisher gets one controlled failure under sustained file accumulation."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        overflow = target / "overflow"
        overflow.mkdir()
        for index in range(validate_repo.MAX_PUBLIC_FILES + 1):
            (overflow / f"receipt-{index:04d}.txt").write_text("bounded\n", encoding="utf-8")
        errors = validate_repo.validate_repo(target)
        cap_errors = [error for error in errors if "public file cap exceeded" in error]
        self.assertEqual(1, len(cap_errors))
        self.assertLessEqual(len(errors), validate_repo.MAX_VALIDATION_ERRORS)

    def test_large_publication_content_stops_once_at_a_total_byte_cap(self) -> None:
        """A publisher cannot make bounded individual files accumulate without a total cap."""
        temporary, target = self.copy_repository()
        self.addCleanup(temporary.cleanup)
        (target / "bounded-a.txt").write_text("a" * 60, encoding="utf-8")
        (target / "bounded-b.txt").write_text("b" * 60, encoding="utf-8")
        discovery_errors = validate_repo.BoundedErrors()
        discovered = validate_repo.collect_public_files(target, discovery_errors)
        self.assertEqual([], discovery_errors)
        observed_total = sum(path.stat().st_size for path in discovered)

        with mock.patch.object(validate_repo, "MAX_PUBLIC_TOTAL_BYTES", observed_total - 1):
            errors = validate_repo.validate_repo(target)

        cap_errors = [error for error in errors if "public byte cap exceeded" in error]
        self.assertEqual(1, len(cap_errors))

    def test_disappearing_file_is_a_controlled_read_failure(self) -> None:
        """A concurrent cleanup cannot turn validation into an uncaught traceback."""
        original_read = validate_repo.read_text

        def disappearing_read(path: Path) -> str:
            if path.name == "README.md":
                raise OSError("synthetic concurrent removal")
            return original_read(path)

        with mock.patch.object(validate_repo, "read_text", side_effect=disappearing_read):
            errors = validate_repo.validate_repo(ROOT)
        self.assertTrue(any("cannot read public file" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
