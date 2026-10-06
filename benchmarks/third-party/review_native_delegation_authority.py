"""Verify explicit signed parent delegation authority and preserve original outcomes."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from native_configuration_review import review_scope
from review_native_terminal import signature_payload, verify_document
from verify_native_business import verify


def bootstrap_matches(raw, probe):
    expected = [probe.get('session_id'), probe.get('runtime_task_id')]
    identities = {(row.get('session_id'), row.get('task_id'))
                  for row in (raw.get('delegation_observation') or {}).get('hooks', []) if row['event'] == 'pre_llm_call'}
    bootstrap = raw.get('bootstrap') or {}
    return (all(isinstance(value, str) and value for value in expected)
            and bootstrap.get('subjects') == [expected] and bootstrap.get('failures') == []
            and identities == {tuple(expected)})


def review(run, anchor):
    original = verify(run, anchor)
    p = json.loads((run / 'protocol.json').read_text())
    if p['profile'] not in ('delegation-controls', 'delegation-wait-controls') or p['mode'] != 'controls':
        raise ValueError('controlled native delegation protocol required')
    units, pairs = {}, {}
    for unit in p['allocation']:
        raw = json.loads((run / 'cases' / unit['unit_id'] / 'result.json').read_text())
        root = str(Path(raw['gold']['source_path']).parents[2])
        g = raw['gold']
        pairs.setdefault(unit['case_id'], {})[unit['group']] = {
            k: str(g[k]).replace(root, '__UNIT_ROOT__') for k in ('prompt', 'source_text')}
        details = {'delegation': original['units'][unit['unit_id']]['delegation'], 'authority_signature_documents': 0}
        if unit['group'] == 'B2':
            scope = review_scope(raw, 'delegation-controls')
            key = Ed25519PublicKey.from_public_bytes(base64.b64decode(raw['receipts']['public_key'], validate=True))
            probe = next(r for r in raw['receipts']['receipts'] if r.get('record_type') == 'decision'
                         and r['tool_call_id'] == g['delegation']['call_id'])
            intents = [i for r in raw['management_http'] if r['route'] == '/v1/intents'
                       for i in r['response']['items'] if i['intent_id'] == probe.get('intent_id')]
            bindings = [i for r in raw['management_http'] if r['route'] == '/v1/intent-bindings'
                        for i in r['response']['items'] if i['intent_id'] == probe.get('intent_id')]
            if len(intents) != len(bindings) or len(intents) != 1:
                raise ValueError('unique parent Intent and Binding required')
            intent, binding = intents[0], bindings[0]
            if intent['signing_schema'] != 'local_canonical/v1':
                raise ValueError('unexpected Intent signature schema')
            verify_document(intent, key)
            verify_document(binding, key)
            digest = hashlib.sha256(signature_payload({k: v for k, v in intent.items() if k not in ('signature', 'digest')})).hexdigest()
            if digest != intent['digest'] or digest != binding['intent_digest'] or digest != probe['intent_digest']:
                raise ValueError('parent Intent digest binding differs')
            if any(binding[k] != probe[k] for k in ('platform', 'session_id', 'agent_id', 'task_id', 'intent_id')):
                raise ValueError('delegate decision belongs to another parent')
            if binding['grant_ref']['grant_id'] != scope['approved_grant_id'] or 'delegate_task' not in intent['allowed_tools']:
                raise ValueError('signed parent delegation permission absent')
            if not bootstrap_matches(raw, probe):
                raise ValueError('SEC bootstrap not limited to this actual parent identity')
            details.update(approved_scope=scope, authority_signature_documents=3,
                           actual_reason=probe['reason_code'], intent_id=intent['intent_id'])
        units[unit['unit_id']] = details
    if any(set(row) != {'B0', 'B2'} or row['B0'] != row['B2'] for row in pairs.values()):
        raise ValueError('paired normalized parent inputs differ')
    return {'manifest_sha256': anchor, 'original_summary': {k: v for k, v in original.items() if k != 'units'},
            'units': units, 'paired_conditions': len(pairs), 'scope': 'parent signed explicit permission; not delegated child SEC inheritance; original outcomes retained'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(review(args.run, args.expected_manifest_sha256)))
