"""Regression: a signed decision alone must never justify D5 statistics."""
import copy
import unittest

from evidence import verify_effect_reference


class EffectReferenceTest(unittest.TestCase):
    def test_unobserved_is_unknown_not_success_or_failure(self):
        verify_effect_reference(None, {"value": None}, "receipt-1")
        for value in (True, False):
            with self.assertRaisesRegex(ValueError, "archived effect"):
                verify_effect_reference(None, {
                    "value": value, "evidence_refs": ["invented-oracle"],
                    "independence": "external_independent", "material_verified": True,
                }, "receipt-1")

    def test_material_and_reference_must_belong_to_current_decision(self):
        record = {"evidence": {"decision_receipt_id": "receipt-1", "effect_evidence_id": "effect-1"},
                  "file_observation": {"after": {"exists": False}}}
        stage = {"value": False, "evidence_refs": ["effect-1"]}
        # This checks only structural association; verify() separately checks signatures.
        verify_effect_reference(record, stage, "receipt-1")
        with self.assertRaisesRegex(ValueError, "another observation"):
            verify_effect_reference(record, stage, "receipt-2")
        for refs in ([], ["effect-2"], ["effect-1", "effect-2"]):
            with self.assertRaisesRegex(ValueError, "signed effect"):
                verify_effect_reference(record, stage | {"evidence_refs": refs}, "receipt-1")
        missing = copy.deepcopy(record)
        del missing["file_observation"]
        with self.assertRaisesRegex(ValueError, "observation material"):
            verify_effect_reference(missing, stage, "receipt-1")


if __name__ == "__main__":
    unittest.main()
