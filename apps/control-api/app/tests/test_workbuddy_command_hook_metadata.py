"""Source-derived WorkBuddy hook shapes; these are not native event captures."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator


CONTRACTS = Path(__file__).parents[4] / "packages" / "contracts"


@pytest.mark.parametrize("event", ["pre", "post"])
def test_workbuddy_source_hook_metadata(event: str) -> None:
    schema = json.loads((CONTRACTS / "workbuddy-command-hook-input.v1.schema.json").read_text())
    Draft7Validator.check_schema(schema)
    validator = Draft7Validator(schema)
    fixtures = json.loads(
        (CONTRACTS / "fixtures" / "workbuddy_command_hook_input_v1_source_examples.json").read_text()
    )
    sample = fixtures[event]
    validator.validate(sample)
    for field in ["generation_id", "model", "client", "version"]:
        for valid in ["", "x" * 4096]:
            validator.validate({**sample, field: valid})
        for invalid in [None, True, 1, [], {}, "x" * 4097]:
            assert list(validator.iter_errors({**sample, field: invalid})), field
        omitted = {key: value for key, value in sample.items() if key != field}
        validator.validate(omitted)
        assert list(validator.iter_errors({**omitted, field.upper(): "alias"}))
    assert list(validator.iter_errors({**sample, "retry_of": "forged"}))


def test_workbuddy_private_correlation_contract() -> None:
    schema = json.loads((CONTRACTS / "workbuddy-hook-correlation.v1.schema.json").read_text())
    Draft7Validator.check_schema(schema)
    validator = Draft7Validator(schema)
    sample = json.loads(
        (CONTRACTS / "fixtures" / "workbuddy_hook_correlation_v1_example.json").read_text()
    )
    validator.validate(sample)
    for field in schema["required"]:
        assert list(validator.iter_errors({k: v for k, v in sample.items() if k != field}))
        assert list(validator.iter_errors({**sample, field: None}))
    for secret in ["params", "result", "token", "signing_key", "allow"]:
        assert list(validator.iter_errors({**sample, secret: "must-not-be-persisted"}))
    for kind in ["pre", "decision", "consume", "post", "complete", "terminal"]:
        validator.validate({**sample, "kind": kind})
    for patch in [
        {"kind": "effective"},
        {"outcome": "approved"},
        {"schema_version": "workbuddy-hook-correlation/v99"},
        {"scope_digest": "x" * 64},
        {"tool_call_id": "raw-host-call"},
        {"action_id": "x" * 257},
    ]:
        assert list(validator.iter_errors({**sample, **patch}))
    for field in ["outcome", "action_id", "decision_receipt_id"]:
        assert list(validator.iter_errors({k: v for k, v in sample.items() if k != field}))
    assert list(validator.iter_errors({**sample, "outcome": "reserved"}))
