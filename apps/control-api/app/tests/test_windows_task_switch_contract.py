"""Windows switch wire evidence; fixture signatures use a public test-only seed."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parents[4]
SAMPLES = ROOT / "apps/agentshield/testdata/contracts"
SCHEMA = ROOT / "packages/contracts/local-windows-task-switch.v1.schema.json"


def test_windows_switch_signed_go_fixture() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    validator = Draft7Validator(schema)
    plan = json.loads((SAMPLES / "local-windows-task-switch.json").read_text(encoding="utf-8"))
    validator.validate(plan)
    key = Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32).public_key()
    for document in (plan, plan["source_record"], plan["target_record"]):
        unsigned = {k: v for k, v in document.items() if k != "signature"}
        key.verify(bytes.fromhex(document["signature"]), json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode())
    for side in ("source", "target"):
        assert plan[f"{side}_record"]["xml_sha256"] == hashlib.sha256(plan[f"{side}_xml"].encode()).hexdigest()
    for field in ("task_name", "user_sid", "instance_id", "state_directory_id"):
        assert plan["source_record"][field] == plan["target_record"][field]
    assert plan["source_xml"] != plan["target_xml"]
    for field in schema["required"]:
        assert list(validator.iter_errors({k: v for k, v in plan.items() if k != field}))
        assert list(validator.iter_errors({**plan, field: None}))
    assert list(validator.iter_errors({**plan, "unknown": True}))


@pytest.mark.parametrize("field", ["source_record", "target_record", "binary_bindings"])
def test_windows_switch_nested_schema_boundaries(field: str) -> None:
    validator = Draft7Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    plan = json.loads((SAMPLES / "local-windows-task-switch.json").read_text(encoding="utf-8"))
    for nested in plan[field]:
        bad = copy.deepcopy(plan)
        del bad[field][nested]
        assert list(validator.iter_errors(bad))
        bad[field][nested] = None
        assert list(validator.iter_errors(bad))
    plan[field]["unknown"] = True
    assert list(validator.iter_errors(plan))
