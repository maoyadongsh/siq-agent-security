"""Schema/producer parity using existing locked Control API jsonschema dependency."""

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("platform_acceptance", ROOT / "scripts/personal-experience/platform_acceptance.py")
a = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(a)


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "packages/contracts/personal-platform-acceptance.v1.schema.json").read_text())
        self.report = json.loads((ROOT / "packages/contracts/personal-platform-acceptance-report.v1.schema.json").read_text())

    def test_schemas_are_valid_and_producer_outputs_match(self):
        for schema in (self.manifest, self.report):
            Draft202012Validator.check_schema(schema)
        bundle = a.template("a" * 40)
        Draft202012Validator(self.manifest).validate(bundle)
        with tempfile.TemporaryDirectory() as directory:
            report = a.verify(bundle, Path(directory), "a" * 40)
        Draft202012Validator(self.report).validate(report)

    def test_schema_rejects_wrong_identity_or_fields(self):
        original = a.template("a" * 40)
        for key, value in (("schema_version", "v0"), ("candidate_sha", "main"), ("source_dirty", True), ("token", "synthetic")):
            bundle = copy.deepcopy(original)
            bundle[key] = value
            self.assertFalse(Draft202012Validator(self.manifest).is_valid(bundle))

    def test_schema_rejects_pass_without_evidence(self):
        bundle = a.template("a" * 40)
        bundle["cases"][0]["checks"]["normal_execution"].update(status="pass", method="native_cli", reason=None)
        self.assertFalse(Draft202012Validator(self.manifest).is_valid(bundle))

    def test_schema_and_producer_capability_names_match(self):
        self.assertEqual(set(self.manifest["$defs"]["case"]["properties"]["checks"]["required"]), set(a.CHECKS))
        self.assertEqual(set(self.manifest["$defs"]["case"]["properties"]["platform"]["enum"]), set(a.PLATFORMS))


if __name__ == "__main__":
    unittest.main()
