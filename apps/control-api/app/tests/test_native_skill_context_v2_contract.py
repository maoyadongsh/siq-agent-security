"""Independent schema/signature readback of the new Go v2 document.

This is not an issuance endpoint or proof of live installation authority.
"""

import copy
import json
from pathlib import Path

import jsonschema
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[4]
SAMPLE = ROOT / "apps/agentshield/testdata/contracts/skill-execution-context-v2.sample.json"
SCHEMA = ROOT / "packages/contracts/skill-execution-context.v2.schema.json"


def _verify(doc):
    value = copy.deepcopy(doc)
    signature = bytes.fromhex(value.pop("signature"))
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    # Public test vector; same fixed synthetic seed as the existing v1 fixtures.
    public = Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32).public_key()
    public.verify(signature, raw)


def test_native_skill_context_v2_go_sample_and_v1_separation():
    doc = json.loads(SAMPLE.read_text())
    schema = json.loads(SCHEMA.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(doc)
    _verify(doc)
    old = json.loads((SCHEMA.parent / "skill-execution-context.v1.schema.json").read_text())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, old)


@pytest.mark.parametrize("field", ["agent_authority", "loader", "schema_version", "signature"])
def test_native_skill_context_v2_missing_fields_refused(field):
    doc = json.loads(SAMPLE.read_text())
    del doc[field]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, json.loads(SCHEMA.read_text()))


@pytest.mark.parametrize("section", [None, "agent_authority", "loader", "subject"])
def test_native_skill_context_v2_unknown_fields_refused(section):
    doc = json.loads(SAMPLE.read_text())
    target = doc if section is None else doc[section]
    target["model_authorized"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, json.loads(SCHEMA.read_text()))


@pytest.mark.parametrize(("section", "field", "value"), [
    ("agent_authority", "grant_id", "another-agent-grant"),
    ("agent_authority", "grant_digest", "8" * 64),
    ("authority", "grant_id", "another-skill-grant"),
    ("loader", "load_id", "nload-" + "8" * 32),
    ("loader", "skill_file_sha256", "8" * 64),
    ("loader", "runtime_artifact_sha256", "8" * 64),
    ("subject", "task_id", "another-native-task"),
])
def test_native_skill_context_v2_tampering_invalidates_signature(section, field, value):
    doc = json.loads(SAMPLE.read_text())
    doc[section][field] = value
    jsonschema.validate(doc, json.loads(SCHEMA.read_text()))
    with pytest.raises(InvalidSignature):
        _verify(doc)


def test_native_skill_revocation_v2_go_sample():
    doc = json.loads(SAMPLE.with_name("skill-execution-context-revocation-v2.sample.json").read_text())
    schema = json.loads(SCHEMA.with_name("skill-execution-context-revocation.v2.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(doc)
    _verify(doc)
    assert doc["context_signature"] == json.loads(SAMPLE.read_text())["signature"]
    old = json.loads(SCHEMA.with_name("skill-execution-context-revocation.v1.schema.json").read_text())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, old)
    doc["context_signature"] = "f" * 128
    with pytest.raises(InvalidSignature):
        _verify(doc)
    del doc["context_signature"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, schema)
