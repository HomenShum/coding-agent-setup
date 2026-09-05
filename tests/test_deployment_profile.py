"""Customer platform owners cannot turn region labels or missing evidence into approval."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import html
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import deployment_profile as deployment


class CustomerDeploymentScenarios(unittest.TestCase):
    def setUp(self):
        self.profile = deployment.read_profile(deployment.ROOT / "templates/harness/deployment-profile.json")

    def resolved(self, owner="customer"):
        profile = copy.deepcopy(self.profile)
        profile["deployment"]["owner"] = owner
        profile["deployment"].update(delivery_mode="binary", customer_admin_visibility="full")
        for key in ("deployment", "policy", *deployment.SURFACE_KEYS):
            profile[key]["evidence"] = {
                "reference": "synthetic-review-manifest:" + key,
                "sha256": hashlib.sha256(key.encode()).hexdigest(),
                "reviewed_on": "2026-09-05", "reviewer_role": "synthetic-reviewer",
            }
        profile["model_processing"].update(provider="synthetic-provider", model="synthetic-model-v1",
            regions=["KR"], cross_region_inference=False, fallback_enabled=False)
        profile["operations"]["support_access_enabled"] = False
        profile["ip"]["legal_review"] = "reviewed"
        return profile

    def test_customer_keeps_unresolved_model_support_and_legal_questions_open(self):
        report = deployment.assess(self.profile)
        self.assertEqual("NO_GATE", report["verdict"])
        self.assertTrue(any("model_processing" in row for row in report["unresolved"]))
        self.assertTrue(any("support_access" in row for row in report["unresolved"]))
        self.assertTrue(any("legal" in row for row in report["unresolved"]))
        for owner in ("customer", "vendor"):
            profile = self.resolved(owner)
            consistent = deployment.assess(profile)
            self.assertEqual("PROFILE_CONSISTENT", consistent["verdict"])
            self.assertFalse(consistent["deployment_authorized"])
            self.assertFalse(consistent["compliance_approved"])
            self.assertTrue(consistent["synthetic"])
            for surface in ("deployment", "policy", *deployment.SURFACE_KEYS):
                missing = copy.deepcopy(profile)
                missing[surface]["evidence"] = None
                self.assertEqual("NO_GATE", deployment.assess(missing)["verdict"], surface)

    def test_customer_rejects_hidden_transfers_despite_unresolved_other_evidence(self):
        for surface, key in (("model_processing", "cross_region_inference"),
                             ("model_processing", "fallback_enabled"),
                             ("trace_eval", "trace_export_enabled"),
                             ("trace_eval", "customer_content_global_eval"),
                             ("operations", "support_access_enabled"),
                             ("operations", "network_egress_enabled")):
            profile = copy.deepcopy(self.profile)
            profile[surface][key] = True
            with self.subTest(surface=surface, key=key):
                result = deployment.assess(profile)
                self.assertEqual("REJECT", result["verdict"])
                self.assertGreater(len(result["unresolved"]), 0)
                self.assertEqual(1, len(result["violations"]))
        for surface, key in (("storage", "regions"), ("model_processing", "regions"),
                             ("trace_eval", "trace_regions"), ("trace_eval", "eval_regions"),
                             ("operations", "operator_regions")):
            profile = self.resolved()
            profile[surface][key] = ["KR", "outside-customer-scope"]
            self.assertEqual("REJECT", deployment.assess(profile)["verdict"])
        profile = self.resolved()
        profile["deployment"]["application_region"] = "outside-customer-scope"
        self.assertEqual("REJECT", deployment.assess(profile)["verdict"])
        profile = self.resolved()
        profile["ip"]["legal_review"] = "rejected"
        self.assertEqual("REJECT", deployment.assess(profile)["verdict"])

    def test_operator_cannot_smuggle_ambiguous_flags_regions_or_evidence(self):
        mutations = [
            ("operations", "network_egress_enabled", 0),
            ("operations", "support_access_enabled", "false"),
            ("model_processing", "regions", []),
            ("model_processing", "regions", ["KR", "KR"]),
            ("storage", "owner", "unreviewed-owner"),
            ("policy", "allow_model_fallback", None),
            ("policy", "storage_regions", ["KR"] * 33),
            ("ip", "legal_review", True),
        ]
        for surface, key, value in mutations:
            profile = self.resolved()
            profile[surface][key] = value
            with self.subTest(surface=surface, key=key), self.assertRaises(ValueError):
                deployment.assess(profile)
        for key, value in (("reference", ""), ("sha256", "not-a-digest"),
                           ("reviewed_on", "2026-02-31"), ("reviewer_role", "x" * 2001)):
            profile = self.resolved()
            profile["storage"]["evidence"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                deployment.assess(profile)
        profile = self.resolved()
        profile["model_processing"]["fallback_override"] = "allow"
        with self.assertRaises(ValueError):
            deployment.assess(profile)

    def test_customer_retains_exact_egress_and_delivery_choices_instead_of_a_generic_switch(self):
        profile = self.resolved()
        endpoint = "https://model-gateway.example.invalid/v1/inference"
        profile["policy"].update(allow_network_egress=True, allowed_egress_endpoints=[endpoint])
        profile["operations"].update(network_egress_enabled=True, egress_endpoints=[endpoint])
        self.assertEqual("PROFILE_CONSISTENT", deployment.assess(profile)["verdict"])
        for unauthorized in (endpoint + "/another-model", "https://tracing.example.invalid/v1/inference"):
            changed = copy.deepcopy(profile)
            changed["operations"]["egress_endpoints"] = [unauthorized]
            self.assertEqual("REJECT", deployment.assess(changed)["verdict"])
        changed = copy.deepcopy(profile)
        changed["operations"]["network_egress_enabled"] = False
        self.assertEqual("REJECT", deployment.assess(changed)["verdict"])
        for invalid in ("https://*.example.invalid/v1", "https://user:credential@example.invalid/v1",
                        endpoint + "?credential=not-a-real-secret", endpoint + "#fragment", "http://example.invalid"):
            changed = copy.deepcopy(profile)
            changed["policy"]["allowed_egress_endpoints"] = [invalid]
            with self.subTest(endpoint=invalid), self.assertRaises(ValueError):
                deployment.assess(changed)
        for key, value in (("delivery_mode", "source"), ("customer_admin_visibility", "none")):
            changed = copy.deepcopy(profile)
            changed["deployment"][key] = value
            self.assertEqual("REJECT", deployment.assess(changed)["verdict"])
            changed["deployment"][key] = None
            self.assertEqual("NO_GATE", deployment.assess(changed)["verdict"])
        profile["operations"]["egress_endpoints"] = None
        self.assertEqual("NO_GATE", deployment.assess(profile)["verdict"])

    def test_reviewer_sees_identical_safe_profile_in_html_ascii_and_json(self):
        profile = self.resolved()
        profile["deployment"]["customer_scope"] = '<script>alert("untrusted")</script> & scope'
        result = deployment.assess(profile)
        encoded = deployment.render(profile, result, "json")
        ascii_report = deployment.render(profile, result, "ascii")
        html_report = deployment.render(profile, result, "html")
        self.assertTrue(ascii_report.endswith(encoded))
        visible_json = html.unescape(html_report.split("<pre>", 1)[1].split("</pre>", 1)[0])
        self.assertEqual(encoded, visible_json)
        self.assertNotIn("<script>", html_report)
        self.assertNotIn("<script", html_report.lower())
        self.assertEqual(profile, json.loads(visible_json)["profile"])
        self.assertEqual(result["profile_sha256"], json.loads(encoded)["assessment"]["profile_sha256"])

    def test_repeated_and_concurrent_local_reviews_are_bounded_read_only_and_stable(self):
        profile = self.resolved()
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve(strict=True)) as directory:
            file = Path(directory) / "customer-profile.json"
            file.write_text(json.dumps(profile), encoding="utf-8")
            before = file.read_bytes()
            with patch("socket.socket", side_effect=AssertionError("network forbidden")):
                with ThreadPoolExecutor(max_workers=4) as executor:
                    reports = list(executor.map(lambda _: deployment.assess(deployment.read_profile(file)), range(64)))
            self.assertTrue(all(report == reports[0] for report in reports))
            reversed_keys = dict(reversed(list(profile.items())))
            self.assertEqual(reports[0], deployment.assess(reversed_keys))
            self.assertEqual(before, file.read_bytes())
            self.assertEqual([file], list(Path(directory).iterdir()))

    def test_operator_gets_no_gate_for_corrupt_oversized_or_linked_files_without_content_echo(self):
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve(strict=True)) as directory:
            file = Path(directory) / "profile.json"
            payloads = ('{"duplicate":1,"duplicate":2}', '{"value":NaN}',
                        "[" * 2000 + "]" * 2000, "x" * (deployment.MAX_BYTES + 1),
                        "PRIVATE_SENTINEL_INVALID_JSON")
            for body in payloads:
                file.write_text(body, encoding="utf-8")
                output = io.StringIO()
                with patch("sys.stdout", output):
                    self.assertEqual(2, deployment.main(["--profile", str(file)]))
                self.assertEqual("NO_GATE", json.loads(output.getvalue())["assessment"]["verdict"])
                self.assertNotIn("PRIVATE_SENTINEL", output.getvalue())
            file.write_bytes(b"\xff\xfe")
            with patch("sys.stdout", io.StringIO()):
                self.assertEqual(2, deployment.main(["--profile", str(file)]))
            with patch("path_safety.is_link_like", return_value=True), self.assertRaises(ValueError):
                deployment.read_profile(file)
            # Real links may be unavailable without Windows link privileges.
            link = Path(directory) / "linked.json"
            try:
                link.symlink_to(file)
            except OSError:
                return
            with self.assertRaises(ValueError):
                deployment.read_profile(link)

    def test_fresh_operator_cli_distinguishes_profile_consistency_rejection_and_unknown(self):
        with tempfile.TemporaryDirectory(dir=Path(tempfile.gettempdir()).resolve(strict=True)) as directory:
            file = Path(directory) / "profile.json"
            blocked = self.resolved()
            blocked["trace_eval"]["customer_content_global_eval"] = True
            for profile, code, verdict in ((self.profile, 2, "NO_GATE"),
                                           (self.resolved(), 0, "PROFILE_CONSISTENT"),
                                           (blocked, 1, "REJECT")):
                file.write_text(json.dumps(profile), encoding="utf-8")
                completed = subprocess.run([sys.executable, str(deployment.ROOT / "scripts/deployment_profile.py"),
                                            "--profile", str(file)], capture_output=True, text=True, timeout=10)
                self.assertEqual(code, completed.returncode)
                self.assertEqual("", completed.stderr)
                self.assertEqual(verdict, json.loads(completed.stdout)["assessment"]["verdict"])


if __name__ == "__main__":
    unittest.main()
