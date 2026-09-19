"""Instance baseline creation requires explicit scope and keeps replay state."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7

ROOT = Path(__file__).parents[4]
CONTRACTS = ROOT / "packages" / "contracts"
SAMPLES = ROOT / "apps" / "agentshield" / "testdata" / "contracts"


def checked(kind: str) -> tuple[Draft7Validator, dict]:
    registry = Registry()
    for name in ["grant.schema.json", "grant.v2.schema.json"]:
        schema = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
        resource = Resource(contents=schema, specification=DRAFT7)
        registry = registry.with_resource("https://siq.dev/contracts/" + name, resource)
        registry = registry.with_resource(schema["$id"], resource)
    schema = json.loads((CONTRACTS / f"{kind}.v1.schema.json").read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    value = json.loads((SAMPLES / f"{kind}.json").read_text(encoding="utf-8"))
    validator = Draft7Validator(schema, registry=registry)
    validator.validate(value)
    return validator, value


@pytest.mark.parametrize("kind", ["grant-instance-draft-create", "grant-instance-draft-created"])
def test_instance_draft_real_go_sample_and_exact_shape(kind: str) -> None:
    validator, value = checked(kind)
    for field in validator.schema["required"]:
        assert list(validator.iter_errors({k: v for k, v in value.items() if k != field})), field
        assert list(validator.iter_errors({**value, field: None})), field
    for field in ["subject_id", "platform", "path", "token", "effective"]:
        assert list(validator.iter_errors({**value, field: "forged"})), field


@pytest.mark.parametrize("field,value", [
    ("confirm_instance_scope", False), ("confirm_instance_scope", "true"), ("confirm_instance_scope", 1),
    ("actor_id", ""), ("actor_id", " operator"), ("actor_id", "operator "),
    ("actor_id", "operator\n"), ("actor_id", "\x00"), ("actor_id", "operator\x85"),
    ("actor_id", "a" * 129), ("instance_id", "hri-" + "a" * 32),
    ("request_id", "gd-" + "a" * 32), ("request_id", "gid-" + "A" * 32),
    ("admission_id", "adm-si-" + "a" * 64), ("admission_id", "../escape"),
])
def test_instance_draft_request_rejects_implicit_or_forged_scope(field: str, value: object) -> None:
    validator, good = checked("grant-instance-draft-create")
    assert list(validator.iter_errors({**good, field: value}))


def test_instance_draft_response_cannot_turn_skill_grant_into_baseline() -> None:
    validator, value = checked("grant-instance-draft-created")
    assert value["grant"]["status"] == "pending_approval"
    assert value["grant"]["approved_by"] is None and value["grant"]["effective_readback"] is None
    assert all(fact["state"] in {"declared", "inferred"} for fact in value["grant"]["facts"])
    for skill in [None, {"skill_id": "forged", "content_hash": "a" * 64}]:
        bad = copy.deepcopy(value)
        bad["grant"]["skill"] = skill
        assert list(validator.iter_errors(bad))
    for revision in [-1, True, 0.5]:
        assert list(validator.iter_errors({**value, "state_revision": revision}))
    bad = copy.deepcopy(value)
    bad["grant"]["status"] = "revoked"
    assert list(validator.iter_errors(bad)), "first creation must stay pending"
    bad["reused"] = True
    validator.validate(bad)


def test_instance_draft_replay_accepts_explicit_windows_profile_without_downgrade() -> None:
    validator, value = checked("grant-instance-draft-created")
    value["reused"] = True
    value["state_revision"] = 1
    grant = value["grant"]
    grant.update(schema_version="grant/v2", filesystem_profile="windows-local-drive/v1", filesystem_bindings={})
    grant["facts"] = [fact for fact in grant["facts"] if fact["domain"] != "filesystem"]
    validator.validate(value)
    grant.pop("schema_version")
    assert list(validator.iter_errors(value)), "legacy response must not smuggle a Windows interpretation"
