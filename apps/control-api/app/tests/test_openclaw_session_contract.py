"""OpenClaw key+epoch identity: shared Go/JS vector and shape rejection."""

import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

ROOT = Path(__file__).parents[4]


def test_native_session_vector():
    schema = json.loads((ROOT / "packages/contracts/openclaw-native-session.v1.schema.json").read_text())
    vector = json.loads((ROOT / "apps/agentshield/testdata/contracts/openclaw-native-session.json").read_text())
    Draft7Validator.check_schema(schema)
    Draft7Validator(schema).validate(vector)


@pytest.mark.parametrize("value", ["", "agent:fixture:main", "openclaw-default", "openclaw-session/v2:" + "a" * 64,
                                  "openclaw-session/v1:" + "A" * 64, "openclaw-session/v1:" + "a" * 63, None, {}])
def test_native_session_rejects_legacy_or_malformed(value):
    schema = json.loads((ROOT / "packages/contracts/openclaw-native-session.v1.schema.json").read_text())
    assert list(Draft7Validator(schema).iter_errors(value))
