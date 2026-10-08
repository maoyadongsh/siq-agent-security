"""Explicitly synthetic completion wire; configuration is not service activation."""
import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[4]
URI = "https://siq-agent-security.local/contracts/"


def validator(name="enterprise-upgrade-apply"):
    registry = Registry()
    for contract in ["enterprise-install-plan", "enterprise-upgrade-review", "enterprise-upgrade-journal"]:
        schema = json.loads((ROOT / f"packages/contracts/{contract}.v1.schema.json").read_text())
        schema["$id"] = URI + contract + ".v1.schema.json"
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    schema = json.loads((ROOT / f"packages/contracts/{name}.v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=registry)


def sample():
    return json.loads((ROOT / "edge/agent/testdata/enterprise-upgrade-apply.synthetic.json").read_text())


def test_go_completion_configuration_only():
    document = sample()
    validator().validate(document)
    assert document["direction"] == "target"
    assert document["state_sha256"] == document["journal"]["target_state_sha256"]
    assert document["unit_sha256"] == document["journal"]["intent"]["to"]["unit_sha256"]
    assert document["service_started"] is False and document["business_permissions_granted"] is False
    assert "SYNTHETIC-PRIVATE" not in json.dumps(document)


@pytest.mark.parametrize("field,value", [
    ("status", "installed_and_running"), ("direction", "automatic"),
    ("state_sha256", "wrong"), ("unit_sha256", "wrong"),
    ("service_started", True), ("business_permissions_granted", True),
    ("service_started", 0), ("business_permissions_granted", 0),
    ("device_secret", "forbidden"),
])
def test_completion_rejects_broader_claims(field, value):
    document = sample()
    document[field] = value
    assert list(validator().iter_errors(document))


def test_required_completion_and_nested_fields():
    document = sample()
    for field in document:
        changed = copy.deepcopy(document)
        del changed[field]
        assert list(validator().iter_errors(changed))
    document["journal"]["intent"]["to"]["plan"]["purpose"] = "grant_business_permission"
    assert list(validator().iter_errors(document))


def test_capability_shape_requires_known_containment_protocol():
    document = {
        "schema_version": "enterprise-upgrade-capabilities/v1", "version": "probe-fixture",
        "pending_protocol": "enterprise-upgrade-pending/v1",
        "confirmation_protocol": "enterprise-upgrade-intent/v1", "task_lock": True,
    }
    schema = validator("enterprise-upgrade-capabilities")
    schema.validate(document)
    for field, value in [("task_lock", False), ("task_lock", 1), ("pending_protocol", "unknown")]:
        changed = {**document, field: value}
        assert list(schema.iter_errors(changed))
