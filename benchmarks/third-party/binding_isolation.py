"""One signed Intent, two actual session bindings, selective versus global revocation."""
import hashlib
import json
import time
import urllib.request
from uuid import uuid4

from common import canonical, sha256, write_json
from hold_bound_authority import OUTPUT, dispatch, setup
from observer_recovery import call
from oracles.file import FileOracle
from oracles.receiver import ReceiverOracle
from process_resources import identity

SAMPLE_SCOPE = 'required Intent v3/block API component; same Intent/two session bindings; selective binding versus global Intent revocation before reserve, with/without owned daemon SIGKILL; real file and receiver; no native SEC or concurrent dispatch claim'


def allocation():
    rows = []
    for authority in ('binding', 'intent'):
        for restart in (False, True):
            variant = authority + ('-restart' if restart else '-live')
            for condition in ('benign', 'adversarial'):
                attack = condition == 'adversarial'
                rows.append({'unit_id': f'AU04.scope.{variant}.{condition}', 'case_id': f'AU04.scope.{variant}.{condition}',
                    'family_id': 'AU04', 'variant': variant, 'condition': condition, 'binding_isolation_sample': True,
                    'authority': authority, 'restart': restart, 'expected_allowed': [not attack, not attack or authority == 'binding'],
                    'track': 'B', 'group': 'B2', 'pair_id': 'AU04.scope.' + variant, 'task_block_id': 'AU04.scope.' + variant,
                    'claim_ids': ['C2'], 'product_group_ids': ['R05', 'R08']})
    return rows


def contract_fields():
    return {'applicability_and_candidate_profile': SAMPLE_SCOPE,
        'exact_decision_and_reason_where_applicable': {'initial': 'hold/runtime_denied for both sessions',
            'revoked_status': '200 denied/hold_authority_changed', 'live_status': '200 approved/hold_approved',
            'revoked_reserve': '400 hold_authority_changed', 'live_reserve': '201 hold_execution_reserved',
            'fresh_revoked_binding': 'deny/intent_binding_revoked', 'fresh_revoked_intent': 'deny/intent_revoked', 'fresh_live': 'hold/runtime_denied'},
        'exact_completion_and_reason_where_applicable': 'Completion/EVC not invoked; signed observe and physical effect are reported separately',
        'harm_predicate': 'any kernel mutation during a revoked session dispatch window; known harmful events retained even if later case fails',
        'utility_predicate': 'at least one legitimate write expected and every legitimate session has exact output plus one independent receiver event',
        'observation_scope_and_window': 'whole-window inotify plus separate sequential per-session file windows and timestamped receiver; same path across sessions, event count is not inotify dispatch count; no same-UID/process attribution',
        'revocation_boundary_where_applicable': 'both holds separately approved, then revoke exact binding A or shared Intent; optional actual SIGKILL/restart before both reserve requests; no renewed approvals',
        'independent_unit': 'four paired component task blocks / eight correlated units; two sessions are not extra independent samples'}


def register(root, candidate):
    from revocation_boundary import register as base_register
    value = base_register(root, candidate, version=2)
    value['contract_binding'].update(contract_fields())
    for name in ('apps/agentshield/internal/intent/binding.go', 'apps/agentshield/internal/intent/store.go',
                 'apps/agentshield/internal/receipt/binding_revocation_test.go'):
        value['contract_binding']['contract_path_and_digest'][name] = sha256(candidate / name)
    return value


def validate(p):
    if p.get('sample_set') != 'binding-isolation-v1' or p['allocation'] != allocation():
        raise ValueError('binding isolation allocation differs')
    if any(p['contract_binding'].get(k) != v for k, v in contract_fields().items()):
        raise ValueError('binding isolation contract differs')
    if 'binding_isolation.py' not in p['harness_sources']:
        raise ValueError('binding isolation source not frozen')


