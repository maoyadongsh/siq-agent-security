from pathlib import Path
import base64, json, hashlib
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
root = Path.cwd() / '.tmp/win-task-native/bootstrap-fixed-20260917/intent-native-private-r1'
state = root / 'state'
# Synthetic test identity only. Never print or export the seed/private key.
public = Ed25519PrivateKey.from_private_bytes(base64.b64decode((state/'keys/signing.seed').read_bytes(), validate=True)).public_key()
rows = [json.loads(line) for path in sorted((state/'receipts/local').glob('*.jsonl')) for line in path.read_text(encoding='utf-8').splitlines() if line]
assert rows, 'empty receipt chain'
previous = '0' * 64
for index, row in enumerate(rows):
    assert row['seq'] == index and row['prev_hash'] == previous, 'broken chain'
    content = {key: value for key, value in row.items() if key not in ('hash', 'sig')}
    digest = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert digest == row['hash'], 'content hash mismatch'
    public.verify(bytes.fromhex(row['sig']), digest.encode('ascii'))
    previous = digest
print(json.dumps({'receipts': len(rows), 'invalid_authority_denials': sum(row.get('authority_status') == 'invalid' and row.get('effective_action') == 'deny' for row in rows), 'chain_links_verified': True, 'content_hashes_verified': True, 'signatures_verified': True, 'head_hash': previous, 'public_key_sha256': hashlib.sha256(public.public_bytes(Encoding.Raw, PublicFormat.Raw)).hexdigest()}))
