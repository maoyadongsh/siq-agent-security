"""Structural candidates for #39; these are not cryptographically signed samples.

Legacy fixtures remain untouched. New shapes use deliberately zero signatures,
so schema acceptance must never be described as successful authority validation.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

ROOT = Path(__file__).parents[4]
CONTRACTS = ROOT / "packages" / "contracts"
FIXTURES = ROOT / "apps" / "agentshield" / "testdata" / "contracts"
PROFILE = "windows-local-drive/v1"


def _read(name: str) -> dict:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    if "signature" in value:
        value["signature"] = "0" * 128
    if "digest" in value:
        value["digest"] = "0" * 64
    return value


def _validator(name: str) -> Draft7Validator:
    schema = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def _candidate(kind: str) -> dict:
    if kind == "intent-contract.v4":
        value = _read("intent-contract.v2.sample.json")
        value.update(schema_version="intent/v4", authority_kind="instance_permission", filesystem_profile=PROFILE)
        value["authority"]["issuer"] = "local-runtime-identity"
        return value
    if kind == "grant.v2":
        value = _read("grant.pending.sample.json")
        value.update(schema_version="grant/v2", filesystem_profile=PROFILE, filesystem_bindings={})
        return value
    if kind == "local-runtime-identity-create.v2":
        value = _read("local-runtime-identity-create.json")
        value.update(schema_version="local-runtime-identity-create/v2", confirm_filesystem_profile=True)
        return value
    if kind == "local-runtime-identity-issued.v2":
        value = _read("local-runtime-identity-issued.json")
        value["schema_version"] = "local-runtime-identity-issued/v2"
        target = value["identity"]
    elif kind == "intent-grant-binding.v2":
        value = _read("intent-grant-binding.json")
        value["schema_version"] = "intent-grant-binding/v2"
        target = value
    else:
        assert kind == "local-runtime-identity.v2"
        value = _read("local-runtime-identity.json")
        value["schema_version"] = "local-runtime-identity/v2"
        target = value
    if kind != "intent-grant-binding.v2":
        target["filesystem_profile"] = PROFILE
    target["grant_ref"]["permission_digest_schema"] = "grant-permissions/v2"
    return value


@pytest.mark.parametrize("kind", [
    "intent-contract.v4", "grant.v2", "local-runtime-identity.v2",
    "local-runtime-identity-create.v2", "local-runtime-identity-issued.v2", "intent-grant-binding.v2",
])
def test_new_resource_contract_required_fields_and_closed_shape(kind: str) -> None:
    validator = _validator(kind + ".schema.json")
    value = _candidate(kind)
    validator.validate(value)
    for field in validator.schema["required"]:
        missing = copy.deepcopy(value)
        missing.pop(field)
        assert list(validator.iter_errors(missing)), field
    assert list(validator.iter_errors({**value, "untrusted_profile": PROFILE}))


def test_new_managed_intent_cannot_encode_provenance_downgrade() -> None:
    validator = _validator("intent-contract.v4.schema.json")
    value = _candidate("intent-contract.v4")
    for patch in [
        {"schema_version": "intent/v3"},
        {"authority_kind": "task_intent"},
        {"filesystem_profile": "posix/v1"},
        {"filesystem_profile": "unknown/v1"},
        {"provenance_constraints": []},
        {"effect_requirements": []},
        {"authority": {**value["authority"], "issuer": "model"}},
    ]:
        assert list(validator.iter_errors({**value, **patch})), patch
    for operator in ["equals", "prefix"]:
        validator.validate({**value, "resource_constraints": [{
            "domain": "filesystem", "operator": operator, "value": "C:/Fixture",
        }]})
    for operator in ["regex", "suffix"]:
        assert list(validator.iter_errors({**value, "resource_constraints": [{
            "domain": "filesystem", "operator": operator, "value": ".*",
        }]}))


def test_new_identity_confirmation_cannot_select_a_profile() -> None:
    validator = _validator("local-runtime-identity-create.v2.schema.json")
    value = _candidate("local-runtime-identity-create.v2")
    for patch in [
        {"confirm_filesystem_profile": False},
        {"confirm_filesystem_profile": "true"},
        {"filesystem_profile": PROFILE},
    ]:
        assert list(validator.iter_errors({**value, **patch}))


@pytest.mark.parametrize("kind", [
    "local-runtime-identity.v2", "local-runtime-identity-issued.v2", "intent-grant-binding.v2",
])
def test_new_binding_cannot_reinterpret_a_v1_permission_digest(kind: str) -> None:
    validator = _validator(kind + ".schema.json")
    for digest_schema in [None, "grant-permissions/v1", "unknown/v1"]:
        value = _candidate(kind)
        target = value["identity"] if "identity" in value else value
        if digest_schema is None:
            target["grant_ref"].pop("permission_digest_schema")
        else:
            target["grant_ref"]["permission_digest_schema"] = digest_schema
        assert list(validator.iter_errors(value))


@pytest.mark.parametrize("schema,fixture,patch", [
    ("intent-contract.v2.schema.json", "intent-contract.v2.sample.json", {"filesystem_profile": PROFILE}),
    ("intent-contract.v3.schema.json", "intent-contract.v3.sample.json", {"filesystem_profile": PROFILE}),
    ("grant.schema.json", "grant.pending.sample.json", {"filesystem_profile": PROFILE}),
    ("local-runtime-identity.v1.schema.json", "local-runtime-identity.json", {"filesystem_profile": PROFILE}),
])
def test_legacy_shapes_stay_closed_to_profile_injection(schema: str, fixture: str, patch: dict) -> None:
    validator = _validator(schema)
    value = _read(fixture)
    validator.validate(value)
    assert list(validator.iter_errors({**value, **patch}))


@pytest.mark.parametrize("kind", ["local-state-windows-profile-plan", "local-state-windows-profile-done", "local-state-windows-profile-result"])
def test_state_profile_transition_contracts(kind: str) -> None:
    validator = _validator(kind + ".v1.schema.json")
    value = _read(kind + ".json")
    validator.validate(value)
    for field in validator.schema["required"]:
        missing = copy.deepcopy(value)
        missing.pop(field)
        assert list(validator.iter_errors(missing)), field
    assert list(validator.iter_errors({**value, "unknown": True}))


@pytest.mark.parametrize(("fixture", "schema"), [
    ("local-state-status-reader3.json", "local-state-status.v1.schema.json"),
    ("skill-manifest.v3.reader3.sample.json", "skill-manifest.v3.schema.json"),
])
def test_reader3_producer_fixtures(fixture: str, schema: str) -> None:
    _validator(schema).validate(_read(fixture))
