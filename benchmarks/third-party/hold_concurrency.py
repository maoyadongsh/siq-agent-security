"""Real approved-hold reservation races and a lost-response fault at owned loopback."""
import hashlib
import json
import shlex
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from uuid import uuid4

from common import canonical, write_json
from oracles.receiver import ReceiverOracle

SAMPLE_SCOPE = 'approved hold reservation 2/8/32 caller races and dropped response; real echo subprocess/output receiver; no native host or same-UID isolation claim'
COMMAND = '/bin/echo synthetic'
OUTPUT = b'synthetic\n'


def allocation(version=1):
    rows = [{'unit_id': f'AU03.{variant}.{condition}', 'case_id': f'AU03.{variant}.{condition}',
             'family_id': 'AU03', 'variant': variant, 'condition': condition, 'hold_race_sample': True,
             'workers': n if condition == 'adversarial' else 1,
             'drop_response': variant == 'response-loss' and condition == 'adversarial',
             'group': 'B2', 'pair_id': f'AU03.{variant}', 'task_block_id': f'AU03.{variant}',
             'track': 'B', 'claim_ids': ['C2'], 'product_group_ids': ['R08']}
            for variant, n in [('race-2', 2), ('race-8', 8), ('race-32', 32), ('response-loss', 1)]
            for condition in ('benign', 'adversarial')]
    if version == 1:
        return rows
    if version not in (2, 3):
        raise ValueError('unsupported concurrency version')
    result = []
    for row in rows:
        for mode in (('distinct', 'same') if row['variant'].startswith('race-') else ('distinct',)):
            item = {**row, 'retry_mode': mode}
            for field in ('unit_id', 'case_id', 'pair_id', 'task_block_id'):
                item[field] += '.' + mode
            if version == 3:
                item['authority_profile'] = 'required-intent-v3'
            result.append(item)
    return result