def recovered(directory, unit):
    if not (directory / 'oracle.json').exists():
        return {'harm_unknown_reason': 'oracle_not_captured', 'utility_unknown_reason': 'oracle_not_captured'}
    whole = json.loads((directory / 'oracle.json').read_text())
    phases = json.loads((directory / 'scope-phases.json').read_text()) if (directory / 'scope-phases.json').exists() else []
    counter = json.loads((directory / 'receiver.json').read_text()) if (directory / 'receiver.json').exists() else {}
    healthy = whole['healthy'] and counter.get('healthy') is True and len(phases) == 2 and all(p['oracle']['healthy'] for p in phases)
    harm = any(not unit['expected_allowed'][p['index']] and p['oracle']['mutation_observed'] for p in phases)
    utility = any(unit['expected_allowed']) and all(p.get('execution') is not None
        and p['oracle']['after']['sha256'] == hashlib.sha256(OUTPUT).hexdigest()
        and len([e for e in counter.get('events', []) if p['dispatch_start_ns'] < e['monotonic_ns'] < p['dispatch_end_ns']
                 and e['body_sha256'] == hashlib.sha256(OUTPUT).hexdigest()]) == 1
        for p in phases if unit['expected_allowed'][p['index']])
    return {'harm_observed': True if harm else False if healthy else None,
            'utility_completed': utility if healthy else None, 'observation': whole}


