import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import sha256
from lifecycle import Journal, process_identity
from process_resources import identity, stop_owned
from product_journal import observe
from verify_product_journal import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / "third-party-evaluation/20261006"
RUN = CAMPAIGN / "data/product-journal-recovery-001"


class ProductJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "run"

    def mutate(self, name, change):
        shutil.copytree(RUN, self.root)
        path = self.root / name
        value = json.loads(path.read_text())
        change(value)
        path.write_text(json.dumps(value))
        manifest_path = self.root / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["artifacts"][name] = sha256(path)
        manifest_path.write_text(json.dumps(manifest))

    def child(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; print('ready', flush=True); time.sleep(30)"],
                                 stdout=subprocess.PIPE, text=True, start_new_session=True)

        def cleanup():
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
            child.stdout.close()

        self.addCleanup(cleanup)
        self.assertEqual(child.stdout.readline(), "ready\n")
        return child

    def test_reused_pid_identity_never_signalled(self):
        child = self.child()
        result = stop_owned({**identity(child.pid), "start_ticks": "0"}, "0" * 64)
        self.assertEqual(result["before"], "pid_reused")
        self.assertFalse(result["signalled"])
        self.assertIsNone(child.poll())

    def test_wrong_command_digest_never_signalled(self):
        child = self.child()
        result = stop_owned(identity(child.pid), "0" * 64)
        self.assertFalse(result["stopped"])
        self.assertFalse(result["signalled"])
        self.assertIsNone(child.poll())

    def test_exact_owned_process_stopped_through_pidfd(self):
        child = self.child()
        digest = hashlib.sha256(Path(f"/proc/{child.pid}/cmdline").read_bytes()).hexdigest()
        result = stop_owned(identity(child.pid), digest)
        self.assertTrue(result["stopped"])
        self.assertTrue(result["signalled"])
        self.assertEqual(child.wait(timeout=5), -15)

    def test_actual_product_recovery_does_not_promote_retry(self):
        anchor = json.loads((CAMPAIGN / "inventory/anchors/product-journal-recovery-001.json").read_text())
        result, code = verify(RUN, anchor["manifest_sha256"])
        self.assertEqual(code, 2)
        self.assertEqual(result["attempts"], 11)
        self.assertEqual(result["first_attempt_pass"], 9)
        self.assertEqual(result["first_attempt_unknown"], 1)
        self.assertEqual(result["known_harm_first_attempt"], 1)
        self.assertEqual(result["signed_completed_attempts_checked"], 10)

    def test_product_checkpoint_records_failure_before_terminal_cleanup(self):
        protocol = json.loads((RUN / "protocol.json").read_text())
        protocol["run_id"] = self.root.name
        journal = Journal(self.root, protocol)
        self.addCleanup(journal.close)
        key = protocol["allocation"][0]["unit_id"] + "#1"
        journal.transition(key, "started", execution_status="running", process_ref=process_identity())
        observe(journal, key, {"assertions": [{"pass": False}], "tool_executed": True}, "attempts/check/1")
        self.assertEqual(journal.states[key]["assertion_status"], "fail")
        before = (self.root / "journal.jsonl").read_bytes()
        with self.assertRaisesRegex(ValueError, "failure"):
            journal.transition(key, "interrupted", execution_status="interrupted", measurement_status="indeterminate", assertion_status="inconclusive")
        self.assertEqual((self.root / "journal.jsonl").read_bytes(), before)

    def test_captured_harm_cannot_disappear_under_resealed_manifest(self):
        self.mutate("attempts/EV08.sample.adversarial/1/oracle.json", lambda value: value.update(mutation_observed=False))
        with self.assertRaisesRegex(ValueError, "harm"):
            verify(self.root)

    def test_false_cleanup_rejected_even_under_resealed_manifest(self):
        self.mutate("attempts/EV08.sample.adversarial/1/recovery-cleanup-1.json", lambda value: value.update(remaining_group_members=[{"pid": 123, "start_ticks": "10"}]))
        with self.assertRaisesRegex(ValueError, "cleanup"):
            verify(self.root)

    def test_receipt_decision_cannot_be_replaced_by_unsigned_result(self):
        self.mutate("attempts/PB01.sample.adversarial/1/result.json", lambda value: value["decision"].update(action="allow"))
        with self.assertRaisesRegex(ValueError, "signed receipt"):
            verify(self.root)

    def test_summary_cannot_count_successful_retry_as_first_pass(self):
        self.mutate("summary.json", lambda value: value.update(first_attempt_pass=10, first_attempt_unknown=0))
        with self.assertRaisesRegex(ValueError, "first-attempt"):
            verify(self.root)


if __name__ == "__main__":
    unittest.main()
