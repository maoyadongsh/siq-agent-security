import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend_governance import evaluate
from verify_governance import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / "evaluations/campaigns/20261006"


class BackendGovernanceTests(unittest.TestCase):
    def test_real_backend_capture_recomputes(self):
        result = verify(CAMPAIGN / "data/governance-backend-003",
                        "0206e091d3dfc1d334759df5a7249b20f1f6d0725423e482d3af36394dd32f15")
        self.assertTrue(result["passed"])
        self.assertEqual(result["checks_passed"], 129)

    def test_original_bad_oracle_not_rewritten(self):
        result = verify(CAMPAIGN / "data/governance-backend-002",
                        "cdd7d2dd79f7096bec99e9f9325f6904ec042143b61b2a3df578128f6ad422c9")
        self.assertTrue(result["integrity_verified"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks_passed"], 128)

    def test_wrong_revision_and_false_restoration_do_not_pass(self):
        path = CAMPAIGN / "data/governance-backend-003/backend-observations.json"
        o = json.loads(path.read_text())
        o["database_applied"][0][4]["backend_revision"] = "999"
        self.assertFalse(evaluate(o)["backend_database_effective"])
        o = json.loads(path.read_text())
        o["rolled_back"]["policy"] = o["applied"]["policy"]
        self.assertFalse(evaluate(o)["backend_exact_rollback"])
        o = json.loads(path.read_text())
        o["after_stale"]["deployments"].append(["unwanted", "effective", "policy-1"])
        self.assertFalse(evaluate(o)["backend_stale_preview_no_effect"])


if __name__ == "__main__":
    unittest.main()
