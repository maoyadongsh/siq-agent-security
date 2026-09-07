"""Go-produced V2 fixtures, strict schema failures and independent signature verification."""

import copy
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft7Validator, FormatChecker

from app.signing import _canonical_bytes

ROOT = Path(__file__).parents[4]
SAMPLES = ROOT / "apps/agentshield/testdata/contracts"
CONTRACTS = ROOT / "packages/contracts"


FORMATS = FormatChecker()


@FORMATS.checks("date-time", raises=ValueError)
def valid_rfc3339(value):
    if not isinstance(value, str):
        return True
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
        return False
    return datetime.fromisoformat(value).tzinfo is not None


def validator(name):
    schema = json.loads((CONTRACTS / f"{name}.schema.json").read_text())
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema, format_checker=FORMATS)


@pytest.mark.parametrize("name", ["hold-status-request.v1", "hold-status.v1"])
def test_hold_status_wire_contract(name):
    sample = json.loads((SAMPLES / f"{name}.sample.json").read_text())
    check = validator(name)
    check.validate(sample)
    for field in check.schema["required"]:
        bad = {key: value for key, value in sample.items() if key != field}
        assert list(check.iter_errors(bad)), field
    assert list(check.iter_errors({**sample, "approve": True}))
    if name == "hold-status-request.v1":
        assert list(check.iter_errors({**sample, "params": None}))
        assert list(check.iter_errors({**sample, "action_id": ""}))
    else:
        for status in ("pending", "approved", "denied", "expired", "consumed"):
            check.validate({**sample, "status": status, "reason_code": f"hold_{status}"})
        check.validate({**sample, "status": "denied", "reason_code": "hold_authority_changed"})
        assert list(check.iter_errors({**sample, "status": "approved", "reason_code": "hold_denied"}))
        assert list(check.iter_errors({**sample, "expires_at": "yesterday"}))


@pytest.mark.parametrize("name", ["intent-contract.v2", "runtime-action-envelope"])
def test_v2_go_fixture_and_required_fields(name):
    sample = json.loads((SAMPLES / f"{name}.sample.json").read_text())
    check = validator(name)
    check.validate(sample)
    for field in check.schema["required"]:
        bad = copy.deepcopy(sample)
        del bad[field]
        assert list(check.iter_errors(bad)), field
    assert list(check.iter_errors({**sample, "unexpected": True}))
    date = "issued_at" if name == "intent-contract.v2" else "occurred_at"
    assert list(check.iter_errors({**sample, date: "yesterday"}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("signature", "forged"),
        ("digest", "not-a-digest"),
        ("resource_constraints", [{"domain": "filesystem", "operator": "execute", "value": "/company"}]),
        ("parameter_constraints", [{"path": "/bad~2", "operator": "equals", "value": "x"}]),
        ("parameter_constraints", [{"path": "/nested/x", "operator": "one_of", "values": []}]),
        ("parameter_constraints", [{"path": "/nested/x", "operator": "equals"}]),
        ("parameter_constraints", [{"path": "/nested/x", "operator": "regex", "value": "x" * 1025}]),
    ],
)
def test_v2_malformed_contract_rejected(field, value):
    sample = json.loads((SAMPLES / "intent-contract.v2.sample.json").read_text())
    assert list(validator("intent-contract.v2").iter_errors({**sample, field: value}))


def test_go_intent_canonical_digest_and_signature_vector():
    vector = json.loads((SAMPLES / "intent-contract.v2.vector.json").read_text())
    contract = vector["contract"]
    unsigned = {k: v for k, v in contract.items() if k not in {"signature", "digest"}}
    canonical = _canonical_bytes(unsigned)
    assert canonical.hex() == vector["canonical_hex"]
    assert hashlib.sha256(canonical).hexdigest() == contract["digest"]
    signed = {**unsigned, "digest": contract["digest"]}
    public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(vector["public_key_hex"]))
    signature = bytes.fromhex(contract["signature"])
    public.verify(signature, _canonical_bytes(signed))
    with pytest.raises(InvalidSignature):
        public.verify(signature, _canonical_bytes({**signed, "purpose": "widened authority"}))
    with pytest.raises(InvalidSignature):
        public.verify(signature, _canonical_bytes({**signed, "digest": "0" * 64}))


