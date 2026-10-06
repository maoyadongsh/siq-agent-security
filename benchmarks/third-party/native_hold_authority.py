"""Exact live authority revocation for registered native hold barriers."""
import native_held_intent
from native_held_intent import signed_canonical as canonical

KINDS = ('grant', 'sec', 'identity', 'intent', 'binding')


def capture(h, hold, kind):
    if kind == 'grant':
        return None
    context = h.api('/v1/skill-contexts/' + hold['skill_attribution']['context_id'])
    identity = h.issued['identity']
    result = {'context': context, 'identity': identity}
    if kind in ('intent', 'binding'):
        result.update(native_held_intent.capture(h, hold))
    return result


def request(subject, kind):
    if kind in ('intent', 'binding'):
        return native_held_intent.request(subject, kind)
    if kind == 'sec':
        context = subject['context']
        return ('/v1/skill-contexts/' + context['context_id'] + '/revoke',
                {'schema_version': 'local-skill-execution-context-revoke/v1',
                 'expected_context_signature': context['signature'],
                 'actor_id': 'evaluation-operator', 'confirm_revoke': True})
    if kind == 'identity':
        return ('/v1/runtime-identities/' + subject['identity']['identity_id'] + '/revoke',
                {'schema_version': 'local-runtime-identity-revoke/v1', 'actor_id': 'evaluation-operator'})
    raise ValueError('unsupported native hold authority')


def confirmed(data):
    if data.get('authority') in ('intent', 'binding'):
        return native_held_intent.confirmed(data)
    if not data['attack']:
        return data['revocation'] is None
    revoked = data['revocation'] or {}
    kind = data.get('authority', 'grant')
    if kind == 'grant':
        return revoked.get('grant', {}).get('status') == 'revoked'
    if kind == 'sec':
        context = (data.get('authority_subject') or {}).get('context', {})
        return bool(context.get('context_id')) and revoked.get('context_id') == context['context_id']
    return revoked.get('revoked') is True


def verify(data, hold, http, key):
    kind = data['authority']
    if kind not in ('sec', 'identity', 'intent', 'binding') or key is None:
        raise ValueError('native hold authority or public key missing')
    subject = data['authority_subject']
    context, identity = subject['context'], subject['identity']
    key.verify(bytes.fromhex(context['signature']), canonical({k: v for k, v in context.items() if k != 'signature'}))
    if context['context_id'] != hold['skill_attribution']['context_id']:
        raise ValueError('native held SEC differs from revoked subject')
    issued = [r for r in http if r['path'] == '/v1/skill-contexts' and r['status'] == 201 and r['response'] == context]
    identities = [r for r in http if r['path'] == '/v1/runtime-identities' and r['status'] == 201 and r['response']['identity'] == identity]
    if len(issued) != 1 or len(identities) != 1:
        raise ValueError('held authority lacks actual issuance')
    if any(context['subject'][k] != hold[k] for k in ('platform', 'session_id', 'agent_id')):
        raise ValueError('held SEC scope differs')
    if context['subject']['task_id'] != hold['runtime_task_id'] or context['authority']['grant_id'] != hold['matched_grant_id']:
        raise ValueError('held SEC task or Grant differs')
    if any(identity[k] != context['subject'][k] for k in ('instance_id', 'agent_id', 'platform')) or identity['grant_ref']['grant_id'] != hold['matched_grant_id']:
        raise ValueError('held runtime identity differs')
    if kind in ('intent', 'binding'):
        return native_held_intent.verify(data, hold, http, key)
    route, body = request(subject, kind)
    rows = [r for r in http if r['path'] == route]
    if not data['attack']:
        if rows or data['revocation'] is not None:
            raise ValueError('normal authority was revoked at barrier')
        return []
    if len(rows) != 1 or rows[0]['request'] != body or rows[0]['status'] != 200 or rows[0]['response'] != data['revocation'] or rows[0]['phase'] != 'r04-v2-read':
        raise ValueError('exact native authority revocation HTTP missing')
    if kind == 'sec':
        revoked = data['revocation']
        key.verify(bytes.fromhex(revoked['signature']), canonical({k: v for k, v in revoked.items() if k != 'signature'}))
        if revoked['context_id'] != context['context_id']:
            raise ValueError('signed revoke targets another SEC')
    return rows
