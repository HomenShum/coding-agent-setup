"""A builder compares harness candidates without mistaking fixtures for proof."""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bootstrap_learning as learning


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
        with tempfile.TemporaryDirectory() as directory:
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
        self.assertEqual("NO_CHANGE", learning.compare(self.policy, self.baseline, self.baseline)["verdict"])
        self.baseline["cases"].append(copy.deepcopy(self.baseline["cases"][0]))
        with self.assertRaises(ValueError):
            learning.compare(self.policy, self.baseline, self.baseline)


if __name__ == "__main__":
    unittest.main()
