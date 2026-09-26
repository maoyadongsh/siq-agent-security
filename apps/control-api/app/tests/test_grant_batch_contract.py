"""The batch revoke contract is additive and never authorizes bulk approval."""
import copy
import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[4]


def test_batch_request_contract():
    schema = json.loads((ROOT / "packages/contracts/grant-batch-revoke.v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    sample = json.loads((ROOT / "apps/agentshield/testdata/contracts/grant-batch-revoke.json").read_text())
    validator.validate(sample)
    for invalid in ({**sample, "action": "approve"}, {**sample, "targets": []},
                    {**sample, "targets": sample["targets"] * 2}, {**sample, "actor_id": " "}):
        assert list(validator.iter_errors(invalid))
    for field in sample:
        invalid = copy.deepcopy(sample)
        invalid.pop(field)
        assert list(validator.iter_errors(invalid))


@pytest.mark.parametrize("outcome", ["revoked", "already_revoked", "conflict", "unavailable"])
def test_batch_result_contract(outcome):
    schema = json.loads((ROOT / "packages/contracts/grant-batch-revoke.v1.schema.json").read_text())
    validator = Draft202012Validator(schema)
    validator.validate({"schema_version": "grant-batch-revoke-result/v1", "batch_id": "gb-" + "a" * 64,
                        "items": [{"grant_id": "fixture-grant", "status": outcome, "state_revision": 1}]})


def test_batch_real_wire_outputs():
    sample_path = os.environ.get("SIQ_BATCH_WIRE_SAMPLE")
    if not sample_path:
        pytest.skip("Set SIQ_BATCH_WIRE_SAMPLE to isolated browser output to validate live Go responses")
    schema = json.loads((ROOT / "packages/contracts/grant-batch-revoke.v1.schema.json").read_text())
    validator = Draft202012Validator(schema)
    samples = json.loads(Path(sample_path).read_text())
    assert len(samples) == 3
    for sample in samples:
        validator.validate(sample)
