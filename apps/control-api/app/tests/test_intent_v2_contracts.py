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
