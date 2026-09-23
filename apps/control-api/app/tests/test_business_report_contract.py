"""Same business operation vectors as the Go descriptor; no business imports."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[4]


def test_fixed_business_call_shared_vectors():
    schema = json.loads((ROOT / "packages/contracts/siq-research-business-call.v1.schema.json").read_bytes())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    cases_path = ROOT / "apps/agentshield/testdata/contracts/siq-research-business-call-v1-cases.json"
    cases = json.loads(cases_path.read_bytes())
    for case in cases:
        assert validator.is_valid(case["call"]) is case["valid"], case["name"]
