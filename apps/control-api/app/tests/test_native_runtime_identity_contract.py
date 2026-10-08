"""Public native-policy identity vectors; no live host/enrollment claims."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft7Validator, FormatChecker, ValidationError

ROOT = Path(__file__).resolve().parents[4]
SAMPLES = ROOT / "apps/agentshield/testdata/contracts"
CASES = [
    ("local-runtime-identity.v4", "local-runtime-identity-native-v4.sample.json"),
    ("local-runtime-identity.v5", "local-runtime-identity-native-v5.sample.json"),
    ("local-runtime-identity-create.v3", "local-runtime-identity-create-native-v3.sample.json"),
]


def canonical(doc):
    return json.dumps(doc, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def verify(doc):
    unsigned = {k: v for k, v in doc.items() if k != "signature"}
    # Known public synthetic seed; not a production credential.
    public = Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32).public_key()
    public.verify(bytes.fromhex(doc["signature"]), canonical(unsigned))


@pytest.mark.parametrize(("name", "sample"), CASES)
def test_native_identity_contract_and_negative_shapes(name, sample):
    schema = json.loads((ROOT / "packages/contracts" / f"{name}.schema.json").read_text())
    Draft7Validator.check_schema(schema)
    validator = Draft7Validator(schema, format_checker=FormatChecker())
    doc = json.loads((SAMPLES / sample).read_text())
    validator.validate(doc)
    for field in schema["required"]:
        for bad in [{k: v for k, v in doc.items() if k != field}, doc | {field: None}]:
            with pytest.raises(ValidationError):
                validator.validate(bad)
    policy = doc["native_skill_policy"]
    for bad in [
        {}, policy | {"mode": "optional"}, policy | {"mode": False},
        policy | {"runtime_artifact_sha256": "unknown"}, policy | {"extra": True},
    ]:
        with pytest.raises(ValidationError):
            validator.validate(doc | {"native_skill_policy": bad})
    if "signature" in doc:
        verify(doc)
        bad = copy.deepcopy(doc)
        bad["native_skill_policy"]["runtime_artifact_sha256"] = "d" * 64
        with pytest.raises(InvalidSignature):
            verify(bad)
        for old in ["local-runtime-identity.v1", "local-runtime-identity.v2", "local-runtime-identity.v3"]:
            old_schema = json.loads((ROOT / "packages/contracts" / f"{old}.schema.json").read_text())
            with pytest.raises(ValidationError):
                Draft7Validator(old_schema).validate(doc)


def test_native_request_identity_pins_parent_and_policy():
    root = json.loads((SAMPLES / "local-runtime-identity-native-v4.sample.json").read_text())
    child = json.loads((SAMPLES / "local-runtime-identity-native-v5.sample.json").read_text())
    verify(root)
    verify(child)
    scope = child["request_scope"]
    assert scope["parent_identity_id"] == root["identity_id"]
    unsigned = {k: v for k, v in root.items() if k != "signature"}
    assert scope["parent_sha256"] == hashlib.sha256(canonical(unsigned)).hexdigest()
    assert child["native_skill_policy"] == root["native_skill_policy"]
    assert child["grant_ref"] == root["grant_ref"]
    assert child["identity_id"] == "ri-" + hashlib.sha256(
        ("siq.runtime-request/v1\0" + root["identity_id"] + "\0" + scope["request_id"]).encode()
    ).hexdigest()[:32]
    assert child["session_ttl_seconds"] <= root["session_ttl_seconds"]
