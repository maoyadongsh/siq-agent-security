"""Offline versioned management readbacks; history is not live authority."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[4]
CONTRACTS = ROOT / "packages/contracts"
SAMPLES = ROOT / "apps/agentshield/testdata/contracts"
CASES = [
    ("local-native-skill-context-record.v1", "local-native-skill-context-record-v1"),
    ("local-skill-context-management.v2", "local-skill-context-management-v2"),
    ("local-skill-execution-context-revoke.v2", "local-skill-execution-context-revoke-v2"),
]


def validator(name):
    names = [n for n, _ in CASES] + ["skill-execution-context.v2", "skill-execution-context-revocation.v2"]
    schemas = [json.loads((CONTRACTS / (n + ".schema.json")).read_text()) for n in names]
    for schema in schemas:
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources([(schema["$id"], Resource.from_contents(schema)) for schema in schemas])
    selected = json.loads((CONTRACTS / (name + ".schema.json")).read_text())
    return Draft202012Validator(selected, registry=registry, format_checker=FormatChecker())


@pytest.mark.parametrize(("name", "sample"), CASES)
def test_management_samples_are_strict_and_versioned(name, sample):
    check = validator(name)
    doc = json.loads((SAMPLES / (sample + ".sample.json")).read_text())
    check.validate(doc)
    for key in check.schema["required"]:
        wrong = copy.deepcopy(doc)
        del wrong[key]
        with pytest.raises(ValidationError):
            check.validate(wrong)
    for extra in ["effective", "credential", "model_authorized"]:
        with pytest.raises(ValidationError):
            check.validate(doc | {extra: True})
    if "revocation" in doc:
        check.validate(doc | {"revocation": None})
        for key in ("context", "revocation"):
            wrong = copy.deepcopy(doc)
            wrong[key]["schema_version"] = wrong[key]["schema_version"].replace("/v2", "/v1")
            with pytest.raises(ValidationError):
                check.validate(wrong)


@pytest.mark.parametrize("patch", [
    {"schema_version": "local-skill-execution-context-revoke/v1"},
    {"expected_context_signature": "a" * 64}, {"confirm_revoke": False},
    {"actor_id": ""}, {"grant_id": "forged"},
])
def test_native_revoke_requires_exact_confirmed_v2_request(patch):
    doc = json.loads((SAMPLES / "local-skill-execution-context-revoke-v2.sample.json").read_text())
    with pytest.raises(ValidationError):
        validator("local-skill-execution-context-revoke.v2").validate(doc | patch)


def test_native_history_page_bounds_and_no_legacy_context():
    check = validator("local-skill-context-management.v2")
    doc = json.loads((SAMPLES / "local-skill-context-management-v2.sample.json").read_text())
    check.validate(doc | {"contexts": [], "next_after": ""})
    check.validate(doc | {"contexts": doc["contexts"] * 64, "next_after": doc["contexts"][0]["context"]["context_id"]})
    for patch in [{"contexts": doc["contexts"] * 65}, {"next_after": "../other"}]:
        with pytest.raises(ValidationError):
            check.validate(doc | patch)
    doc["contexts"][0]["context"] = json.loads((SAMPLES / "skill-execution-context.sample.json").read_text())
    with pytest.raises(ValidationError):
        check.validate(doc)
