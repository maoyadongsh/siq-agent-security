"""Versioned approval/closed process tool shapes, validated by existing schemas."""

import json
import unittest
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[4]


class ApprovalContractsTest(unittest.TestCase):
    def test_closed_report_tool_and_admin_request_shapes(self):
        for name, valid, invalid in (
            ("report-verification-tool", {"path": "/workspace/report.md"},
             [{"path": "relative"}, {"path": "/workspace/report.md", "command": "substitution"}, {"path": 1}]),
            ("grant-tool-approval", {"schema_version": "grant-tool-approval/v1", "expected_revision": 0,
                                     "actor_id": "operator", "tools": ["verify_report"]},
             [{"schema_version": "grant-tool-approval/v1", "expected_revision": 0,
               "actor_id": "operator", "tools": []}]),
        ):
            schema = json.loads((ROOT / "packages/contracts" / (name + ".schema.json")).read_text())
            jsonschema.Draft7Validator.check_schema(schema)
            validator = jsonschema.Draft7Validator(schema)
            validator.validate(valid)
            for value in invalid:
                self.assertTrue(list(validator.iter_errors(value)))


if __name__ == "__main__":
    unittest.main()
