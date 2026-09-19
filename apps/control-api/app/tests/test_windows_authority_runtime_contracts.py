"""Windows confirmation/list schemas; these inputs are structural fixtures only."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

ROOT = Path(__file__).parents[4]
CONTRACTS = ROOT / "packages" / "contracts"
FIXTURES = ROOT / "apps" / "agentshield" / "testdata" / "contracts"


def validator(name: str) -> Draft7Validator:
    schema = json.loads((CONTRACTS / name).read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def edit_request() -> dict:
    return {
        "schema_version": "grant-resource-edit/v2",
        "expected_revision": 0,
        "actor_id": "fixture-operator",
        "tools": ["read_file"],
        "network": [],
        "filesystem": {"read_only": ["C:/Approved"], "read_write": []},
        "models": [],
        "confirm_filesystem_profile": True,
    }


def test_windows_resource_edit_requires_explicit_confirmation_and_drive() -> None:
    check = validator("grant-resource-edit.v2.schema.json")
    value = edit_request()
    for path in ["C:/Approved", "D:\\Approved\\Input.txt"]:
        value["filesystem"]["read_only"] = [path]
        check.validate(value)
    for path in ["/Approved", "relative", "C:relative", "\\\\server\\share"]:
        value["filesystem"]["read_only"] = [path]
        assert list(check.iter_errors(value)), path
    for field in check.schema["required"]:
        value = edit_request()
        value.pop(field)
        assert list(check.iter_errors(value)), field
    for confirm in [False, None, "true", 1]:
        assert list(check.iter_errors({**edit_request(), "confirm_filesystem_profile": confirm}))


def test_mixed_identity_list_keeps_profiles_and_permission_domains_separate() -> None:
    record = json.loads((FIXTURES / "local-runtime-identity.json").read_text(encoding="utf-8"))
    for name in ["schema_version", "credential_hash", "signature"]:
        record.pop(name)
    record.update(status="issued", runtime_state="unverified")
    windows = copy.deepcopy(record)
    windows["filesystem_profile"] = "windows-local-drive/v1"
    windows["grant_ref"]["permission_digest_schema"] = "grant-permissions/v2"
    value = {"schema_version": "local-runtime-identities/v2", "items": [record, windows]}
    check = validator("local-runtime-identities.v2.schema.json")
    check.validate(value)
    for field in ["filesystem_profile", "permission_digest_schema"]:
        bad = copy.deepcopy(value)
        target = bad["items"][1] if field == "filesystem_profile" else bad["items"][1]["grant_ref"]
        target.pop(field)
        assert list(check.iter_errors(bad)), field
    bad = copy.deepcopy(value)
    bad["items"][0]["credential_hash"] = "0" * 64
    assert list(check.iter_errors(bad)), "credential hashes cannot enter management summaries"


@pytest.mark.parametrize("field", ["provenance_refs", "provenance_constraints", "effect_requirements"])
def test_managed_windows_envelope_cannot_claim_task_provenance(field: str) -> None:
    value = json.loads((FIXTURES / "intent-contract.v2.sample.json").read_text(encoding="utf-8"))
    value.update(
        schema_version="intent/v4",
        authority_kind="instance_permission",
        filesystem_profile="windows-local-drive/v1",
    )
    value.pop("provenance_refs", None)
    value["authority"]["issuer"] = "local-runtime-identity"
    check = validator("intent-contract.v4.schema.json")
    check.validate(value)
    assert list(check.iter_errors({**value, field: []}))
