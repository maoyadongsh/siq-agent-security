import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import Events, safe_path, sha256, write_json
from run import seal
from verify import verify


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "raw-private").mkdir()
        (self.root / "harness-source").mkdir()
        self.allocation = [{"unit_id": "controls:calibration", "case_id": "calibration", "suite": "controls", "repetition": 1}]
        write_json(self.root / "allocation.json", self.allocation)
        write_json(self.root / "protocol.json", {"allocation_sha256": sha256(self.root / "allocation.json"),
                                                "allocation_count": 1, "operations": ["controls", "controls-verify"]})
        plans = [{"command_id": name, "argv": ["calibration-no-execution", name]} for name in ("controls", "controls-verify")]
        write_json(self.root / "execution-plan.json", plans)
        events = Events(self.root / "command-events.jsonl", "calibration")
        for plan in plans:
            events.add("command_started", **plan)
            events.add("command_finished", **plan, exit_code=0, error=None)
        events = Events(self.root / "case-events.jsonl", "calibration")
        events.add("scheduled", unit_id="controls:calibration")
        events.add("legacy_capture_finished", unit_id="controls:calibration")
        observation = {"case": {"id": "calibration"}, "expectation_violations": []}
        write_json(self.root / "raw-private/controls.json", {"cases": [observation]})
        case = {**self.allocation[0], "execution_status": "completed", "assertion_status": "pass",
                "evidence_refs": ["raw-private/controls.json"], "legacy_observation": observation,
                "harm_observed": None, "utility_completed": None}
        (self.root / "cases.jsonl").write_text(json.dumps(case) + "\n")
        write_json(self.root / "metrics.json", {"allocated": 1, "captured": 1, "assertion_pass": 1,
                                               "inconclusive": 0, "failed_commands": []})
        write_json(self.root / "findings.json", [])
        (self.root / "report.md").write_text("Synthetic verifier calibration; not a product result.\n")
        self.metadata = {"run_id": "calibration", "protocol_sha256": sha256(self.root / "protocol.json"), "allocation_count": 1}
        self.anchor = seal(self.root, self.metadata)

    def reseal(self):
        (self.root / "checksums.json").unlink()
        (self.root / "manifest.json").unlink()
        return seal(self.root, self.metadata)

    def test_valid_package_and_absent_anchor_scope(self):
        result, code = verify(self.root, self.anchor)
        self.assertEqual(code, 0)
        self.assertEqual(result["captured"], 1)
        self.assertEqual(verify(self.root, None)[0]["integrity"], "internal_consistency_only")

    def test_tampering_and_whole_package_replacement(self):
        (self.root / "report.md").write_text("substituted")
        with self.assertRaises(ValueError):
            verify(self.root, self.anchor)
        self.reseal()
        with self.assertRaisesRegex(ValueError, "manifest digest"):
            verify(self.root, self.anchor)

    def test_duplicate_or_missing_case_even_after_rehash(self):
        text = (self.root / "cases.jsonl").read_text()
        for value in (text + text, ""):
            (self.root / "cases.jsonl").write_text(value)
            anchor = self.reseal()
            with self.assertRaises(ValueError):
                verify(self.root, anchor)

    def test_unknown_cannot_pass_and_original_failure_cannot_disappear(self):
        row = json.loads((self.root / "cases.jsonl").read_text())
        row["legacy_observation"] = None
        (self.root / "cases.jsonl").write_text(json.dumps(row) + "\n")
        with self.assertRaisesRegex(ValueError, "projection"):
            verify(self.root, self.reseal())

    def test_event_truncation_detected_after_rehash(self):
        path = self.root / "command-events.jsonl"
        path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n")
        with self.assertRaisesRegex(ValueError, "unaccounted"):
            verify(self.root, self.reseal())

    def test_path_escape_and_symlink(self):
        for name in ("../outside", "/tmp/outside"):
            with self.assertRaises(ValueError):
                safe_path(self.root, name)
        (self.root / "escape").symlink_to("/tmp")
        with self.assertRaises(ValueError):
            safe_path(self.root, "escape/file")


if __name__ == "__main__":
    unittest.main()
