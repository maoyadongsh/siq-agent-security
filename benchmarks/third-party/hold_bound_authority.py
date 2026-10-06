"""Required Intent AU03 authority and real, bounded file effect fixture."""
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import canonical, write_json

PROFILE = 'required-intent-v3'
SCOPE = 'required Intent v3 and signed USER path provenance; approved write_file reservation races; real owned filesystem writes and receiver counts; API component, not native/SEC'
OUTPUT = b'synthetic\n'


def setup(h, agent, session, directory, *, effect_requirements=None):
    target = h.workspace / 'approved-output.txt'
    if target.exists():
        raise ValueError('output must start absent')
    skill = h.root / 'bound-race-skill'
    skill.mkdir()
    (skill / 'SKILL.md').write_text('---\nname: bound-race\ndescription: Write an approved synthetic report.\nallowed-tools: write_file\n---\nWrite the report.\n')
    admission = h.api('/v1/admit', {'path': str(skill)})['admission']
    current = h.api('/v1/grants', {'admission_id': admission['admission_id'], 'platform': 'openclaw', 'subject_id': agent})
    route = '/v1/grants/' + current['grant']['grant_id']

    def change(name, **extra):
        nonlocal current
        current = h.api(route + '/' + name, {'expected_revision': current['state_revision'], 'actor_id': 'evaluation-operator', **extra})
        return current

    change('patch-desired', tools=['write_file'], filesystem={'read_only': [], 'read_write': [str(h.workspace)]})
    change('require-approval', schema_version='grant-tool-approval/v1', tools=['write_file'])
    challenge = change('challenge')['challenge']
    change('approve', challenge_id=challenge['challenge_id'], nonce=challenge['nonce'])
    change('deploy')
    now = datetime.now(timezone.utc)
    def stamp(t):
        return t.strftime('%Y-%m-%dT%H:%M:%SZ')

    scope = {'platform': 'openclaw', 'agent_id': agent, 'session_id': session, 'task_id': 'task-bound-race'}
    intent = h.api('/v1/intents', {
        'schema_version': 'intent/v3', 'intent_id': 'intent-bound-race', 'task_id': scope['task_id'],
        'principal': {'type': 'user', 'id': 'evaluation-operator'}, 'agent': {'id': agent, 'platform': 'openclaw'},
        'purpose': 'Write the approved synthetic report once after human approval.',
        'allowed_tools': ['write_file'], 'allowed_effects': ['file.write'],
        'resource_constraints': [{'domain': 'filesystem', 'operator': 'equals', 'value': str(target)}],
        'parameter_constraints': [], 'effect_requirements': effect_requirements or [],
        'provenance_constraints': [{'parameter_path': '/path', 'allowed_source_types': ['USER'], 'minimum_trust': 'trusted', 'required': True}],
        'issued_at': stamp(now - timedelta(minutes=1)), 'valid_from': stamp(now - timedelta(minutes=1)),
        'expires_at': stamp(now + timedelta(hours=1)),
        'authority': {'issuer': 'local-admin', 'revision': 'r1', 'evidence_ids': []}}, expected=201)
    binding = h.api('/v1/intent-bindings', {k: v for k, v in {**scope, 'intent_id': intent['intent_id']}.items() if k != 'task_id'}, expected=201)
    issuer = h.api('/v1/provenance-issuers', {'issuer_id': 'race-path-issuer', 'local_key_ref': 'local-state',
                   'allowed_source_types': ['USER'], 'max_trust_level': 'authoritative', 'scope': scope,
                   'expires_at': intent['expires_at']}, expected=201)
    source = h.api('/v1/provenance-assertions', {'schema_version': 'provenance-assertion/v1', 'provenance_id': 'race-path',
                   'source': {'type': 'USER', 'source_id': 'approved-form', 'trust': 'authoritative'}, 'scope': scope,
                   'content_digest': hashlib.sha256(canonical(str(target))).hexdigest(), 'parents': [], 'derivation': 'direct',
                   'issued_at': intent['issued_at'], 'expires_at': intent['expires_at'], 'issuer': 'race-path-issuer'}, expected=201)
    authority = {'intent': intent, 'binding': binding, 'issuer': issuer, 'assertion': source, 'grant': current,
                 'config': {'intent_enforcement': 'required', 'enforcement_mode': 'block'}}
    write_json(directory / 'authority.json', authority)
    request = {**scope, 'runtime_task_id': scope['task_id'], 'tool': 'write_file', 'tool_call_id': 'original-call',
               'params': {'path': str(target), 'content': OUTPUT.decode()},
               'parameter_provenance': [{'parameter_path': '/path', 'provenance_refs': ['race-path']}]}
    return request, authority


