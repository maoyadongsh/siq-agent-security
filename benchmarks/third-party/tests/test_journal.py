import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lifecycle import Journal, process_identity, project, validate
from verify_journal import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / "evaluations/campaigns/20261006"
RUN = CAMPAIGN / "data/journal-calibration-002"


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "test-run"
        self.protocol = json.loads((RUN / "protocol.json").read_text())
        self.protocol["run_id"] = self.root.name

    def journal(self):
        value = Journal(self.root, self.protocol)
        self.addCleanup(value.close)
        return value

    def start(self, journal):
        journal.transition("interrupted-write#1", "started", execution_status="running", process_ref=process_identity())

    def test_actual_interruption_retry_keeps_unknown_first_attempt(self):
        anchor = json.loads((CAMPAIGN / "inventory/anchors/journal-calibration-002.json").read_text())
        result, code = verify(RUN, anchor["manifest_sha256"])
        self.assertEqual(code, 2)
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(result["first_attempt_pass"], 1)
        self.assertEqual(result["first_attempt_unknown"], 1)
        self.assertEqual(result["known_harm_first_attempt"], 1)

    def test_live_writer_not_reconciled_or_retried(self):
        journal = self.journal()
        self.start(journal)
        journal.reconcile_dead_writers()
        self.assertEqual(journal.states["interrupted-write#1"]["lifecycle"], "started")
        with self.assertRaises(ValueError):
            journal.retry("interrupted-write")
        with self.assertRaises(ValueError):
            Journal(self.root)

    def test_known_effect_cannot_be_erased_or_process_replaced(self):
        journal = self.journal()
        self.start(journal)
        journal.transition("interrupted-write#1", "observed", harm_observed=True, harm_unknown_reason=None,
                           harm_evidence_refs=["effect.json"], tool_executed=True)
        before = (self.root / "journal.jsonl").read_bytes()
        for change in ({"harm_observed": None}, {"harm_evidence_refs": []}, {"tool_executed": False},
                       {"process_ref": {**process_identity(), "start_ticks": "0"}}, {"attempt": 2}):
            with self.assertRaises(ValueError):
                journal.transition("interrupted-write#1", "observed", **change)
            self.assertEqual((self.root / "journal.jsonl").read_bytes(), before)

    def test_torn_tail_is_not_silently_truncated(self):
        journal = self.journal()
        journal.close()
        path = self.root / "journal.jsonl"
        with path.open("ab") as stream:
            stream.write(b'{"incomplete"')
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "torn"):
            Journal(self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_truncated_allocation_rejected_even_with_valid_event_prefix(self):
        journal = self.journal()
        journal.close()
        path = self.root / "journal.jsonl"
        path.write_bytes(path.read_bytes().splitlines(keepends=True)[0])
        with self.assertRaisesRegex(ValueError, "allocation"):
            project(self.root)

    def test_unknown_cannot_be_encoded_as_pass_or_numeric_boolean(self):
        journal = self.journal()
        row = copy.deepcopy(journal.states["interrupted-write#1"])
        row["assertion_status"] = "pass"
        with self.assertRaises(ValueError):
            validate(row)
        row["assertion_status"] = "not_evaluated"
        row["harm_observed"] = 0
        with self.assertRaises(ValueError):
            validate(row)
        row["harm_observed"] = None
        row["harm_unknown_reason"] = None
        with self.assertRaises(ValueError):
            validate(row)

    def test_sealed_run_and_escaped_material_rejected(self):
        shutil.copytree(RUN, self.root)
        with self.assertRaisesRegex(ValueError, "sealed"):
            Journal(self.root)
        manifest = self.root / "manifest.json"
        value = json.loads(manifest.read_text())
        value["artifacts"]["../escape"] = "0" * 64
        manifest.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            verify(self.root)


if __name__ == "__main__":
    unittest.main()
