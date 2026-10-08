"""Synthetic Go recovery journal shape and independent state-binding checks."""
import base64
import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[4]
URI = "https://siq-agent-security.local/contracts/"


def sample():
    return json.loads((ROOT / "edge/agent/testdata/enterprise-upgrade-journal.synthetic.json").read_text())


def validator():
    registry = Registry()
    for name in ["enterprise-install-plan", "enterprise-upgrade-review"]:
        schema = json.loads((ROOT / f"packages/contracts/{name}.v1.schema.json").read_text())
        schema["$id"] = URI + f"{name}.v1.schema.json"
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    schema = json.loads((ROOT / "packages/contracts/enterprise-upgrade-journal.v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=registry)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def test_go_journal_contract_and_independent_hashes():
    document = sample()
    validator().validate(document)
    intent = document["intent"]
    canonical = json.dumps(intent, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    assert digest(canonical) == document["confirmation_sha256"]
    old_raw = base64.b64decode(document["original_plan_bytes"], validate=True)
    old_plan = json.loads(old_raw)
    assert old_plan == intent["from"]["plan"]
    # Only known synthetic component credentials; never read real device state.
    state = {
        "control_plane_url": intent["control_plane_origin"],
        "device_identity": "synthetic-device",
        "secret": "SYNTHETIC-PRIVATE-DEVICE-TOKEN",
        "environment_id": intent["environment_id"],
        "signer_seed": "SYNTHETIC-PRIVATE-SEED",
    }
    assert digest(compact(state)) == document["state_baseline_sha256"]
    for plan, field in [(old_plan, "restored_state_sha256"), (intent["to"]["plan"], "target_state_sha256")]:
        state["discovery_plan"] = plan
        state["discovery_plan_sha256"] = digest(compact(plan))
        assert digest(json.dumps(state, ensure_ascii=False, indent=2).encode()) == document[field]
    assert document["target_state_sha256"] != document["restored_state_sha256"]
    assert "SYNTHETIC-PRIVATE" not in json.dumps(document)
    assert "SYNTHETIC-PRIVATE" not in old_raw.decode()


@pytest.mark.parametrize("field", [
    "schema_version", "intent", "confirmation_sha256", "state_baseline_sha256",
    "original_plan_bytes", "restored_state_sha256", "target_state_sha256",
])
def test_required_recovery_binding(field):
    document = sample()
    del document[field]
    assert list(validator().iter_errors(document))


@pytest.mark.parametrize("field,value", [
    ("schema_version", "enterprise-upgrade-completed/v1"),
    ("target_state_sha256", "bad"), ("original_plan_bytes", "not base64!"),
    ("secret", "forbidden"), ("installed", True), ("business_permissions_granted", True),
])
def test_forbidden_shape(field, value):
    document = sample()
    document[field] = value
    assert list(validator().iter_errors(document))


def test_nested_intent_and_plan_contracts():
    document = sample()
    changed = copy.deepcopy(document)
    changed["intent"]["to"]["plan"]["purpose"] = "grant_business_permission"
    assert list(validator().iter_errors(changed))
    changed = copy.deepcopy(document)
    changed["intent"]["from"]["unit_sha256"] = "0"
    assert list(validator().iter_errors(changed))
