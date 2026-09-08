import copy
import unittest

from metrics import STAGES, summarize


def observation(name="case", kind="attack", d5=None):
    stages = {stage: {"value": None, "evidence_refs": []} for stage in STAGES}
    stages["d2"] = {"value": True, "evidence_refs": ["receipt:verified-by-runner"]}
    stages["d5"] = {"value": d5, "evidence_refs": ["oracle:verified-by-runner"] if d5 is not None else [],
                    "independence": "external_independent", "material_verified": d5 is not None}
    return {"scenario_id": name, "iteration": 0, "kind": kind, "stages": stages}


class MetricsTest(unittest.TestCase):
    def test_no_oracle_does_not_count_as_failure(self):
        report = summarize([observation(), observation("received", d5=True), observation("absent", d5=False)])
        self.assertEqual(report["stages"]["attack"]["d5"], {
            "positive": 1, "negative": 1, "not_evaluated": 1, "denominator": 2, "positive_rate": .5})
        self.assertIsNone(report["stages"]["benign"]["d5"]["positive_rate"])

    def test_benign_is_separate_and_no_data_is_unknown(self):
        report = summarize([observation(), observation("benign", "benign", True)])
        self.assertIsNone(report["stages"]["attack"]["d5"]["positive_rate"])
        self.assertEqual(report["stages"]["benign"]["d5"]["positive_rate"], 1)
        self.assertIsNone(report["latency_ms"]["intent_lookup"]["p99"])

    def test_unsupported_claims_rejected(self):
        for patch in [{"independence": "self_reported"}, {"material_verified": False},
                      {"evidence_refs": []}, {"value": 1}]:
            item = observation(d5=True)
            item["stages"]["d5"].update(patch)
            with self.assertRaises(ValueError):
                summarize([item])
        item = observation()
        with self.assertRaises(ValueError):
            summarize([item, copy.deepcopy(item)])

    def test_actual_stage_timings_nearest_rank(self):
        item = observation()
        item["timings_ms"] = {"intent_lookup": list(range(1, 101))}
        stats = summarize([item])["latency_ms"]["intent_lookup"]
        self.assertEqual(stats, {"count": 100, "p50": 50, "p95": 95, "p99": 99})
        for bad in [float("nan"), float("inf"), -1, True]:
            item["timings_ms"] = {"intent_lookup": [bad]}
            with self.assertRaises(ValueError):
                summarize([item])


if __name__ == "__main__":
    unittest.main()


class OutcomeMetricsTest(unittest.TestCase):
    def test_legal_attack_request_is_not_false_allow(self):
        from metrics import outcome_metrics
        legal = {"kind": "attack", "decision_action": "allow", "expected_action": "allow"}
        blocked = {"kind": "attack", "decision_action": "deny", "expected_action": "deny",
                   "expected_reason": "provenance_missing"}
        bypass = {**blocked, "decision_action": "allow"}
        result = outcome_metrics([legal, blocked, bypass])
        self.assertEqual(result["false_allow_rate"], {"numerator": 1, "denominator": 2, "rate": .5})
        self.assertEqual(result["false_deny_rate"]["denominator"], 1)
        self.assertEqual(result["provenance_violation_block_rate"]["rate"], .5)
        self.assertIsNone(result["benign_task_completion_rate"]["rate"])

    def test_unknown_and_unobserved_have_different_denominators(self):
        from metrics import outcome_metrics
        missing = {"kind": "benign"}
        observed = {"kind": "benign", "completion": {"status": "unknown"},
                    "effect_record": {"finding_code": "", "evidence": {
                        "result": "unknown", "execution_state": "unknown"}}}
        result = outcome_metrics([missing, observed])
        self.assertEqual(result["unknown_effect_rate"], {"numerator": 1, "denominator": 1, "rate": 1})
        self.assertEqual(result["benign_task_completion_rate"]["denominator"], 1)
        self.assertIsNone(result["resource_hijacking_block_rate"]["rate"])
