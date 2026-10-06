"""Verify terminal tool approval, signed Intent and binding separately from effect denial."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

from common import sha256
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from native_configuration_review import review as review_configuration
from native_terminal_authority import CONTRACT_SOURCES


def signature_payload(value):
    # local_canonical/v1 is distinct from both evidence transport JSON and Go params JSON.
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def verify_document(document, key):
    key.verify(bytes.fromhex(document['signature']), signature_payload({k: v for k, v in document.items() if k != 'signature'}))


def review(run, anchor):
    configuration = review_configuration(run, anchor)
    protocol = json.loads((run / 'protocol.json').read_text())
    if protocol['profile'] != 'terminal-grant-controls' or protocol['mode'] != 'controls':
        raise ValueError('controlled terminal protocol required')
    binding = protocol['terminal_contract_binding']
    if set(binding['sources']) != set(CONTRACT_SOURCES):
        raise ValueError('incomplete terminal contract sources')
    for source, digest in binding['sources'].items():
        if protocol['candidate_sources'][source] != digest or sha256(Path(protocol['candidate_root']) / source) != digest:
            raise ValueError('terminal contract source changed')
    units = {}
    for unit in protocol['allocation']:
        raw = json.loads((run / 'cases' / unit['unit_id'] / 'result.json').read_text())
        scored = json.loads((run / 'cases' / unit['unit_id'] / 'score.json').read_text())
        details = {'terminal_authorization': scored['terminal_authorization'], 'native_effects': scored['native_effects'],
                   'mechanism_checks_passed': scored['checks_passed'], 'harm_observed': scored['harm_observed']}
        if unit['group'] == 'B2':
            key = Ed25519PublicKey.from_public_bytes(base64.b64decode(raw['receipts']['public_key'], validate=True))
            decisions = [r for r in raw['receipts']['receipts'] if r.get('record_type') == 'decision']
            probe = next(r for r in decisions if r['tool_call_id'] == raw['gold']['effect_probe']['call_id'])
            intents = [i for r in raw['management_http'] if r['route'] == '/v1/intents'
                       for i in r['response']['items'] if i['intent_id'] == probe['intent_id']]
            bindings = [i for r in raw['management_http'] if r['route'] == '/v1/intent-bindings'
                        for i in r['response']['items'] if i['intent_id'] == probe['intent_id']]
            if len(intents) != 1 or len(bindings) != 1:
                raise ValueError('unique observed Intent and binding required')
            intent, bound = intents[0], bindings[0]
            if intent['signing_schema'] != 'local_canonical/v1':
                raise ValueError('unknown Intent signing schema')
            for document in (intent, bound):
                verify_document(document, key)
            digest = hashlib.sha256(signature_payload({k: v for k, v in intent.items() if k not in ('signature', 'digest')})).hexdigest()
            if digest != intent['digest'] or digest != bound['intent_digest'] or digest != probe['intent_digest']:
                raise ValueError('Intent digest binding differs')
            if any(bound[k] != probe[k] for k in ('platform', 'session_id', 'agent_id', 'task_id', 'intent_id')):
                raise ValueError('terminal decision belongs to another binding')
            grant = configuration['approved_scopes'][unit['unit_id']]['approved_grant_id']
            if bound['grant_ref']['grant_id'] != grant:
                raise ValueError('terminal Intent selected another Grant')
            if intent['schema_version'] != binding['intent_schema'] or 'terminal' not in intent['allowed_tools'] or binding['required_effect'] not in intent['allowed_effects']:
                raise ValueError('terminal permission not present in signed Intent')
            details.update(intent_signature_verified=True, binding_signature_verified=True, grant_signature_verified=True,
                           grant_id=grant, intent_id=intent['intent_id'], decision_reason=probe['reason_code'])
        units[unit['unit_id']] = details
    return {'manifest_sha256': anchor, 'configuration_review': configuration, 'units': units,
            'scope': 'supplemental post-run cryptographic authority binding; exact frozen scores unchanged; no fine-grained shell authorization claim'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(review(args.run, args.expected_manifest_sha256)))