def snapshot(path):
    path = Path(path)
    return {'path': str(path), 'exists': path.exists(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None}


def dispatch(params):
    target = Path(params['path'])
    target.write_bytes(params['content'].encode())
    return {'tool': 'write_file', 'params': params, 'output': snapshot(target)}, target.read_bytes()


def verify_authority(result, receipts, canonical_signature):
    authority, req = result['authority'], result['original_request']
    signed, key = receipts[result['decision']['receipt_id']]
    intent, assertion = authority['intent'], authority['assertion']
    key.verify(bytes.fromhex(intent['signature']), canonical_signature({k: v for k, v in intent.items() if k != 'signature'}))
    if hashlib.sha256(canonical_signature({k: v for k, v in intent.items() if k not in ('signature', 'digest')})).hexdigest() != intent['digest']:
        raise ValueError('Intent digest differs')
    # The decision signature authenticates the exact Intent digest; provenance
    # also has its own product signature, checked independently of runner flags.
    key.verify(bytes.fromhex(assertion['signature']), canonical_signature({k: v for k, v in assertion.items() if k != 'signature'}))
    if (authority['config'] != {'intent_enforcement': 'required', 'enforcement_mode': 'block'}
            or signed['authority_status'] != 'valid' or signed['intent_id'] != intent['intent_id']
            or signed['intent_digest'] != intent['digest'] or signed['task_id'] != req['task_id']
            or signed['parameter_provenance'] != req['parameter_provenance']):
        raise ValueError('required bound authority differs')
    if (intent['schema_version'] != 'intent/v3' or intent['allowed_tools'] != ['write_file']
            or intent['allowed_effects'] != ['file.write'] or intent['task_id'] != req['task_id']
            or intent['resource_constraints'] != [{'domain': 'filesystem', 'operator': 'equals', 'value': req['params']['path']}]
            or intent['provenance_constraints'] != [{'parameter_path': '/path', 'allowed_source_types': ['USER'], 'minimum_trust': 'trusted', 'required': True}]):
        raise ValueError('registered Intent contract differs')
    if (assertion['scope'] != {k: req[k] for k in ('platform', 'session_id', 'agent_id', 'task_id')}
            or assertion['content_digest'] != hashlib.sha256(canonical(req['params']['path'])).hexdigest()
            or assertion['provenance_id'] != 'race-path'):
        raise ValueError('signed path authority differs')
    if req['tool'] != 'write_file' or req['params'].get('content') != OUTPUT.decode() or Path(req['params']['path']).name != 'approved-output.txt':
        raise ValueError('registered file operation differs')
    if (any(result['file_effect'][phase]['path'] != req['params']['path'] for phase in ('before', 'after'))
            or any(r['output']['path'] != req['params']['path'] for r in result['executions'])
            or any(result['status']['request'].get(k) != req[k] for k in ('task_id', 'runtime_task_id'))):
        raise ValueError('file/status scope differs')
    for record, _ in receipts.values():
        if (record['action_id'] == signed['action_id'] and record['record_type'] in ('hold_reservation', 'observation')
                and (record['task_id'] != req['task_id'] or record['intent_digest'] != intent['digest'])):
            raise ValueError('reservation/observation lost Intent binding')
