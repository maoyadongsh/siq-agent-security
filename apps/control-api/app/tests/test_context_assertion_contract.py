"""Context authority wire contract and fixed Go signature vector."""
import copy
import json
import re
from datetime import datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[4]
FORMATS = FormatChecker()


@FORMATS.checks("date-time", raises=ValueError)
def valid_rfc3339(value):
    if not isinstance(value, str):
        return True
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
        return False
    return datetime.fromisoformat(value).tzinfo is not None


def test_context_assertion_sample_and_closed_claims():
    schema = json.loads((ROOT / "packages/contracts/context-assertion.v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FORMATS)
    sample = json.loads((ROOT / "apps/agentshield/testdata/contracts/context-assertion.sample.json").read_text())
    validator.validate(sample)
    for field in sample:
        bad = dict(sample)
        del bad[field]
        assert list(validator.iter_errors(bad)), field
    for field, value in [("role", "admin"), ("tenant", "forged"), ("device_trust", "trusted")]:
        bad = copy.deepcopy(sample)
        bad["claims"][field] = value
        assert list(validator.iter_errors(bad)), field
    for field, value in [
        ("issuer_id", "caller"), ("signature", "fake"), ("request_binding", ""), ("expires_at", "later"),
    ]:
        assert list(validator.iter_errors({**sample, field: value})), field


def test_context_go_signature_matches_python_canonical_bytes():
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    sample = json.loads((ROOT / "apps/agentshield/testdata/contracts/context-assertion.sample.json").read_text())
    signature = bytes.fromhex(sample.pop("signature"))
    public = Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32).public_key()
    def canonical(doc):
        return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()

    public.verify(signature, canonical(sample))
    sample["claims"]["workspace_root"] = "/secret"
    with pytest.raises(InvalidSignature):
        public.verify(signature, canonical(sample))
