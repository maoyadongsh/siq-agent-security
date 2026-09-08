"""Negative verification against an archived real SIQ / StepFun checkpoint."""

import copy
import json
import unittest
from pathlib import Path

from trifecta_evidence import verify_trifecta


class TrifectaEvidenceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = json.loads((Path(__file__).resolve().parents[2] /
            "docs/hackathon/evidence/stepfun-trifecta-20260908.json").read_text())

    def test_actual_signed_sequence(self):
        self.assertTrue(verify_trifecta(self.record)["same_session"])

    def test_forged_display_state_is_rejected(self):
        record = copy.deepcopy(self.record)
        record["result"]["task"]["actions"][0]["decision_trifecta"]["untrusted_input"] = True
        with self.assertRaises(ValueError):
            verify_trifecta(record)

    def test_reordered_or_borrowed_action_is_rejected(self):
        for mode in ("reorder", "borrow"):
            record = copy.deepcopy(self.record)
            events = record["result"]["task"]["actions"]
            if mode == "reorder":
                events[0], events[1] = events[1], events[0]
            else:
                events[0]["receipt_id"] = record["result"]["preparation"]["actions"][0]["receipt_id"]
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                verify_trifecta(record)

    def test_missing_or_modified_signed_observation_is_rejected(self):
        for mode in ("missing", "modified"):
            record = copy.deepcopy(self.record)
            receipts = record["public_evidence"]["receipts"]
            receipt = next(r for r in receipts if r["record_type"] == "observation")
            if mode == "missing":
                receipts.remove(receipt)
            else:
                receipt["params_digest"] = "0" * 64
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                verify_trifecta(record)

    def test_claimed_effect_or_execution_after_deny_is_rejected(self):
        for mode in ("sink", "execution", "completion"):
            record = copy.deepcopy(self.record)
            if mode == "sink":
                record["result"]["messages"] = [{"synthetic": True}]
            elif mode == "execution":
                record["result"]["task"]["actions"][-1]["d3_materialized"] = True
            else:
                record["result"]["task"]["completion"]["status"] = "verified"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                verify_trifecta(record)
