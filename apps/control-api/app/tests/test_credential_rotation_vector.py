import base64
import json
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.routers.credential_rotation import RotateCredential


def test_independent_rotation_vector():
    root = Path(__file__).resolve().parents[4]
    vector = json.loads((root / 'packages/contracts/fixtures/credential_rotation_vector_v1.json').read_text())
    assert vector['scope'] == 'public-test-key-only'
    generated = subprocess.run(
        [sys.executable, str(root / 'scripts/enterprise-experience/generate-credential-rotation-vector.py')],
        capture_output=True, text=True, check=True, timeout=10,
    )
    assert json.loads(generated.stdout) == vector
    request = RotateCredential(**vector['request'])
    assert request.signed_bytes().decode('ascii') == vector['canonical']
    key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(vector['seed_base64']))
    key.public_key().verify(bytes.fromhex(request.signature), request.signed_bytes())
