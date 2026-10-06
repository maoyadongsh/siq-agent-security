import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ui_governance import evaluate
from verify_governance import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / "third-party-evaluation/20261006"


class UIGovernanceTests(unittest.TestCase):
    def observations(self):
        return json.loads((CAMPAIGN / "data/governance-ui-005/ui-observations.json").read_text())

    def test_browser_and_database_capture_recompute(self):
        anchor = json.loads((CAMPAIGN / "inventory/anchors/governance-ui-005.json").read_text())
        result = verify(CAMPAIGN / "data/governance-ui-005", anchor["manifest_sha256"])
        self.assertTrue(result["passed"])
        self.assertEqual(result["checks_passed"], 113)

    def test_enabled_self_approval_and_duplicate_post_fail(self):
        o = self.observations()
        o["self_review"] = o["self_review"].replace('[disabled]', '')
        self.assertFalse(evaluate(o)["ui_self_review_blocked"])
        o = self.observations()
        post = next(x for x in o["api"] if x["path"].endswith('/review-decision'))
        o["api"].append(copy.deepcopy(post))
        self.assertFalse(evaluate(o)["ui_approval_transaction"])

    def test_false_ui_claim_and_storage_leak_fail(self):
        o = self.observations()
        o["approved"] = '后端标记已生效'
        o["storage"]["local"] = 1
        o["mobile"]["width"] = 650
        result = evaluate(o)
        for name in ('ui_approved_not_effective', 'ui_no_persistent_token', 'ui_mobile_fits'):
            self.assertFalse(result[name])


if __name__ == "__main__":
    unittest.main()
