"""Versioned local hook evidence; runnable without starting the Control API."""

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft7Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[4]


class WorkBuddyPendingContracts(unittest.TestCase):
    def test_go_readonly_migration_preview(self):
        sample = json.loads((ROOT / "apps/agentshield/testdata/contracts/local-state-migration-preview.json").read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "packages/contracts/local-state-migration-preview.v1.schema.json").read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)
        validator = Draft7Validator(schema)
        validator.validate(sample)
        for patch in [{"invocation_binding": "a" * 64}, {"executable_path": "C:/candidate.exe"}, {"executable_sha256": "invalid"}, {"service_stop_required": False}, {"backup_bytes": -1}, {"windows_profile": "ready"}, {"grant_approved": True}]:
            self.assertTrue(list(validator.iter_errors({**sample, **patch})), patch)
        validator.validate({**sample, "executable_path": "C:/fixture/candidate.exe", "executable_sha256": "a" * 64, "invocation_binding": "b" * 64})

    def test_go_local_failure_sample_and_legacy_separation(self):
        sample = json.loads((ROOT / "apps/agentshield/testdata/contracts/receipt-local-failure-v2.json").read_text(encoding="utf-8"))
        schema = json.loads((ROOT / "packages/contracts/receipt.v2.schema.json").read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)
        validator = Draft7Validator(schema, format_checker=FormatChecker())
        validator.validate(sample)
        self.assertNotEqual(sample["issued_at"], sample["local_origin"]["recorded_at"])
        for field in ["schema_version", "local_origin", "record_type"]:
            bad = copy.deepcopy(sample)
            del bad[field]
            self.assertTrue(list(validator.iter_errors(bad)), field)
        for patch in [{"authority_status": "valid"}, {"policy_action": "allow"}, {"effective_action": "allow"},
                      {"record_type": "decision"}, {"action": "deny"}, {"token": "secret"}]:
            self.assertTrue(list(validator.iter_errors({**sample, **patch})), patch)
        legacy = json.loads((ROOT / "packages/contracts/receipt.schema.json").read_text(encoding="utf-8"))
        self.assertTrue(list(Draft7Validator(legacy).iter_errors(sample)))

    def test_pending_fields_are_bounded_unsigned_and_no_raw_parameters(self):
        sample = json.loads((ROOT / "apps/agentshield/testdata/contracts/receipt-local-failure-v2.json").read_text(encoding="utf-8"))["local_origin"]
        schema = json.loads((ROOT / "packages/contracts/pending-decision.v2.schema.json").read_text(encoding="utf-8"))
        Draft7Validator.check_schema(schema)
        validator = Draft7Validator(schema, format_checker=FormatChecker())
        validator.validate(sample)
        for field in schema["required"]:
            self.assertTrue(list(validator.iter_errors({k: v for k, v in sample.items() if k != field})), field)
        for patch in [{"signed": True}, {"origin": "online_policy"}, {"params": {}}, {"token": "secret"},
                      {"tool": "x" * 257}, {"reason_code": "raw failure message"}, {"stage": "unknown"},
                      {"native_call_id": "unverified"}, {"recorded_at": "invalid"}]:
            self.assertTrue(list(validator.iter_errors({**sample, **patch})), patch)


if __name__ == "__main__":
    unittest.main()
