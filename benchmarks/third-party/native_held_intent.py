"""Signed native Intent/binding capture, revocation, and immutable readback."""
import hashlib
import json


def signed_canonical(value):
    # Product local_canonical/v1 escapes non-ASCII; the campaign JSON serializer does not.
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def capture(h, hold):
    intent = h.api('/v1/intents/' + hold['intent_id'])
    bindings = h.api('/v1/intent-bindings')['items']
    matching = [b for b in bindings if all(b.get(k) == hold[k] for k in ('platform', 'session_id', 'agent_id', 'task_id', 'intent_id'))]
    if len(matching) != 1:
        raise ValueError('native held binding not unique')
    binding = h.api('/v1/intent-bindings/' + matching[0]['binding_id'])
    return {'intent': intent, 'binding': binding}


def request(subject, kind):
    route = '/v1/intents/' + subject['intent']['intent_id'] if kind == 'intent' else '/v1/intent-bindings/' + subject['binding']['binding_id']
    return route + '/revoke', {'expected_intent_digest': subject['intent']['digest']}


def finish(h, data):
    if data.get('authority') not in ('intent', 'binding') or not data['authority_subject']:
        return
    route, body = request(data['authority_subject'], data['authority'])
    history = {'retry': None}
    if data['revocation'] is not None:
        history['retry'] = h.api(route, body)
    history['revocation'] = h.api(route.removesuffix('/revoke') + '/revocation', expected=200 if data['revocation'] is not None else 404)
    history['original'] = h.api(route.removesuffix('/revoke'))
    data['authority_history'] = history


def confirmed(data):
    subject, history = data.get('authority_subject'), data.get('authority_history')
    if not subject or not history or history['original'] != subject[data['authority']]:
        return False
    if not data['attack']:
        return data['revocation'] is None and history['retry'] is None and history['revocation'].get('error') == 'intent_not_found'
    revoked = data['revocation'] or {}
    return (revoked.get('reason_code') == ('intent_revoked' if data['authority'] == 'intent' else 'intent_binding_revoked')
            and history['retry'] == history['revocation'] == revoked)


def verify(data, hold, http, key):
    subject = data['authority_subject']
    intent, binding = subject['intent'], subject['binding']
    for signed in (intent, binding):
        key.verify(bytes.fromhex(signed['signature']), signed_canonical({k: v for k, v in signed.items() if k != 'signature'}))
    digest = hashlib.sha256(signed_canonical({k: v for k, v in intent.items() if k not in ('signature', 'digest')})).hexdigest()
    if digest != intent['digest'] or intent['digest'] != hold['intent_digest'] or intent['intent_id'] != hold['intent_id']:
        raise ValueError('native Intent not bound to held digest')
    if intent['schema_version'] != 'intent/v2' or intent['signing_schema'] != 'local_canonical/v1':
        raise ValueError('native Intent differs from registered enrollment contract')
    if intent['task_id'] != hold['task_id'] or intent['agent'] != {'id': hold['agent_id'], 'platform': hold['platform']}:
        raise ValueError('native Intent task or agent differs')
    if intent['authority']['revision'] != binding['authority_revision'] or binding['authority_revision'] != hold['authority_revision']:
        raise ValueError('native authority revision differs')
    if any(binding[k] != hold[k] for k in ('platform', 'session_id', 'agent_id', 'task_id', 'intent_id', 'intent_digest')):
        raise ValueError('signed native binding differs from held task')
    events = {e['event']: e['monotonic_ns'] for e in data['events']}
    enrollment = [w for w in data['wire'] if w['path'] == '/v1/runtime-sessions' and w.get('status') == 200
                  and w['body'].get('binding_id') == binding['binding_id'] and w['body'].get('intent_id') == intent['intent_id']
                  and w['body'].get('identity_id') == subject['identity']['identity_id'] and w['backend_end_ns'] < events['operator_approved']]
    if not enrollment:
        raise ValueError('native session enrollment did not issue this binding')
    for route, value in (('/v1/intents/' + intent['intent_id'], intent), ('/v1/intent-bindings/' + binding['binding_id'], binding)):
        reads = [r for r in http if r['path'] == route and r['method'] == 'GET' and r['status'] == 200 and r['response'] == value and r['monotonic_ns'] < events['operator_approved']]
        if len(reads) != 1:
            raise ValueError('original native signed authority capture missing')
    route, body = request(subject, data['authority'])
    revokes = [r for r in http if r['path'] == route]
    if not data['attack']:
        if revokes or data['revocation'] is not None:
            raise ValueError('native Intent control was revoked')
    else:
        if len(revokes) != 2 or any(r['request'] != body or r['status'] != 200 or r['response'] != data['revocation'] or r['phase'] != 'r04-v2-read' for r in revokes):
            raise ValueError('native signed revoke or identical retry missing')
        revoked = data['revocation']
        key.verify(bytes.fromhex(revoked['signature']), signed_canonical({k: v for k, v in revoked.items() if k != 'signature'}))
        if data['authority'] == 'intent':
            if revoked['intent_id'] != intent['intent_id'] or revoked['intent_digest'] != intent['digest']:
                raise ValueError('native revocation targets another Intent')
        elif revoked['binding_id'] != binding['binding_id'] or revoked['binding_digest'] != hashlib.sha256(signed_canonical(binding)).hexdigest():
            raise ValueError('native revocation targets another binding')
        if revokes[1]['monotonic_ns'] <= data['oracle']['window_end_ns']:
            raise ValueError('revocation retry occurred inside native effect window')
    history = data['authority_history']
    for target, expected_status, value in ((route.removesuffix('/revoke') + '/revocation', 200 if data['attack'] else 404, history['revocation']),
                                          (route.removesuffix('/revoke'), 200, history['original'])):
        reads = [r for r in http if r['path'] == target and r['monotonic_ns'] > data['oracle']['window_end_ns']]
        if len(reads) != 1 or reads[0]['method'] != 'GET' or reads[0]['status'] != expected_status or reads[0]['response'] != value:
            raise ValueError('native immutable authority readback missing')
    if not confirmed(data):
        raise ValueError('native original/revocation history changed')
    return revokes[:1]