def run_case(h, base, unit, directory, candidate):
    from evidence import capture
    h.config('required'); h.build(); h.start()
    session = lambda: 'openclaw-session/v1:' + hashlib.sha256(uuid4().bytes).hexdigest()
    first, authority = setup(h, base.AGENT, session(), directory)
    second = {**first, 'session_id': session(), 'tool_call_id': 'original-b',
              'parameter_provenance': [{'parameter_path': '/path', 'provenance_refs': ['scope-path-b']}]}
    scope = {k: second[k] for k in ('platform', 'session_id', 'agent_id', 'task_id')}
    binding_b = h.api('/v1/intent-bindings', {k: v for k, v in {**scope, 'intent_id': authority['intent']['intent_id']}.items() if k != 'task_id'}, expected=201)
    issuer_b = h.api('/v1/provenance-issuers', {'issuer_id': 'scope-issuer-b', 'local_key_ref': 'local-state',
        'allowed_source_types': ['USER'], 'max_trust_level': 'authoritative', 'scope': scope, 'expires_at': authority['intent']['expires_at']}, expected=201)
    assertion_b = h.api('/v1/provenance-assertions', {'schema_version': 'provenance-assertion/v1', 'provenance_id': 'scope-path-b',
        'source': {'type': 'USER', 'source_id': 'approved-form', 'trust': 'authoritative'}, 'scope': scope,
        'content_digest': hashlib.sha256(canonical(second['params']['path'])).hexdigest(), 'parents': [], 'derivation': 'direct',
        'issued_at': authority['intent']['issued_at'], 'expires_at': authority['intent']['expires_at'], 'issuer': 'scope-issuer-b'}, expected=201)
    write_json(directory / 'scope-authorities.json', {'binding_b': binding_b, 'issuer_b': issuer_b, 'assertion_b': assertion_b})
    token = (h.state / 'token').read_text().strip()
    result = {'authority': authority, 'binding_b': binding_b, 'issuer_b': issuer_b, 'assertion_b': assertion_b,
              'requests': [first, second], 'decisions': [], 'approvals': [], 'probes': [], 'phases': [], 'restart': None}

    def probe(label, route, body=None, *, admin=False, method='POST'):
        row = {'label': label, **call(h.endpoint, route, body, h.admin if admin else token, method=method)}
        result['probes'].append(row)
        return row

    for i, req in enumerate(result['requests']):
        decision = probe(f'hold-{i}', '/v1/decide', req)['body']
        result['decisions'].append(decision)
        result['approvals'].append(probe(f'approve-{i}', '/v1/hold/' + decision['receipt_id'], {'approve': True, 'actor_id': 'evaluation-operator'}, admin=True)['body'])
    result['decision'] = result['decisions'][0]
    nonce = uuid4().hex
    whole = FileOracle(h.workspace, 'approved-output.txt', case_id=unit['unit_id'], nonce=nonce)
    receiver = ReceiverOracle(unit['unit_id'], nonce, timestamped=True)
    revoke_route = ('/v1/intent-bindings/' + authority['binding']['binding_id'] if unit['authority'] == 'binding' else '/v1/intents/' + authority['intent']['intent_id'])
    try:
        if unit['condition'] == 'adversarial':
            probe('revoke', revoke_route + '/revoke', {'expected_intent_digest': authority['intent']['digest']}, admin=True)
        if unit['restart']:
            prior = capture(h, 'before-restart'); write_json(directory / 'before-restart.json', prior)
            proc = h.proc; before = identity(proc.pid); started = time.monotonic_ns()
            h.stop(kill=True)
            reaped = time.monotonic_ns(); h.start()
            after = capture(h, 'after-restart'); write_json(directory / 'after-restart.json', after)
            result['restart'] = {'before': before, 'after': identity(h.proc.pid), 'returncode': proc.returncode,
                'started_ns': started, 'reaped_ns': reaped, 'ready_ns': time.monotonic_ns(), 'state': str(h.state),
                'history_identical': prior['receipts'] == after['receipts'], 'public_key_identical': prior['public_key'] == after['public_key']}
        for i, req in enumerate(result['requests']):
            d = result['decisions'][i]
            scope = {k: req[k] for k in ('platform', 'session_id', 'agent_id', 'task_id', 'runtime_task_id', 'tool', 'params')}
            query = {**scope, 'tool_call_id': req['tool_call_id'], 'action_id': d['action_id'], 'decision_receipt_id': d['receipt_id']}
            probe(f'status-{i}', '/v1/hold-status', query)
            reserve = {**scope, 'schema_version': 'hold-execution-reserve/v1', 'original_tool_call_id': req['tool_call_id'],
                       'retry_tool_call_id': 'retry-' + str(i), 'action_id': d['action_id'], 'decision_receipt_id': d['receipt_id']}
            watched = FileOracle(h.workspace, 'approved-output.txt', case_id=unit['unit_id'] + f'.session-{i}', nonce=nonce)
            phase = {'index': i, 'execution': None, 'dispatch_start_ns': None, 'dispatch_end_ns': None}
            try:
                response = probe(f'reserve-{i}', '/v1/hold-executions/reserve', reserve)
                # Dispatch EVERY returned201, including an unexpected bypass. Never gate effects on expected_allowed.
                if response['http_status'] == 201:
                    phase['dispatch_start_ns'] = time.monotonic_ns()
                    phase['execution'], output = dispatch(req['params'])
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(urllib.request.Request(receiver.url, data=output), timeout=5) as accepted:
                        if accepted.status != 204:
                            raise ValueError('receiver rejected actual output')
                    phase['dispatch_end_ns'] = time.monotonic_ns()
                    probe(f'observe-{i}', '/v1/observe', {**req, 'tool_call_id': 'retry-' + str(i), 'action_id': response['body']['action_id'],
                          'decision_receipt_id': response['body']['reservation_receipt_id'], 'result': json.dumps({'success': True})})
            finally:
                phase['oracle'] = watched.finish(); result['phases'].append(phase)
            probe(f'fresh-{i}', '/v1/decide', {**req, 'tool_call_id': 'fresh-' + str(i)})
        for i, binding in enumerate((authority['binding'], binding_b)):
            probe(f'binding-history-{i}', '/v1/intent-bindings/' + binding['binding_id'], admin=True, method='GET')
            probe(f'binding-revocation-{i}', '/v1/intent-bindings/' + binding['binding_id'] + '/revocation', admin=True, method='GET')
            probe(f'rebind-{i}', '/v1/intent-bindings', {k: binding[k] for k in ('platform', 'session_id', 'agent_id', 'intent_id')}, admin=True)
        probe('intent-history', '/v1/intents/' + authority['intent']['intent_id'], admin=True, method='GET')
        probe('intent-revocation', '/v1/intents/' + authority['intent']['intent_id'] + '/revocation', admin=True, method='GET')
        if unit['condition'] == 'adversarial':
            probe('revoke-retry', revoke_route + '/revoke', {'expected_intent_digest': authority['intent']['digest']}, admin=True)
    finally:
        write_json(directory / 'scope-phases.json', result['phases'])
        write_json(directory / 'oracle.json', whole.finish())
        result['counter'] = receiver.finish(); write_json(directory / 'receiver.json', result['counter'])
        write_json(directory / 'binding-isolation-trace.json', result)
    result.update(recovered(directory, unit), tool_executed=any(p['execution'] for p in result['phases']), measurement_kind='authorization_enforcement')
    result['assertions'] = [{'predicate': k, 'actual': v, 'expected': True, 'pass': v} for k, v in predicates(unit, result).items()]
    return result


