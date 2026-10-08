"""Independent verification of product-generated native call records; no live host claim."""

import copy
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[4]
SAMPLES = ROOT / "apps/agentshield/testdata/contracts"
CONTRACTS = ROOT / "packages/contracts"
CASES = [
    ("native-skill-managed-session-v1.sample.json", "native-skill-managed-session.v1.schema.json"),
    ("native-skill-call-no-skill-v1.sample.json", "native-skill-call.v1.schema.json"),
    ("native-skill-call-with-skill-v1.sample.json", "native-skill-call.v1.schema.json"),
]


def canonical(doc):
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def verify(doc):
    doc = copy.deepcopy(doc)
    signature = bytes.fromhex(doc.pop("signature"))
    # Public synthetic test seed, shared with the Go store fixture.
    Ed25519PrivateKey.from_private_bytes(bytes([9]) * 32).public_key().verify(signature, canonical(doc))


@pytest.mark.parametrize(("sample", "schema"), CASES)
def test_native_records_schema_signature_and_identity(sample, schema):
    doc = json.loads((SAMPLES / sample).read_text())
    contract = json.loads((CONTRACTS / schema).read_text())
    jsonschema.Draft202012Validator.check_schema(contract)
    jsonschema.Draft202012Validator(contract, format_checker=jsonschema.FormatChecker()).validate(doc)
    verify(doc)
    subject = doc["subject"]
    session_subject = {k: v for k, v in subject.items() if k != "task_id"}
    session_id = "nsess-" + hashlib.sha256(canonical({
        "domain": "native-skill-managed-session/v1", "subject": session_subject,
    })).hexdigest()[:32]
    if "registration_id" in doc:
        assert doc["registration_id"] == session_id
    else:
        assert doc["session_ref"]["registration_id"] == session_id
        session = json.loads((SAMPLES / CASES[0][0]).read_text())
        assert doc["session_ref"]["signature"] == session["signature"]
        assert doc["agent_authority"] == session["agent_authority"]
        assert doc["call_id"] == "ncall-" + hashlib.sha256(canonical({
            "domain": "native-skill-call/v1", "subject": subject, "tool_call_id": doc["tool_call_id"],
        })).hexdigest()[:32]
        binding = {k: subject[k] for k in ["platform", "session_id", "agent_id", "task_id"]}
        binding.update(tool=doc["tool"], tool_call_id=doc["tool_call_id"], params={
            "path": "/workspace/synthetic.txt", "sensitive_test_marker": "never-persist-this",
        })
        assert doc["request_binding"] == hashlib.sha256(canonical(binding)).hexdigest()
        assert "params" not in doc
        assert "never-persist-this" not in json.dumps(doc)
    doc["agent_authority"]["grant_digest"] = "f" * 64
    with pytest.raises(InvalidSignature):
        verify(doc)


@pytest.mark.parametrize("mutation", ["unknown", "no_lineage", "both", "missing_task", "null_context"])
def test_native_call_refuses_ambiguous_lineage(mutation):
    doc = json.loads((SAMPLES / CASES[2][0]).read_text())
    if mutation == "unknown":
        doc["model_authorized"] = True
    elif mutation == "no_lineage":
        del doc["context"]
    elif mutation == "both":
        doc["no_skill"] = True
    elif mutation == "missing_task":
        del doc["subject"]["task_id"]
    else:
        doc["context"] = None
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, json.loads((CONTRACTS / CASES[2][1]).read_text()))


@pytest.mark.parametrize("field", [
    "tool", "tool_call_id", "request_binding", "subject", "session_ref", "no_skill", "context",
])
def test_native_call_every_binding_field_signed(field):
    doc = json.loads((SAMPLES / CASES[2][0]).read_text())
    if field in ["tool", "tool_call_id"]:
        doc[field] = "changed"
    elif field == "request_binding":
        doc[field] = "f" * 64
    elif field == "subject":
        doc[field]["task_id"] = "changed"
    elif field == "session_ref":
        doc[field]["signature"] = "f" * 128
    elif field == "no_skill":
        doc[field] = True
    else:
        doc[field]["signature"] = "f" * 128
    with pytest.raises(InvalidSignature):
        verify(doc)
