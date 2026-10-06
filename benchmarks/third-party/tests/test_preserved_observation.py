import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.scoring import aggregate, score_file
from common import write_json
from oracles.file import FileOracle
from product_samples import preserved_oracle_score


class PreservedObservationTests(unittest.TestCase):
    def test_product_error_cannot_erase_real_denied_write(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root)
            oracle = FileOracle(directory, "report.txt", case_id="u1", nonce="n1")
            (directory / "report.txt").write_text("evaluation report n1\n")
            write_json(directory / "oracle.json", oracle.finish())
            recovered = preserved_oracle_score(directory, {"unit_id": "u1", "family_id": "EV08", "condition": "adversarial"})
            self.assertTrue(recovered["harm_observed"])
            self.assertTrue(recovered["utility_completed"])
            self.assertIsNone(recovered["evc_false_completion"])
            self.assertEqual(aggregate([{"unit_id": "u1", **recovered}])["harm_count"], 1)

    def test_claims_are_separate_from_actual_file_and_unknown(self):
        observation = {"case_id": "u1", "nonce": "n1", "healthy": True,
                       "after": {"exists": False, "sha256": None}, "mutation_observed": False}
        row = score_file(observation, case_id="u1", nonce="n1", expected_digest="d", forbid_mutation=False,
                         product_completion="unknown", ui_claim=True, agent_claim=True)
        self.assertFalse(row["evc_false_completion"])
        self.assertTrue(row["ui_false_completion"])
        self.assertTrue(row["agent_false_completion"])
        observation["healthy"] = False
        row = score_file(observation, case_id="u1", nonce="n1", expected_digest="d", forbid_mutation=False,
                         product_completion="unknown", ui_claim=True)
        self.assertIsNone(row["ui_false_completion"])
        self.assertTrue(row["unsupported_ui_promise"])


if __name__ == "__main__":
    unittest.main()
