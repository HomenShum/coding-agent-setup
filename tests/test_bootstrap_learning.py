"""A builder compares harness candidates without mistaking fixtures for proof."""
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bootstrap_learning as learning

# Test-owned fixtures use physical paths; the production link guard stays strict.
TEMP_ROOT = Path(tempfile.gettempdir()).resolve(strict=True)


class BuilderLearningScenarios(unittest.TestCase):
    def setUp(self):
        self.policy = learning.policy_at(learning.ROOT / "templates/learning")
        self.baseline, self.candidate = learning.demo(self.policy)

    def test_builder_sees_synthetic_improvement_but_never_activation(self):
        result = learning.compare(self.policy, self.baseline, self.candidate)
        self.assertEqual("NUMERICALLY_ELIGIBLE", result["verdict"])
        self.assertTrue(result["synthetic"])
        self.assertFalse(result["activated"])
        self.candidate["cases"][1]["scores"]["usefulness"]["value"] = 2
        self.assertEqual("REJECT", learning.compare(self.policy, self.baseline, self.candidate)["verdict"])

    def test_high_quality_does_not_compensate_for_ungrounded_answer(self):
        self.candidate["cases"][0]["gates"]["grounded"]["value"] = False
        self.assertEqual("REJECT", learning.compare(self.policy, self.baseline, self.candidate)["verdict"])

    def test_builder_cannot_compare_corrupt_or_unavailable_evidence(self):
        for field, value in (("status", "provider_error"), ("trace", ""), ("group", "heldout")):
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.candidate)
                candidate["cases"][0][field] = value
                with self.assertRaises(ValueError):
                    learning.compare(self.policy, self.baseline, candidate)
        for value in (True, 0, 6, 3.5):
            candidate = copy.deepcopy(self.candidate)
            candidate["cases"][0]["scores"]["usefulness"]["value"] = value
            with self.assertRaises(ValueError):
                learning.compare(self.policy, self.baseline, candidate)
        self.candidate["identity"]["model"] = "different-model"
        with self.assertRaises(ValueError):
            learning.compare(self.policy, self.baseline, self.candidate)

    def test_repeated_bootstrap_preserves_existing_builder_work(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            target = Path(directory)
            learning.initialize(target)
            content = (target / "evals/learning/policy.json").read_bytes()
            for _ in range(20):
                with self.assertRaises(ValueError):
                    learning.initialize(target)
            self.assertEqual(content, (target / "evals/learning/policy.json").read_bytes())

    def test_builder_rejects_partial_scores_and_bounds_accumulated_cases(self):
        for mutation in ("missing_case", "missing_rationale", "duplicate"):
            candidate = copy.deepcopy(self.candidate)
            if mutation == "missing_case":
                candidate["cases"].pop()
            elif mutation == "missing_rationale":
                candidate["cases"][0]["scores"]["usefulness"]["rationale"] = " "
            else:
                candidate["cases"].append(copy.deepcopy(candidate["cases"][0]))
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                learning.compare(self.policy, self.baseline, candidate)
        for index in range(2, 1000):
            case = copy.deepcopy(self.baseline["cases"][index % 2])
            case["id"] = str(index)
            self.baseline["cases"].append(case)
        unchanged = copy.deepcopy(self.baseline)
        unchanged["harness"] = "unchanged-candidate"
        self.assertEqual("NO_CHANGE", learning.compare(self.policy, self.baseline, unchanged)["verdict"])
        self.baseline["cases"].append(copy.deepcopy(self.baseline["cases"][0]))
        with self.assertRaises(ValueError):
            learning.compare(self.policy, self.baseline, unchanged)

    def test_reviewer_rejects_policy_changes_hidden_behind_stable_labels(self):
        changed_policy = copy.deepcopy(self.policy)
        changed_policy["gates"]["grounded"]["pass"] = "Materially different acceptance wording."
        with self.assertRaisesRegex(ValueError, "policy digest"):
            learning.compare(changed_policy, self.baseline, self.candidate)
        canonical = json.dumps(self.policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        self.assertEqual(hashlib.sha256(canonical.encode("utf-8")).hexdigest(), self.baseline["policy_sha256"])
        reordered = dict(reversed(list(self.policy.items())))
        self.assertEqual("NUMERICALLY_ELIGIBLE", learning.compare(reordered, self.baseline, self.candidate)["verdict"])

    def test_reviewer_requires_explicit_version_and_distinct_harnesses(self):
        for mutation in ("legacy", "same_harness", "missing_digest", "wrong_digest"):
            candidate = copy.deepcopy(self.candidate)
            if mutation == "legacy":
                candidate.pop("version", None)
            elif mutation == "same_harness":
                candidate["harness"] = self.baseline["harness"]
            elif mutation == "missing_digest":
                candidate.pop("policy_sha256", None)
            else:
                candidate["policy_sha256"] = "0" * 64
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                learning.compare(self.policy, self.baseline, candidate)

    def test_reviewer_cannot_relabel_synthetic_trace_evidence_as_real(self):
        self.baseline["synthetic"] = self.candidate["synthetic"] = False
        with self.assertRaisesRegex(ValueError, "synthetic trace"):
            learning.compare(self.policy, self.baseline, self.candidate)
        for run in (self.baseline, self.candidate):
            for case in run["cases"]:
                case["trace"] = "local:opaque-" + case["id"]
        result = learning.compare(self.policy, self.baseline, self.candidate)
        self.assertFalse(result["activated"])
        self.assertIn("source authenticity", result["unverified"])

    def test_stronger_aggregate_scores_cannot_hide_one_users_regression(self):
        for run in (self.baseline, self.candidate):
            additional = copy.deepcopy(run["cases"][0])
            additional["id"] = "visible-second-user"
            run["cases"].append(additional)
        self.candidate["cases"][0]["scores"]["usefulness"]["value"] = 2
        self.candidate["cases"][2]["scores"]["usefulness"]["value"] = 5
        self.assertEqual("REJECT", learning.compare(self.policy, self.baseline, self.candidate)["verdict"])

    def test_legacy_or_weakened_policy_cannot_silently_opt_out_of_protection(self):
        for change in ({"version": 1}, {"regression": "allow-aggregate-offset"}):
            policy = copy.deepcopy(self.policy)
            policy.update(change)
            with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
                bundle = Path(directory)
                (bundle / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
                with self.subTest(change=change), self.assertRaisesRegex(ValueError, "policy"):
                    learning.policy_at(bundle)


if __name__ == "__main__":
    unittest.main()
