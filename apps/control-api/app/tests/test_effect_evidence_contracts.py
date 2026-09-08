"""Effect structure is separate from observer authorization and correlation."""
import copy
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator, FormatChecker


def validator():
    path = Path(__file__).parents[4] / "packages/contracts/effect-evidence.v1.schema.json"
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def record():
    # Structural fixture only; the placeholder signature has no signing authority.
    return {
        "schema_version": "effect-evidence/v1", "effect_evidence_id": "eff-1",
        "action_id": "action-1", "decision_receipt_id": "rcp-1",
        "effect_type": "file.write", "resource_ref": "filesystem:sha256:" + "b" * 64,
        "execution_state": "completed",
        "source": {"type": "host_observer", "source_id": "observer-1", "independence": "host_independent"},
        "coverage": "partial", "result": "expected", "evidence_digest": "a" * 64,
        "observed_at": "2026-09-08T01:00:00Z", "signing_schema": "local_canonical/v1",
        "signature": "0" * 128,
    }


def test_required_correlation_and_closed_record():
    v = validator()
    good = record()
    v.validate(good)
    for field in good:
        missing = copy.deepcopy(good)
        del missing[field]
        assert list(v.iter_errors(missing)), field
    for field, value in [("observed_at", "yesterday"), ("evidence_digest", "plaintext"),
                         ("completed", True), ("signature", "unsigned")]:
        assert list(v.iter_errors({**good, field: value})), field


@pytest.mark.parametrize("source_type,independence", [("tool_report", "self_reported"), ("unknown", "unknown")])
def test_self_report_cannot_claim_verified_effect(source_type, independence):
    v = validator()
    good = record()
    good.update(source={"type": source_type, "source_id": "source-1", "independence": independence},
                coverage="unknown", result="unknown")
    v.validate(good)
    for level in ["host_independent", "external_independent"]:
        forged = copy.deepcopy(good)
        forged["source"]["independence"] = level
        assert list(v.iter_errors(forged))
    for field, value in [("coverage", "full"), ("result", "expected")]:
        assert list(v.iter_errors({**good, field: value}))


def test_shared_signed_effect_sample():
    path = Path(__file__).parents[4] / "apps/agentshield/testdata/contracts/effect-evidence.sample.json"
    sample = json.loads(path.read_text())
    validator().validate(sample)
    signature = bytes.fromhex(sample.pop("signature"))
    canonical = json.dumps(sample, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    key = Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32)
    key.public_key().verify(signature, canonical)
    assert key.sign(canonical) == signature