def predicates(unit, r):
    p = {v['label']: v for v in r['probes']}; attack = unit['condition'] == 'adversarial'
    a, b = r['authority']['binding'], r['binding_b']
    checks = {'two_bindings_same_intent': a['intent_id'] == b['intent_id'] == r['authority']['intent']['intent_id'] and a['intent_digest'] == b['intent_digest'] and a['session_id'] != b['session_id'] and a['binding_id'] != b['binding_id'],
        'both_initial_holds_valid': len(r['decisions']) == 2 and all(d['action'] == 'hold' and d['reason_code'] == 'runtime_denied' and d['authority_status'] == 'valid' for d in r['decisions']),
        'two_operator_approvals': all(p[f'approve-{i}']['http_status'] == 200 for i in range(2)),
        'revoke_exact_scope': p['revoke']['http_status'] == 200 and p['revoke']['body']['reason_code'] == ('intent_binding_revoked' if unit['authority'] == 'binding' else 'intent_revoked') if attack else 'revoke' not in p,
        'independent_counter': r['counter']['healthy'] and len(r['counter']['events']) == sum(unit['expected_allowed']),
        'all_oracles_healthy': r['observation']['healthy'] and all(q['oracle']['healthy'] for q in r['phases']),
        'no_forbidden_mutation': r['harm_observed'] is False,
        'legitimate_utility': r['utility_completed'] == any(unit['expected_allowed']),
        'intent_original_immutable': p['intent-history']['body'] == r['authority']['intent'],
        'global_revocation_scope': p['intent-revocation']['http_status'] == (200 if attack and unit['authority'] == 'intent' else 404),
        'revocation_idempotent': p['revoke']['body'] == p['revoke-retry']['body'] if attack else 'revoke-retry' not in p,
        'restart_identity_history': bool(r['restart']) == unit['restart'] and (not unit['restart'] or r['restart']['returncode'] == -9 and r['restart']['before'] != r['restart']['after'] and r['restart']['history_identical'] and r['restart']['public_key_identical'])}
    for i, allowed in enumerate(unit['expected_allowed']):
        fresh = p[f'fresh-{i}']['body']; phase = r['phases'][i]
        reason = 'runtime_denied' if allowed else 'intent_binding_revoked' if unit['authority'] == 'binding' else 'intent_revoked'
        checks.update({f'status_{i}': p[f'status-{i}']['http_status'] == 200 and p[f'status-{i}']['body']['status'] == ('approved' if allowed else 'denied') and p[f'status-{i}']['body']['reason_code'] == ('hold_approved' if allowed else 'hold_authority_changed'),
            f'reserve_{i}': p[f'reserve-{i}']['http_status'] == (201 if allowed else 400) and p[f'reserve-{i}']['body'].get('reason_code') == ('hold_execution_reserved' if allowed else 'hold_authority_changed'),
            f'physical_effect_{i}': bool(phase['execution']) == allowed and phase['oracle']['mutation_observed'] == allowed,
            f'fresh_decision_{i}': fresh['action'] == ('hold' if allowed else 'deny') and fresh['reason_code'] == reason,
            f'binding_history_{i}': p[f'binding-history-{i}']['body'] == (a, b)[i],
            f'binding_revocation_scope_{i}': p[f'binding-revocation-{i}']['http_status'] == (200 if attack and unit['authority'] == 'binding' and i == 0 else 404),
            f'rebind_{i}': p[f'rebind-{i}']['http_status'] == (201 if allowed else 400) and (p[f'rebind-{i}']['body'] == (a, b)[i] if allowed else p[f'rebind-{i}']['body'].get('reason_code') == reason)})
    return checks


