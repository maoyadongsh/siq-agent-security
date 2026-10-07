"""Independent validation of v3 receipts emitted by signed-store/engine integration."""

import copy
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[4]
CONTRACTS = ROOT / "packages/contracts"
SAMPLES = ROOT / "apps/agentshield/testdata/contracts"


def canonical(doc):
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def verify(doc):
    doc = copy.deepcopy(doc)
    signature = bytes.fromhex(doc.pop("sig"))
    recorded_hash = doc.pop("hash")
    actual_hash = hashlib.sha256(canonical(doc)).hexdigest()
    assert recorded_hash == actual_hash
    public = Ed25519PrivateKey.from_private_bytes(bytes([9]) * 32).public_key()
    public.verify(signature, actual_hash.encode())


@pytest.mark.parametrize("kind", ["no-skill", "with-skill"])
def test_native_receipt_schema_signature_and_version_separation(kind):
    doc = json.loads((SAMPLES / f"native-receipt-{kind}-v3.sample.json").read_text())
    schema = json.loads((CONTRACTS / "receipt.v3.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(doc)
    verify(doc)
    for legacy in ["receipt.schema.json", "receipt.v2.schema.json"]:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.Draft7Validator(json.loads((CONTRACTS / legacy).read_text())).validate(doc)
    evidence = doc["native_invocation"]
    assert evidence["no_skill"] == (kind == "no-skill")
    assert ("skill_attribution" in doc) == (kind == "with-skill")
    binding = {k: doc[k] for k in ["platform", "session_id", "agent_id", "tool", "tool_call_id"]}
    binding.update(task_id=doc["runtime_task_id"], params={
        "path": "/workspace/synthetic.txt", "sensitive_test_marker": "never-persist-this",
    })
    assert evidence["request_binding"] == hashlib.sha256(canonical(binding)).hexdigest()
    if kind == "with-skill":
        assert doc["skill_attribution"]["call_binding"] == evidence["request_binding"]
        assert doc["skill_attribution"]["context_id"] == evidence["contexts"][0]["context_id"]
        assert doc["matched_grant_id"] == evidence["contexts"][0]["authority"]["grant_id"]
    else:
        assert evidence["contexts"] == []
        assert doc["matched_grant_id"] == evidence["agent_authority"]["grant_id"]


@pytest.mark.parametrize("field", [
    "call_signature", "session_signature", "request_binding", "agent_authority", "contexts",
])
def test_native_receipt_authority_tampering_breaks_chain_signature(field):
    doc = json.loads((SAMPLES / "native-receipt-with-skill-v3.sample.json").read_text())
    evidence = doc["native_invocation"]
    if field == "agent_authority":
        evidence[field]["grant_digest"] = "f" * 64
    elif field == "contexts":
        evidence[field][0]["authority"]["grant_id"] = "other-grant"
    else:
        evidence[field] = "f" * len(evidence[field])
    with pytest.raises(AssertionError):
        verify(doc)
    unsigned = {k: v for k, v in doc.items() if k not in {"sig", "hash"}}
    doc["hash"] = hashlib.sha256(canonical(unsigned)).hexdigest()
    with pytest.raises(InvalidSignature):
        verify(doc)


@pytest.mark.parametrize("mutation", ["missing_proof", "empty_chain", "no_skill_lie", "legacy_level", "unknown"])
def test_native_receipt_refuses_incomplete_or_ambiguous_evidence(mutation):
    doc = json.loads((SAMPLES / "native-receipt-with-skill-v3.sample.json").read_text())
    if mutation == "missing_proof":
        del doc["native_invocation"]
    elif mutation == "empty_chain":
        doc["native_invocation"]["contexts"] = []
    elif mutation == "no_skill_lie":
        doc["native_invocation"]["no_skill"] = True
    elif mutation == "legacy_level":
        doc["skill_attribution"]["evidence_level"] = "controlled_task"
    else:
        doc["native_invocation"]["model_authorized"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, json.loads((CONTRACTS / "receipt.v3.schema.json").read_text()))


@pytest.mark.parametrize("kind", ["no-skill", "with-skill"])
def test_native_hold_full_product_chain(kind):
    rows = json.loads((SAMPLES / f"native-hold-{kind}-v3.sample.json").read_text())
    schema = json.loads((CONTRACTS / "receipt.v3.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    previous = "0" * 64
    for seq, row in enumerate(rows):
        validator.validate(row)
        verify(row)
        assert row["seq"] == seq and row["prev_hash"] == previous
        previous = row["hash"]
    decision, approval, reservation, observation = rows
    assert [row["record_type"] for row in rows] == [
        "decision", "hold_resolution", "hold_reservation", "observation",
    ]
    assert approval["decision_receipt_id"] == decision["receipt_id"]
    assert reservation["decision_receipt_id"] == decision["receipt_id"]
    assert observation["decision_receipt_id"] == reservation["receipt_id"]
    original = decision["native_invocation"]
    retry = reservation["native_invocation"]
    assert approval["native_invocation"] == original
    assert observation["native_invocation"] == retry
    assert original["call_id"] != retry["call_id"]
    assert original["request_binding"] != retry["request_binding"]
    for field in ["agent_authority", "session_registration_id", "session_signature", "no_skill", "contexts"]:
        assert original[field] == retry[field]
    if kind == "with-skill":
        assert len(retry["contexts"]) == 2
        assert retry["contexts"][0]["authority"]["grant_id"] != retry["contexts"][1]["authority"]["grant_id"]
        assert reservation["skill_attribution"]["call_binding"] == retry["request_binding"]
    else:
        assert retry["contexts"] == [] and "skill_attribution" not in reservation
