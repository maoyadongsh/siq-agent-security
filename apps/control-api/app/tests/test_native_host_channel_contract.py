"""Native host packet contracts; peer authentication is an OS transport check."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, ValidationError

ROOT = Path(__file__).resolve().parents[4]


@pytest.mark.parametrize(("kind", "field"), [("event", "event"), ("response", "result")])
def test_native_host_packet_contract(kind, field):
    schema = json.loads((ROOT / f"packages/contracts/native-host-{kind}.v1.schema.json").read_text())
    Draft7Validator.check_schema(schema)
    validator = Draft7Validator(schema)
    value = json.loads((ROOT / f"apps/agentshield/testdata/contracts/native-host-{kind}-v1.sample.json").read_text())
    validator.validate(value)
    validator.validate(value | {"sequence": 9007199254740991})
    for key in schema["required"]:
        with pytest.raises(ValidationError):
            validator.validate({k: v for k, v in value.items() if k != key})
    for patch in [
        {"sequence": True}, {"sequence": 0}, {"sequence": 9007199254740992},
        {"sequence": "1"}, {"sequence": 1.5}, {"schema_version": "unknown"},
        {"extra": "claim"}, {field: None}, {field: []}, {field: {str(i): i for i in range(33)}},
    ]:
        with pytest.raises(ValidationError):
            validator.validate(value | patch)
