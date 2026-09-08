import copy
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from run import CORPUS, ROOT, load_corpus, run_case, summarize, target_action
from verify import verify


class BenchmarkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="siq-hackathon-benchmark-")
        cls.addClassCleanup(cls.temp.cleanup)
        root = Path(cls.temp.name)
        binary = root / "siq-agent-security"
        subprocess.run(["go", "build", "-o", str(binary), "./cmd/agentshield"],
                       cwd=ROOT / "apps/agentshield", check=True, capture_output=True)
        case = next(c for c in load_corpus() if c["id"] == "benign-docs")
        item = run_case(case, binary, root / "normal", "controls")
        cls.report = {"schema_version": "hackathon-benchmark/v1", "cohort": "controls", "coverage": "partial",
                      "corpus_sha256": hashlib.sha256(CORPUS.read_bytes()).hexdigest(), "cases": [item],
                      "summary": summarize([item])}

    def test_actual_receipts_effects_and_utility_verify(self):
        result = verify(self.report)
        self.assertGreater(result["verified_receipts"], 0)
        self.assertEqual(result["verified_effect_envelopes"], 2)
        self.assertEqual(result["summary"]["benign_task_completion_rate"]["rate"], 1)

    def test_partial_cannot_claim_full_and_duplicate_cannot_inflate_denominator(self):
        for change in ("coverage", "duplicate"):
            report = copy.deepcopy(self.report)
            if change == "coverage":
                report["coverage"] = "full"
            else:
                report["cases"].append(report["cases"][0])
            with self.assertRaises(ValueError):
                verify(report)

    def test_tampered_decision_effect_or_metrics_fail_verification(self):
        for change in ("decision", "effect", "metric", "completion", "expectation"):
            report = copy.deepcopy(self.report)
            task = report["cases"][0]["result"]["task"]
            if change == "decision":
                task["actions"][0]["decision"] = "deny"
            elif change == "effect":
                record = next(a["effect"] for a in task["actions"] if a["effect"])
                record["evidence"]["signature"] = "00" * 64
            elif change == "metric":
                report["summary"]["benign_task_completion_rate"]["numerator"] = 9
            elif change == "completion":
                task["completion"]["requirements"][0]["evidence_ids"] = ["invented-effect"]
            else:
                report["cases"][0]["expectation_violations"] = ["invented_failure"]
            with self.assertRaises((ValueError, InvalidSignature)):
                verify(report)

    def test_failed_planning_remains_in_benign_utility_denominator(self):
        failure = copy.deepcopy(self.report["cases"][0])
        failure["result"]["task"].update(status="failed", completion=None, actions=[])
        failure["result"]["preparation"]["actions"] = []
        failure["verification"]["effects"] = 0
        metric = summarize([self.report["cases"][0], failure])["benign_task_completion_rate"]
        self.assertEqual((metric["numerator"], metric["denominator"]), (1, 2))

    def test_early_benign_denial_is_counted_without_reaching_delivery(self):
        item = copy.deepcopy(self.report["cases"][0])
        item["result"]["task"]["actions"] = [{"tool": "write_file", "decision": "deny", "effect": None}]
        metric = summarize([item])["siq_decision_metrics"]["false_deny_rate"]
        self.assertEqual((metric["numerator"], metric["denominator"]), (1, 1))

    def test_preparation_reads_do_not_count_as_revoked_execution(self):
        item = copy.deepcopy(self.report["cases"][0])
        case = next(c for c in load_corpus() if c["id"] == "intent-revoked")
        item["result"]["task"]["actions"] = [{"tool": "web_fetch", "decision": "deny", "d3_materialized": False}]
        target = target_action(case, item["result"])
        self.assertFalse(target["d3_materialized"])


if __name__ == "__main__":
    unittest.main()