@pytest.mark.parametrize(
    "case",
    json.loads((SAMPLES / "intent-v2-matcher-cases.json").read_text()),
    ids=lambda case: case["name"],
)
def test_shared_matcher_constraints_conform_to_schema(case):
    # Go evaluates these exact cases; Python independently validates wire shape.
    sample = json.loads((SAMPLES / "intent-contract.v2.sample.json").read_text())
    sample.update(
        resource_constraints=case["resource_constraints"],
        parameter_constraints=case["parameter_constraints"],
        allowed_tools=[case["tool"]],
        allowed_effects=["file.read", "network.request", "message.send"],
    )
    validator("intent-contract.v2").validate(sample)


@pytest.mark.parametrize("name", ["intent-contract.v2", "runtime-action-envelope", "receipt"])
@pytest.mark.parametrize("refs", [["../unsafe"], ["duplicate", "duplicate"], [f"ref-{i}" for i in range(65)]])
def test_provenance_reference_limits(name, refs):
    sample = json.loads((SAMPLES / f"{name}.sample.json").read_text())
    assert list(validator(name).iter_errors({**sample, "provenance_refs": refs}))


@pytest.mark.parametrize("name", ["runtime-action-envelope", "receipt"])
def test_resource_refs_and_principal_reject_plaintext_or_forged_shape(name):
    sample = json.loads((SAMPLES / f"{name}.sample.json").read_text())
    for field, value in [
        ("resource_refs", [{"domain": "filesystem", "digest": "a" * 64, "value": "/private"}]),
        ("resource_refs", [{"domain": "filesystem", "digest": "/private"}]),
        ("principal", {"type": "model", "id": "a-1"}),
    ]:
        assert list(validator(name).iter_errors({**sample, field: value}))


def test_historical_receipt_without_optional_metadata_still_valid():
    sample = json.loads((SAMPLES / "receipt.pre-resource-refs.sample.json").read_text())
    validator("receipt").validate(sample)


@pytest.mark.parametrize("name", ["intent-binding-revoke-request.v1", "intent-binding-revocation.v1"])
def test_binding_revocation_wire_contract(name):
    sample = json.loads((SAMPLES / f"{name}.sample.json").read_text())
    check = validator(name)
    check.validate(sample)
    for field in check.schema["required"]:
        assert list(check.iter_errors({k: v for k, v in sample.items() if k != field})), field
    assert list(check.iter_errors({**sample, "approved": True}))
    if name == "intent-binding-revoke-request.v1":
        for bad in ("", "A" * 64, "0" * 63, None):
            assert list(check.iter_errors({"expected_intent_digest": bad}))
    else:
        for field, bad in (("signature", "0" * 127), ("binding_id", "../escape"),
                           ("binding_digest", "A" * 64), ("revoked_at", "yesterday"),
                           ("reason_code", "allow"), ("signing_schema", "unknown")):
            assert list(check.iter_errors({**sample, field: bad}))


def test_go_binding_revocation_signature_and_binding_digest_vector():
    vector = json.loads((SAMPLES / "intent-binding-revocation.v1.vector.json").read_text())
    binding, revocation = vector["binding"], vector["revocation"]
    public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(vector["public_key_hex"]))
    public.verify(bytes.fromhex(binding["signature"]),
                  _canonical_bytes({k: v for k, v in binding.items() if k != "signature"}))
    assert hashlib.sha256(_canonical_bytes(binding)).hexdigest() == revocation["binding_digest"]
    unsigned = {k: v for k, v in revocation.items() if k != "signature"}
    canonical = _canonical_bytes(unsigned)
    assert canonical.hex() == vector["canonical_hex"]
    public.verify(bytes.fromhex(revocation["signature"]), canonical)
    for field, replacement in (("binding_digest", "0" * 64), ("revoked_at", "2099-01-01T00:00:00Z")):
        with pytest.raises(InvalidSignature):
            public.verify(bytes.fromhex(revocation["signature"]), _canonical_bytes({**unsigned, field: replacement}))
