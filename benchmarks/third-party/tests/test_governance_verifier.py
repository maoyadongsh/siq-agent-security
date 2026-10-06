"""Calibrate against sealed captures; never starts HTTP or accesses a database."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import sha256
from verify_governance import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / "third-party-evaluation/20261006"
SOURCE = CAMPAIGN / "data/governance-http-003"
ANCHOR = "c6b0e40c6a31f892c8c5380ab0d078fe2a239c2817e04355571685744593495c"


class GovernanceVerifierTests(unittest.TestCase):
    def test_edge_complete_capture(self):
        result = verify(CAMPAIGN / "data/governance-edge-001",
                        "977254b34d789789a1eda7cc25b460c8e736ddefb83cad19527a4ca1d9a96b64")
        self.assertTrue(result["passed"])
        self.assertEqual(result["checks_passed"], 102)

    def test_edge_mutated_task_signature_and_tenant_leak_detected(self):
        from edge_governance_scoring import evaluate
        source = CAMPAIGN / "data/governance-edge-001/edge-observations.json"
        o = json.loads(source.read_text())
        o["tasks_a"][0]["environment_id"] = o["registration_b"]["environment_id"]
        self.assertFalse(evaluate(o)["edge_task_scope_signatures"])
        o = json.loads(source.read_text())
        o["assets_b"].append(o["assets_a"][0])
        self.assertFalse(evaluate(o)["edge_asset_list_isolation"])
        o = json.loads(source.read_text())
        o["after_invalid"]["permissions"].append(["injected", "effective"])
        self.assertFalse(evaluate(o)["edge_invalid_batches_atomic"])

    def test_edge_credentials_redacted_before_event_capture(self):
        run = CAMPAIGN / "data/governance-edge-001"
        rows = json.loads((run / "http.json").read_text())
        for row in rows:
            if row["case_id"].startswith("edge_register_"):
                self.assertEqual(row["request_body"]["enrollment_code"], "[REDACTED]")
                self.assertEqual(row["body"]["device_secret"], "[REDACTED]")
            if row["case_id"].startswith("edge_enroll_"):
                self.assertEqual(row["body"]["code"], "[REDACTED]")
        self.assertNotIn('"Authorization"', (run / "events.jsonl").read_text())

    def test_complete_capture(self):
        self.assertTrue(verify(SOURCE, ANCHOR)["passed"])

    def test_preserved_failure_not_reclassified_as_pass(self):
        result = verify(CAMPAIGN / "data/governance-http-002",
                        "605bb5ced25edf2699b14b5d1fd1480cd936b84375da3768c6b9c19ed81890d4")
        self.assertTrue(result["integrity_verified"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["checks_passed"], 42)

    def test_raw_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            shutil.copytree(SOURCE, run)
            with (run / "http.json").open("a") as stream:
                stream.write(" ")
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                verify(run, ANCHOR)

    def test_resealed_false_positive_sql_assertion_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / "run"
            shutil.copytree(SOURCE, run)
            summary = json.loads((run / "summary.json").read_text())
            # Even after granting a new anchor, a coherent projection of an
            # incorrect success flag must not override the recorded SQL state.
            next(c for c in summary["checks"] if c["id"] == "approved_with_audit_and_outbox")["observed"]["outbox"] = []
            (run / "summary.json").write_text(json.dumps(summary))
            events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
            next(e for e in events if e.get("id") == "approved_with_audit_and_outbox")["observed"]["outbox"] = []
            (run / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
            manifest = json.loads((run / "manifest.json").read_text())
            for name in ("events.jsonl", "summary.json"):
                manifest["artifacts"][name] = sha256(run / name)
            (run / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "assertion outcome differs"):
                verify(run, sha256(run / "manifest.json"))


if __name__ == "__main__":
    unittest.main()