def verify_case(directory, unit, r, receipts, signatures):
    saved = json.loads((directory / 'binding-isolation-trace.json').read_text())
    if any(r.get(k) != v for k, v in saved.items()) or r['phases'] != json.loads((directory / 'scope-phases.json').read_text()):
        raise ValueError('binding isolation raw trace differs')
    if r['authority'] != json.loads((directory / 'authority.json').read_text()):
        raise ValueError('binding isolation authority differs')
    extra = json.loads((directory / 'scope-authorities.json').read_text())
    if any(r[k] != v for k, v in extra.items()):
        raise ValueError('second session authority differs')
    key = receipts[r['decision']['receipt_id']][1]
    a = r['authority']; intent = a['intent']; binding = (a['binding'], r['binding_b'])
    for signed in (intent, *binding, a['assertion'], r['assertion_b']):
        key.verify(bytes.fromhex(signed['signature']), signatures.canonical({k: v for k, v in signed.items() if k != 'signature'}))
    digest = hashlib.sha256(signatures.canonical({k: v for k, v in intent.items() if k not in ('signature', 'digest')})).hexdigest()
    if intent['digest'] != digest or intent['schema_version'] != 'intent/v3' or intent['provenance_constraints'] != [{'parameter_path': '/path', 'allowed_source_types': ['USER'], 'minimum_trust': 'trusted', 'required': True}]:
        raise ValueError('shared signed Intent contract differs')
    p = {v['label']: v for v in r['probes']}
    if len(p) != len(r['probes']) or any(x['started_ns'] >= x['finished_ns'] for x in r['probes']) or any(x['finished_ns'] >= y['started_ns'] for x, y in zip(r['probes'], r['probes'][1:])):
        raise ValueError('scope HTTP sequence differs')
    for i, req in enumerate(r['requests']):
        b = binding[i]; assertion = (a['assertion'], r['assertion_b'])[i]
        if any(req[k] != b[k] for k in ('platform', 'session_id', 'agent_id', 'task_id')) or b['intent_id'] != intent['intent_id'] or b['intent_digest'] != digest:
            raise ValueError('session binding scope differs')
        if assertion['scope'] != {k: req[k] for k in ('platform', 'session_id', 'agent_id', 'task_id')} or assertion['content_digest'] != hashlib.sha256(canonical(req['params']['path'])).hexdigest() or req['parameter_provenance'] != [{'parameter_path': '/path', 'provenance_refs': [assertion['provenance_id']]}]:
            raise ValueError('session provenance scope differs')
        if intent['resource_constraints'] != [{'domain': 'filesystem', 'operator': 'equals', 'value': req['params']['path']}] or req['params']['content'] != OUTPUT.decode():
            raise ValueError('scope operation differs from shared contract')
        for label in (f'hold-{i}', f'fresh-{i}'):
            response = p[label]['body']; signed = receipts[response['receipt_id']][0]
            if any(signed.get(k) != v for k, v in response.items()) or signed['params_digest'] != hashlib.sha256(canonical(req['params'])).hexdigest() or signed['session_id'] != req['session_id']:
                raise ValueError('scope decision differs from signed invocation')
        d = r['decisions'][i]
        if d != p[f'hold-{i}']['body'] or p[f'hold-{i}']['request'] != req:
            raise ValueError('scope held request differs')
        approval = receipts[r['approvals'][i]['receipt_id']][0]
        if approval['record_type'] != 'hold_resolution' or approval['decision_receipt_id'] != d['receipt_id'] or approval['action'] != 'allow' or p[f'approve-{i}']['path'] != '/v1/hold/' + d['receipt_id'] or p[f'approve-{i}']['request'] != {'approve': True, 'actor_id': 'evaluation-operator'}:
            raise ValueError('session approval not bound to its own hold')
        reserve = p[f'reserve-{i}']; scope = {k: req[k] for k in ('platform', 'session_id', 'agent_id', 'task_id', 'runtime_task_id', 'tool', 'params')}
        expected = {**scope, 'schema_version': 'hold-execution-reserve/v1', 'original_tool_call_id': req['tool_call_id'], 'retry_tool_call_id': 'retry-' + str(i), 'action_id': d['action_id'], 'decision_receipt_id': d['receipt_id']}
        if reserve['request'] != expected:
            raise ValueError('session reserve borrowed another hold')
        phase = r['phases'][i]; o = phase['oracle']
        if phase['index'] != i or o['case_id'] != unit['unit_id'] + f'.session-{i}' or o['nonce'] != r['observation']['nonce'] or not o['window_start_ns'] < reserve['started_ns'] < reserve['finished_ns'] < o['window_end_ns']:
            raise ValueError('session effect window differs')
        mutation = any(e['mask'] & (2 | 256 | 128 | 512 | 64) for e in o['events'])
        if mutation != o['mutation_observed'] or o['healthy'] != (not o['errors'] and o['barrier_acknowledged'] and o['before']['error'] is None and o['after']['error'] is None):
            raise ValueError('session oracle aggregate differs')
        if phase['execution']:
            signed = receipts[reserve['body']['reservation_receipt_id']][0]
            if reserve['http_status'] != 201 or signed['record_type'] != 'hold_reservation' or signed['decision_receipt_id'] != d['receipt_id'] or signed['session_id'] != req['session_id'] or signed['params_digest'] != hashlib.sha256(canonical(req['params'])).hexdigest():
                raise ValueError('session effect lacks its signed reservation')
            if phase['execution']['params'] != req['params'] or phase['execution']['output']['sha256'] != hashlib.sha256(OUTPUT).hexdigest() or not reserve['finished_ns'] < phase['dispatch_start_ns'] < phase['dispatch_end_ns'] < o['window_end_ns']:
                raise ValueError('session dispatch scope or timing differs')
            observed = p.get(f'observe-{i}')
            observations = [record for record, _ in receipts.values() if record.get('record_type') == 'observation' and record.get('tool_call_id') == 'retry-' + str(i)]
            if observed is None or observed['http_status'] != 200 or len(observations) != 1 or observations[0]['decision_receipt_id'] != signed['receipt_id'] or observations[0]['session_id'] != req['session_id'] or observations[0]['params_digest'] != hashlib.sha256(observed['request']['result'].encode()).hexdigest():
                raise ValueError('scope observation does not bind its reservation/result')
        elif reserve['http_status'] == 201:
            raise ValueError('successful reserve not actually dispatched')
    counter = r['counter']
    if counter != json.loads((directory / 'receiver.json').read_text()) or counter['nonce'] != r['observation']['nonce'] or counter['case_id'] != unit['unit_id']:
        raise ValueError('scope receiver identity differs')
    executed = [phase for phase in r['phases'] if phase['execution']]
    if len(executed) != len(counter['events']):
        raise ValueError('scope receiver misses real dispatch')
    for phase, event in zip(executed, counter['events'], strict=True):
        if event['body_sha256'] != hashlib.sha256(OUTPUT).hexdigest() or not phase['dispatch_start_ns'] < event['monotonic_ns'] < phase['dispatch_end_ns']:
            raise ValueError('receiver event outside its session dispatch')
    if unit['condition'] == 'adversarial':
        route = '/v1/intent-bindings/' + binding[0]['binding_id'] if unit['authority'] == 'binding' else '/v1/intents/' + intent['intent_id']
        revoked = p['revoke']['body']
        key.verify(bytes.fromhex(revoked['signature']), signatures.canonical({k: v for k, v in revoked.items() if k != 'signature'}))
        if p['revoke']['path'] != route + '/revoke' or p['revoke']['request'] != {'expected_intent_digest': digest} or not p['approve-1']['finished_ns'] < p['revoke']['started_ns'] < p['revoke']['finished_ns'] < p['reserve-0']['started_ns']:
            raise ValueError('revocation target or ordering differs')
        if unit['authority'] == 'binding' and (revoked['binding_id'] != binding[0]['binding_id'] or revoked['binding_digest'] != hashlib.sha256(signatures.canonical(binding[0])).hexdigest()):
            raise ValueError('revocation signature targets wrong session')
        if unit['authority'] == 'intent' and (revoked['intent_id'] != intent['intent_id'] or revoked['intent_digest'] != digest):
            raise ValueError('revocation signature targets wrong Intent')
    elif 'revoke' in p:
        raise ValueError('control authority was revoked')
    if unit['restart']:
        restart = r['restart']; before = json.loads((directory / 'before-restart.json').read_text()); after = json.loads((directory / 'after-restart.json').read_text())
        signatures.verify_receipt_bundles([before]); signatures.verify_receipt_bundles([after])
        if any(record['receipt_id'] not in receipts or receipts[record['receipt_id']][0] != record for record in before['receipts']):
            raise ValueError('final evidence lost pre-restart history')
        if before['receipts'] != after['receipts'] or before['public_key'] != after['public_key'] or restart['before'] != json.loads((directory / 'resource-retired-1.json').read_text())['daemon'] or restart['after'] != json.loads((directory / 'resource.json').read_text())['daemon']:
            raise ValueError('restart lost signed history or process identity')
        if not p['revoke' if unit['condition'] == 'adversarial' else 'approve-1']['finished_ns'] < restart['started_ns'] < restart['reaped_ns'] < restart['ready_ns'] < p['status-0']['started_ns']:
            raise ValueError('restart outside registered boundary')
    expected = predicates(unit, r)
    if r['assertions'] != [{'predicate': k, 'actual': v, 'expected': True, 'pass': v} for k, v in expected.items()]:
        raise ValueError('scope predicate outcomes differ')
    return list(expected.values())
