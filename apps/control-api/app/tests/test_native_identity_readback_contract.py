"""Versioned native identity readbacks; metadata never proves active protection."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[4]
SAMPLES = ROOT / "apps/agentshield/testdata/contracts"
CASES = [
    ("local-runtime-identities.v3", "local-runtime-identities-native-v3", "items", "v2"),
    ("local-runtime-identity-issued.v3", "local-runtime-identity-issued-native-v3", "identity", "v1"),
    ("local-runtime-identity-self.v2", "local-runtime-identity-self-native-v2", None, "v1"),
    ("local-runtime-session-enrolled.v3", "local-runtime-session-enrolled-native-v3", None, "v1"),
    ("local-runtime-request-identity-issued.v2", "local-runtime-request-identity-issued-native-v2", "identity", "v1"),
]


def validator(name):
    schema = json.loads((ROOT / "packages/contracts" / f"{name}.schema.json").read_text())
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema, format_checker=FormatChecker())


def subject(doc, field):
    return doc["items"][0] if field == "items" else doc[field] if field else doc


@pytest.mark.parametrize(("name", "sample", "field", "old"), CASES)
def test_native_readback_shapes_and_downgrade_refusal(name, sample, field, old):
    check = validator(name)
    doc = json.loads((SAMPLES / (sample + ".sample.json")).read_text())
    check.validate(doc)
    if "request" in doc:
        assert doc["identity"]["identity_id"] != doc["request"]["parent_identity_id"]
    for key in check.schema["required"]:
        bad = copy.deepcopy(doc)
        del bad[key]
        with pytest.raises(ValidationError):
            check.validate(bad)
    for patch in [
        {"native_skill_policy": None}, {"native_skill_policy": {}},
        {"native_skill_policy": {"mode": "optional", "runtime_artifact_sha256": "c" * 64}},
        {"native_skill_policy": {"mode": "required", "runtime_artifact_sha256": "unknown"}},
        {"runtime_state": "verified"}, {"platform": "openclaw"},
        {"credential_hash": "a" * 64}, {"signature": "a" * 128},
    ]:
        bad = copy.deepcopy(doc)
        subject(bad, field).update(patch)
        with pytest.raises(ValidationError):
            check.validate(bad)
    bad = copy.deepcopy(doc)
    del subject(bad, field)["native_skill_policy"]
    with pytest.raises(ValidationError):
        check.validate(bad)
    # Relabeling native metadata as a legacy response must not hide the policy.
    legacy = name.rsplit(".", 1)[0] + "." + old
    doc["schema_version"] = name.rsplit(".", 1)[0] + "/" + old
    with pytest.raises(ValidationError):
        validator(legacy).validate(doc)


def test_native_mixed_list_preserves_platform_boundaries_and_requires_native_item():
    doc = json.loads((SAMPLES / "local-runtime-identities-native-v3.sample.json").read_text())
    legacy = json.loads((SAMPLES / "local-runtime-identities.json").read_text())["items"][0]
    windows = copy.deepcopy(legacy)
    windows["platform"] = "workbuddy"
    windows["filesystem_profile"] = "windows-local-drive/v1"
    windows["grant_ref"]["permission_digest_schema"] = "grant-permissions/v2"
    doc["items"].extend([legacy, windows])
    check = validator("local-runtime-identities.v3")
    check.validate(doc)
    check.validate(doc | {"items": list(reversed(doc["items"]))})
    for items in [[], [legacy, windows], [doc["items"][0]] * 513]:
        with pytest.raises(ValidationError):
            check.validate(doc | {"items": items})
