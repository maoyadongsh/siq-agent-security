import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from concurrent_governance import evaluate
from verify_governance import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / "third-party-evaluation/20261006"


class ConcurrentGovernanceTests(unittest.TestCase):
    def test_original_concurrent_failures_remain_failures(self):
        run = CAMPAIGN / "data/governance-race-002"
        anchor = json.loads((CAMPAIGN / "inventory/anchors/governance-race-002.json").read_text())
        result = verify(run, anchor["manifest_sha256"])
        self.assertTrue(result["integrity_verified"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks_passed"], 45)

    def test_repaired_http_and_sql_results_recompute(self):
        result = verify(CAMPAIGN / "data/governance-race-fix1-001",
                        "14b69f008891b818909e5969d0e01b91f046adcd8e3cdd83ec484c06d9222f5d")
        self.assertTrue(result["passed"])
        self.assertEqual(result["checks_passed"], 48)

    def test_duplicate_event_wrong_winner_and_missing_overlap_fail(self):
        path = CAMPAIGN / "data/governance-race-fix1-001/race-observations.json"
        o = json.loads(path.read_text())
        o["legacy_approve"]["database"]["outbox"].append(o["legacy_approve"]["database"]["outbox"][0])
        self.assertFalse(evaluate(o)["race_legacy_approve"])
        o = json.loads(path.read_text())
        o["legacy_mixed"]["database"]["change"][0][1] = "different-reviewer"
        self.assertFalse(evaluate(o)["race_legacy_mixed"])
        o = json.loads(path.read_text())
        o["review_approve"]["blocked"].pop()
        self.assertFalse(evaluate(o)["race_review_approve"])
        o = json.loads(path.read_text())
        o["create_idempotency"]["responses"][0]["body"]["id"] = "another-object"
        self.assertFalse(evaluate(o)["race_create_idempotency"])


if __name__ == "__main__":
    unittest.main()
