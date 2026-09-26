"""Print a PUBLIC TEST KEY vector; imports no product canonicalization/signing code."""
import base64
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

seed = bytes(range(32))  # Public fixture material, never a deployment identity.
body = {
    'schema_version': 'edge-credential-rotation/v1',
    'device_identity': 'fixture-device',
    'environment_id': 'fixture-environment',
    'rotation_id': '12345678-1234-4234-8234-123456789abc',
    'expected_secret_hash': 'a' * 64,
    'new_secret_hash': 'b' * 64,
}
payload = json.dumps(body, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
signature = Ed25519PrivateKey.from_private_bytes(seed).sign(payload.encode('ascii')).hex()
print(json.dumps({'scope': 'public-test-key-only', 'seed_base64': base64.b64encode(seed).decode(),
                  'request': dict(body, signature=signature), 'canonical': payload}, indent=2))
