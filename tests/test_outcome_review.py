"""Cross-host builders preserve frozen goals and failed work through handoffs."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import outcome_review as outcome

# Test-owned fixtures use physical paths; the production link guard stays strict.
TEMP_ROOT = Path(tempfile.gettempdir()).resolve(strict=True)


class OutcomeScenarios(unittest.TestCase):
    def setUp(self):
        self.contract = outcome.read(Path(__file__).resolve().parents[1] / "templates/harness/outcome-contract.json")

    def test_builder_cannot_upgrade_unknown_baseline_to_ready(self):
        self.assertEqual("DISCOVERY", outcome.validate_contract(self.contract)["status"])
        self.contract["state"] = "READY"
        with self.assertRaises(ValueError):
            outcome.validate_contract(self.contract)

    def test_failed_gate_survives_host_switch_and_stale_writer_is_refused(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            ledger = Path(directory) / "events.jsonl"
            first = outcome.append(ledger, contract=self.contract)
            failure = {"type": "GATE_FAILED", "actor": "worker", "summary": "A source claim lacks its receipt.", "next_action": "Inspect the source", "failed_gates": ["citation-support"], "evidence": ["run-1/failure.json"]}
            second = outcome.append(ledger, event=failure, expected_head=first["sha256"])
            with self.assertRaises(ValueError):
                outcome.append(ledger, event=failure, expected_head=first["sha256"])
            switch = {**failure, "type": "HOST_SWITCH", "actor": "next-host", "failed_gates": [], "summary": "Resume the same work."}
            outcome.append(ledger, event=switch, expected_head=second["sha256"])
            report = outcome.review(outcome.history(ledger))
            self.assertIn("Open failures: citation-support", report)
            self.assertIn("NOT AUTHORIZED", report)
            before = ledger.read_bytes()
            with self.assertRaises(ValueError):
                outcome.append(ledger, event={**failure, "type": "GATE_PASSED", "evidence": []}, expected_head=outcome.history(ledger)[-1]["sha256"])
            self.assertEqual(before, ledger.read_bytes())
            self.assertIn("Open failures: citation-support", outcome.review(outcome.history(ledger)))
            with self.assertRaises(ValueError):
                outcome.append(ledger, contract=self.contract)

    def test_sustained_append_bounds_history_and_detects_corruption(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            ledger = Path(directory) / "events.jsonl"
            head = outcome.append(ledger, contract=self.contract)["sha256"]
            event = {"type": "CONTEXT_REFRESHED", "actor": "builder", "summary": "No new source yet", "next_action": "Review remaining authorized source", "failed_gates": [], "evidence": []}
            for _ in range(30):
                head = outcome.append(ledger, event=event, expected_head=head)["sha256"]
            self.assertEqual(31, len(outcome.history(ledger)))
            original = ledger.read_bytes()
            ledger.write_bytes(original.replace(b"No new source yet", b"All sources found", 1))
            with self.assertRaises(ValueError):
                outcome.history(ledger)

    def test_search_ablation_measures_exact_repetition_not_semantic_quality(self):
        item = {"query": "programmable display", "query_origin": "USER", "retriever": "keyword-v1", "corpus_snapshot": "sources-v1", "trace": "run/search", "stop_reason": "continue", "complete": True, "document_ids": ["doc-a"]}
        result = outcome.trajectory({"positive_document_ids": ["doc-a", "doc-b"], "rounds": [item, copy.deepcopy(item)]})
        self.assertEqual(1, result["repeated_exact_queries"])
        self.assertEqual(0.5, result["positive_document_recall"])
        self.assertEqual("REQUIRES_REVIEW", result["source_support"])


if __name__ == "__main__":
    unittest.main()
