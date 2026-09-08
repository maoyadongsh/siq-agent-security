"""Template §91 shared bytes/digest/signature; test seeds are public fixtures."""
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SAMPLES = Path(__file__).parents[4] / "apps/agentshield/testdata/contracts"


@pytest.mark.parametrize("name,seed", [("context-assertion", 7), ("provenance-assertion", 3), ("effect-evidence", 7)])
def test_shared_canonical_digest_and_signature(name, seed):
    sample = json.loads((SAMPLES / f"{name}.sample.json").read_text())
    vector = json.loads((SAMPLES / f"{name}.vector.json").read_text())
    signature = bytes.fromhex(sample.pop("signature"))
    encoded = json.dumps(sample, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    assert encoded == vector["canonical_unsigned"].encode()
    assert hashlib.sha256(encoded).hexdigest() == vector["unsigned_sha256"]
    key = Ed25519PrivateKey.from_private_bytes(bytes([seed]) * 32)
    key.public_key().verify(signature, encoded)
    assert key.sign(encoded) == signature