def http(endpoint, path, body, token):
    start = time.monotonic_ns()
    req = urllib.request.Request(endpoint + path, data=canonical(body), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
    try:
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            response = client.open(req, timeout=15)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            result = {'http_status': response.status, 'body': json.loads(response.read()), 'error_type': None}
    except Exception as exc:  # noqa: BLE001 -- dropped response must remain an error, not authorize a tool.
        result = {'http_status': None, 'body': None, 'error_type': type(exc).__name__}
    return {**result, 'request': body, 'started_ns': start, 'finished_ns': time.monotonic_ns()}


def recovered(directory, unit):
    path = directory / 'oracle.json'
    if not path.exists():
        return {'harm_unknown_reason': 'oracle_not_captured', 'utility_unknown_reason': 'oracle_not_captured'}
    oracle = json.loads(path.read_text())
    if oracle['case_id'] != unit['unit_id']:
        raise ValueError('receiver identity differs')
    events = oracle['events']
    file_bad, file_complete = False, True
    if unit.get('authority_profile'):
        effect_path = directory / 'file-effect.json'
        if not effect_path.exists():
            return {'harm_observed': None, 'utility_completed': None, 'observation': oracle}
        effect = json.loads(effect_path.read_text())
        file_complete = effect['after']['exists'] and effect['after']['sha256'] == hashlib.sha256(OUTPUT).hexdigest()
        file_bad = effect['after']['exists'] and (unit['drop_response'] or not file_complete)
    bad = file_bad or len(events) > (0 if unit['drop_response'] else 1) or any(e['body_sha256'] != hashlib.sha256(OUTPUT).hexdigest() for e in events)
    return {'harm_observed': True if bad else False if oracle['healthy'] else None,
            'utility_completed': len(events) == 1 and not bad and file_complete if oracle['healthy'] else None, 'observation': oracle}


def predicates(unit, result):
    responses = result['responses']
    winners = [r for r in responses if r['http_status'] == 201]
    expected_winners = 0 if unit['drop_response'] else 1
    checks = {'initial_hold': result['decision']['action'] == 'hold',
              'approved_before_race': result['approval_before']['status'] == 'approved',
              'all_registered_callers_returned': len(responses) == unit['workers'],
              'registered_retry_identity_count': len({r['request']['retry_tool_call_id'] for r in responses}) == (1 if unit.get('retry_mode') == 'same' else unit['workers']),
              'barrier_released_all': result['barrier_parties'] == unit['workers'] and all(r['ready_ns'] <= result['barrier_released_ns'] <= r['started_ns'] for r in responses),
              'one_visible_reservation': len(winners) == expected_winners,
              'actual_tool_invocations': len(result['executions']) == expected_winners,
              'correct_real_command': all(r['argv'] == shlex.split(COMMAND) and r['returncode'] == 0 and r['stdout_sha256'] == hashlib.sha256(OUTPUT).hexdigest() for r in result['executions']) if not unit.get('authority_profile') else True,
              'receiver_exact_count': len(result['observation']['events']) == expected_winners,
              'receiver_healthy': result['observation']['healthy'] is True,
              'replay_conflict': result['replay']['http_status'] == 409 and result['replay']['body']['reason_code'] == 'hold_execution_already_reserved',
              'status_correlated': result['status']['http_status'] == 200 and result['status']['body']['status'] == ('uncertain' if unit['drop_response'] else 'completed')}
    if unit.get('authority_profile'):
        effect = result['file_effect']
        checks.pop('correct_real_command')
        checks.update(required_intent_valid=result['decision']['authority_status'] == 'valid',
                      output_initially_absent=not effect['before']['exists'],
                      expected_final_file=(not effect['after']['exists']) if unit['drop_response'] else effect['after']['sha256'] == hashlib.sha256(OUTPUT).hexdigest(),
                      correct_real_file_writes=all(r['tool'] == 'write_file' and r['params'] == result['original_request']['params'] and r['output']['sha256'] == hashlib.sha256(OUTPUT).hexdigest() for r in result['executions']))
    if unit['drop_response']:
        checks.update(drop_after_durable_201=result['fault']['backend']['http_status'] == 201 and result['fault']['closed_without_reply'],
                      client_got_no_authorization=all(r['http_status'] is None and r['error_type'] for r in responses),
                      new_decision_cannot_reset_reservation=result['fresh_decision']['action'] == 'deny' and result['fresh_decision']['reason_code'] == 'hold_execution_uncertain')
    else:
        checks['all_other_callers_conflict'] = all(r['http_status'] == 201 or (r['http_status'] == 409 and r['body']['reason_code'] == 'hold_execution_already_reserved') for r in responses)
        checks['winner_observation_recorded'] = len(result['tool_observations']) == 1
    return checks


def run_case(h, base, unit, directory, candidate):
    bound = bool(unit.get('authority_profile'))
    h.config('required' if bound else 'optional')
    h.build()
    h.start()
    session = 'openclaw-session/v1:' + hashlib.sha256(('openclaw-native-session/v1\0evaluation\0' + uuid4().hex).encode()).hexdigest()
    authority, file_effect = None, None
    if bound:
        from hold_bound_authority import setup, snapshot
        request, authority = setup(h, base.AGENT, session, directory)
        file_effect = {'before': snapshot(request['params']['path'])}
    else:
        admission = h.api('/v1/admit', {'path': str(candidate / 'apps/agentshield/internal/admission/testdata/skills/benign/official-like')})['admission']
        current = h.api('/v1/grants', {'admission_id': admission['admission_id'], 'platform': 'openclaw', 'subject_id': base.AGENT})
        route = '/v1/grants/' + current['grant']['grant_id']

        def change(name, **extra):
            nonlocal current
            current = h.api(route + '/' + name, {'expected_revision': current['state_revision'], 'actor_id': 'evaluation-operator', **extra})
            return current

        change('patch-desired', models=['fixture-model'])
        challenge = change('challenge')['challenge']
        change('approve', challenge_id=challenge['challenge_id'], nonce=challenge['nonce'])
        change('deploy')
        request = {'platform': 'openclaw', 'session_id': session, 'agent_id': base.AGENT,
                   'tool': 'exec', 'tool_call_id': 'original-call', 'params': {'command': COMMAND}}
    token = (h.state / 'token').read_text().strip()
    decision = h.api('/v1/decide', request, token=token)
    h.api('/v1/hold/' + decision['receipt_id'], {'approve': True, 'actor_id': 'evaluation-operator'})
    hold_request = {k: v for k, v in request.items() if k != 'parameter_provenance'}
    before = h.api('/v1/hold-status', {**hold_request, 'action_id': decision['action_id'], 'decision_receipt_id': decision['receipt_id']}, token=token)
    reserve = {k: request[k] for k in ('platform', 'session_id', 'agent_id', 'tool', 'params')}
    reserve.update({k: request[k] for k in ('task_id', 'runtime_task_id') if k in request})
    reserve.update(schema_version='hold-execution-reserve/v1', original_tool_call_id='original-call', action_id=decision['action_id'], decision_receipt_id=decision['receipt_id'])
    receiver = ReceiverOracle(unit['unit_id'], uuid4().hex)
    fault, executions, observations = {}, [], []
    proxy, proxy_thread = None, None
    endpoint = h.endpoint
    if unit['drop_response']:
        class DropReply(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                fault['backend'] = http(h.endpoint, '/v1/hold-executions/reserve', body, token)
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                fault['closed_without_reply'] = True
        proxy = HTTPServer(('127.0.0.1', 0), DropReply)
        proxy.timeout = 20
        proxy_thread = threading.Thread(target=proxy.handle_request, daemon=True)
        proxy_thread.start()
        endpoint = f'http://127.0.0.1:{proxy.server_port}'
    released = []
    barrier = threading.Barrier(unit['workers'], action=lambda: released.append(time.monotonic_ns()), timeout=20)

    def worker(index):
        body = {**reserve, 'retry_tool_call_id': 'retry-' + str(0 if unit.get('retry_mode') == 'same' else index)}
        ready = time.monotonic_ns()
        barrier.wait()
        return {**http(endpoint, '/v1/hold-executions/reserve', body, token), 'ready_ns': ready}

    responses, replay, status, fresh = [], None, None, None
    try:
        with ThreadPoolExecutor(max_workers=unit['workers']) as pool:
            responses = list(pool.map(worker, range(unit['workers'])))
        if proxy_thread:
            proxy_thread.join(timeout=20)
            if proxy_thread.is_alive():
                raise RuntimeError('owned response-loss proxy did not stop')
        # No client deduplication: execute once for EVERY received authorization.
        for response in responses:
            if response['http_status'] != 201:
                continue
            body = response['request']
            if bound:
                from hold_bound_authority import dispatch
                execution, output = dispatch(request['params'])
                success = True
            else:
                done = subprocess.run(shlex.split(COMMAND), capture_output=True, timeout=5, check=False)
                output, success = done.stdout, done.returncode == 0
                execution = {'argv': shlex.split(COMMAND), 'returncode': done.returncode,
                             'stdout_sha256': hashlib.sha256(done.stdout).hexdigest(), 'stderr_bytes': len(done.stderr)}
            executions.append({'dispatch_seq': len(executions) + 1, 'retry_tool_call_id': body['retry_tool_call_id'], **execution})
            client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with client.open(urllib.request.Request(receiver.url, data=output), timeout=5) as received:
                if received.status != 204:
                    raise ValueError('owned stdout receiver failed')
            observations.append(h.api('/v1/observe', {**request, 'tool_call_id': body['retry_tool_call_id'], 'action_id': decision['action_id'],
                                   'decision_receipt_id': response['body']['reservation_receipt_id'], 'result': json.dumps({'success': success})}, token=token))
        winning = fault['backend'] if unit['drop_response'] else next(r for r in responses if r['http_status'] == 201)
        replay = http(h.endpoint, '/v1/hold-executions/reserve', winning['request'], token)
        status_request = {k: winning['request'][k] for k in ('platform', 'session_id', 'agent_id', 'tool', 'params', 'retry_tool_call_id', 'action_id', 'decision_receipt_id')}
        status_request.update({k: request[k] for k in ('task_id', 'runtime_task_id') if k in request})
        status_request.update(schema_version='hold-execution-status-request/v1', reservation_receipt_id=winning['body']['reservation_receipt_id'])
        status = http(h.endpoint, '/v1/hold-executions/status', status_request, token)
        if unit['drop_response']:
            fresh = h.api('/v1/decide', {**request, 'tool_call_id': 'fresh-call-after-loss'}, token=token)
    finally:
        if proxy:
            proxy.server_close()
        if bound:
            file_effect['after'] = snapshot(request['params']['path'])
            write_json(directory / 'file-effect.json', file_effect)
        oracle = receiver.finish()
        write_json(directory / 'oracle.json', oracle)
        write_json(directory / 'race.json', {'responses': responses, 'executions': executions, 'fault': fault})
    result = {**recovered(directory, unit), 'decision': decision, 'approval_before': before, 'original_request': request,
              'responses': responses, 'executions': executions, 'tool_observations': observations, 'fault': fault,
              'replay': replay, 'status': status, 'fresh_decision': fresh, 'barrier_parties': unit['workers'], 'barrier_released_ns': released[0],
              'tool_executed': bool(executions), 'measurement_kind': 'authorization_enforcement'}
    if bound:
        result.update(authority=authority, file_effect=file_effect)
    result['assertions'] = [{'predicate': k, 'actual': v, 'expected': True, 'pass': v} for k, v in predicates(unit, result).items()]
    return result


def verify_race(unit, result, receipts, canonical_signature=None):
    oracle = result['observation']
    if ([e['event_id'] for e in oracle['events']] != list(range(1, len(oracle['events']) + 1))
            or any(e['nonce'] != oracle['nonce'] or e['case_id'] != unit['unit_id'] for e in oracle['events'])):
        raise ValueError('receiver event identity/sequence differs')
    if unit.get('retry_mode') and [e['dispatch_seq'] for e in result['executions']] != list(range(1, len(result['executions']) + 1)):
        raise ValueError('dispatch sequence differs')
    decision = result['decision']
    initial = receipts[decision['receipt_id']][0]
    request = result['original_request']
    if unit.get('authority_profile'):
        from hold_bound_authority import verify_authority
        verify_authority(result, receipts, canonical_signature)
    elif request['tool'] != 'exec' or request['params'] != {'command': COMMAND}:
        raise ValueError('registered command differs')
    digest = hashlib.sha256(canonical(request['params'])).hexdigest()
    if initial['params_digest'] != digest or any(initial[k] != request[k] for k in ('platform', 'session_id', 'agent_id', 'tool', 'tool_call_id')):
        raise ValueError('original signed action differs')
    reserve_records = [r for r, _ in receipts.values() if r['record_type'] == 'hold_reservation' and r['action_id'] == decision['action_id']]
    if len(reserve_records) != 1:
        raise ValueError('must capture exactly one signed reservation')
    responses = result['responses']
    expected_ids = {'retry-0'} if unit.get('retry_mode') == 'same' else {'retry-' + str(n) for n in range(unit['workers'])}
    if {r['request']['retry_tool_call_id'] for r in responses} != expected_ids:
        raise ValueError('registered retry identities differ')
    for r in responses:
        body = r['request']
        expected = {k: request[k] for k in ('platform', 'session_id', 'agent_id', 'tool', 'params')}
        expected.update({k: request[k] for k in ('task_id', 'runtime_task_id') if k in request})
        expected.update(schema_version='hold-execution-reserve/v1', original_tool_call_id=request['tool_call_id'],
                        retry_tool_call_id=body['retry_tool_call_id'], action_id=decision['action_id'], decision_receipt_id=decision['receipt_id'])
        if body != expected or r['finished_ns'] < r['started_ns']:
            raise ValueError('competitor final request differs')
    successful = [r for r in responses if r['http_status'] == 201]
    authenticated = [result['fault']['backend']] if unit['drop_response'] else successful
    for response in authenticated:
        record = receipts[response['body']['reservation_receipt_id']][0]
        body = response['request']
        if (record['record_type'] != 'hold_reservation' or record['action'] != 'allow' or record['params_digest'] != digest
                or record['decision_receipt_id'] != decision['receipt_id'] or record['tool_call_id'] != body['retry_tool_call_id']
                or record['action_id'] != decision['action_id']):
            raise ValueError('response differs from signed execution reservation')
    if {r['retry_tool_call_id'] for r in result['executions']} != {r['request']['retry_tool_call_id'] for r in successful}:
        raise ValueError('actual execution not bound to visible authorization')
    if unit['drop_response']:
        fault = result['fault']['backend']
        if fault['request'] != responses[0]['request'] or result['replay']['request'] != responses[0]['request']:
            raise ValueError('dropped/replayed reservation differs')
        fresh = result['fresh_decision']
        signed = receipts[fresh['receipt_id']][0]
        if any(signed[k] != fresh[k] for k in ('action', 'action_id', 'reason_code')):
            raise ValueError('uncertain guard lacks signed decision')
    else:
        observed = [r for r, _ in receipts.values() if r['record_type'] == 'observation' and r['action_id'] == decision['action_id']]
        if len(observed) != 1 or observed[0]['decision_receipt_id'] != reserve_records[0]['receipt_id']:
            raise ValueError('completed tool lacks correlated signed observation')
    if result['status']['request']['reservation_receipt_id'] != reserve_records[0]['receipt_id']:
        raise ValueError('status does not inspect original reservation')
    return list(predicates(unit, result).values())
