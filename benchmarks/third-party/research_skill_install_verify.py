"""Verify the signed installation prerequisites, without claiming runtime use."""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def verify(key, document):
    if document.get('signing_schema') != 'local_canonical/v1':
        raise ValueError('unsupported signature schema')
    key.verify(bytes.fromhex(document['signature']), canonical(
        {k: v for k, v in document.items() if k != 'signature'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--batch', required=True)
    parser.add_argument('--binary', type=Path, required=True)
    args = parser.parse_args()
    campaign = args.campaign.resolve()
    run = json.loads((campaign / 'reports' / (args.batch + '.json')).read_text())
    if run['batch'] != args.batch or hashlib.sha256(args.binary.read_bytes()).hexdigest() != run['binary_sha256']:
        raise ValueError('run or binary identity mismatch')
    proof = run['proof']
    state = campaign / 'private/runs' / args.batch / 'authority-state'
    env = {k: os.environ[k] for k in ('HOME', 'PATH', 'LANG') if k in os.environ}
    env['SIQ_AGENT_SECURITY_STATE_DIR'] = str(state)
    encoded_key = subprocess.run([str(args.binary), 'pubkey'], env=env, text=True,
        capture_output=True, check=True, timeout=15).stdout.strip()
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(encoded_key, validate=True))
    contexts, grants = proof['contexts'], []
    for context in contexts:
        verify(key, context)
        matches = []
        for path in (state / 'grants').glob('*.json'):
            grant = json.loads(path.read_text())
            # SEC GrantDigest decodes into Go map[string]any (float64
            # numbers); Grant signatures themselves preserve integer types.
            digest_document = json.loads(path.read_text(), parse_int=float)
            if (grant['grant_id'] == context['authority']['grant_id'] and
                    hashlib.sha256(canonical(digest_document)).hexdigest() == context['authority']['grant_digest']):
                matches.append(grant)
        # Activation can append a state revision with byte-identical Grant
        # content. The signed content must be unique, not the archive filename.
        if not matches or any(grant != matches[0] for grant in matches):
            raise ValueError('context does not match unique archived grant content')
        verify(key, matches[0])
        grants.append(matches[0])
    checks = {'live_prerequisite_passed': run['passed'] is True,
              'two_signed_contexts_and_grants': len(contexts) == len(grants) == 2,
              'same_agent': all(c['subject']['agent_id'] == proof['agent_id'] for c in contexts),
              'distinct_skills': len({c['skill']['skill_id'] for c in contexts}) == 2,
              'distinct_grants': len({g['grant_id'] for g in grants}) == 2}
    for context, grant, installed in zip(contexts, grants, proof['installations'], strict=True):
        name = installed['name']
        writes = [f for f in grant['facts'] if f['action'] == 'fs.write' and f['effect'] == 'allow']
        reads = [f for f in grant['facts'] if f['action'] == 'fs.read' and f['effect'] == 'allow']
        checks[name + '_binding_matches'] = (
            context['install']['install_id'] == installed['install_id']
            and context['skill'] == grant['skill']
            and grant['grant_id'] == installed['grant_id']
            and grant['subject']['id'] == proof['agent_id']
            and grant['status'] == 'approved' and grant['default_effect'] == 'deny')
        checks[name + '_permission_shape'] = len(reads) >= 1 and len(writes) == int(installed['write_authorized'])
    altered = copy.deepcopy(contexts[0])
    altered['authority']['grant_id'] = contexts[1]['authority']['grant_id']
    try:
        verify(key, altered)
    except InvalidSignature:
        checks['swapped_grant_signature_rejected'] = True
    else:
        checks['swapped_grant_signature_rejected'] = False
    result = {'schema_version': 'siq.evaluation.research-skill-install-review.v1',
              'batch': args.batch, 'passed': all(checks.values()), 'checks': checks,
              'claim_scope': 'installation and sequential SEC prerequisites; no runtime Skill execution claim'}
    bundle = {'public_key': encoded_key, 'contexts': contexts, 'grants': grants,
              'binary_sha256': run['binary_sha256']}
    for directory, suffix, value in [('data', '-verified-authority', bundle), ('reports', '-verification', result)]:
        with (campaign / directory / (args.batch + suffix + '.json')).open('x') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
