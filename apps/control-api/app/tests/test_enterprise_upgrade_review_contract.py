"""Consumer checks for an explicitly synthetic Go upgrade-review wire sample."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[4]


def sample():
    return json.loads((ROOT / "edge/agent/testdata/enterprise-upgrade-review.synthetic.json").read_text())


def validator():
    plan = json.loads((ROOT / "packages/contracts/enterprise-install-plan.v1.schema.json").read_text())
    uri = "https://siq-agent-security.local/contracts/enterprise-install-plan.v1.schema.json"
    # Register the unchanged plan shape under the contract's canonical file URI.
    plan["$id"] = uri
    registry = Registry().with_resource(uri, Resource.from_contents(plan))
    schema = json.loads((ROOT / "packages/contracts/enterprise-upgrade-review.v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=registry)


def test_go_wire_shape_and_python_canonical_confirmation():
    document = sample()
    validator().validate(document)
    raw = json.dumps(document["intent"], sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    assert hashlib.sha256(raw).hexdigest() == document["confirmation_sha256"]
    assert "评估角色" in json.dumps(document["intent"], ensure_ascii=False)
    assert document["intent"]["from"]["plan"]["release_version"] != document["intent"]["to"]["plan"]["release_version"]
    assert document["installed"] is False and document["connector_capabilities_verified"] is False
    assert "SYNTHETIC-PRIVATE" not in json.dumps(document)


@pytest.mark.parametrize("field,value", [
    ("schema_version", "enterprise-upgrade-review/v2"), ("status", "installed"),
    ("publisher_signature_verified", False), ("publisher_signature_verified", 1),
    ("service_activity", "stopped"), ("connector_capabilities_verified", True),
    ("requires_explicit_confirmation", False), ("installed", True), ("business_permissions_granted", True),
])
def test_shape_rejects_changed_security_meaning(field, value):
    document = sample()
    document[field] = value
    assert list(validator().iter_errors(document))


def test_exact_fields_and_nested_plan_contract():
    original = sample()
    changed = copy.deepcopy(original)
    del changed["intent"]["state_file_sha256"]
    assert list(validator().iter_errors(changed))
    changed = copy.deepcopy(original)
    changed["intent"]["device_secret"] = "forbidden"
    assert list(validator().iter_errors(changed))
    changed = copy.deepcopy(original)
    changed["intent"]["to"]["plan"]["purpose"] = "grant_business_permission"
    assert list(validator().iter_errors(changed))
