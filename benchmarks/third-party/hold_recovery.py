"""Approved effect replay and real SIGKILL recovery with durable receipts."""
import hashlib
import json
import socket
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from itertools import pairwise
from uuid import uuid4

from common import write_json
from hold_bound_authority import OUTPUT, dispatch, setup, snapshot, verify_authority
from hold_concurrency import http
from hold_concurrency import recovered as file_score
from oracles.receiver import ReceiverOracle
from process_resources import identity

SAMPLE_SCOPE = 'required Intent v3 API: same-process/restart replay and SIGKILL before reserve/after reserve/after file dispatch; no native SEC or observer revocation claim'


def allocation(version=1):
    units = []
    variants = [('AU02', 'same-process-replay'), ('AU02', 'restart-replay'),
                ('AU05', 'before-reserve'), ('AU05', 'after-reserve'), ('AU05', 'after-dispatch')]
    if version == 2:
        variants.append(('AU05', 'observe-response-loss'))
    elif version != 1:
        raise ValueError('unsupported recovery version')
    for family, variant in variants:
        for condition in ('benign', 'adversarial'):
            adversarial = condition == 'adversarial'
            uncertain = adversarial and variant in ('after-reserve', 'after-dispatch')
            units.append({'unit_id': f'{family}.{variant}.{condition}', 'case_id': f'{family}.{variant}.{condition}',
                          'family_id': family, 'variant': variant, 'condition': condition, 'recovery_sample': True,
                          'group': 'B2', 'pair_id': family + '.' + variant, 'task_block_id': family + '.' + variant,
                          'track': 'B', 'claim_ids': ['C2'], 'product_group_ids': ['R08'],
                          'authority_profile': 'required-intent-v3', 'drop_response': adversarial and variant == 'after-reserve',
                          'expected_effects': 0 if adversarial and variant == 'after-reserve' else 1,
                          'expected_status': 'uncertain' if uncertain else 'completed',
                          'restart_stage': variant if adversarial and family == 'AU05' and variant != 'observe-response-loss' else None if variant == 'same-process-replay' else 'after-observe'})
    if version == 2:
        for unit in units:
            unit['observe_response_loss'] = unit['variant'] == 'observe-response-loss' and unit['condition'] == 'adversarial'
    return units


def recovered(directory, unit):
    return file_score(directory, unit)


def predicates(unit, result):
    requests = result['requests']
    checkpoints = result['restart_checkpoints']
    expected = unit['expected_effects']
    status = result['status']
    checks = {'initial_valid_hold': result['decision']['action'] == 'hold' and result['decision']['authority_status'] == 'valid',
              'human_approved': result['approval_before']['status'] == 'approved',
              'first_reservation_created': requests['reserve']['http_status'] == 201 and requests['reserve']['body']['reason_code'] == 'hold_execution_reserved',
              'one_registered_restart': len(checkpoints) == (0 if unit['restart_stage'] is None else 1),
              'actual_sigkill_then_new_process': all(c['returncode'] == -9 and c['old_process'] != c['new_process'] and c['old_reaped'] for c in checkpoints),
              'correct_fault_boundary': all(c['stage'] == unit['restart_stage'] for c in checkpoints),
              'same_persistent_authority': all(c['state_dir_before'] == c['state_dir_after'] and c['public_key_before'] == c['public_key_after'] for c in checkpoints),
              'file_initially_absent': not result['file_effect']['before']['exists'],
              'real_effect_count': len(result['executions']) == len(result['observation']['events']) == expected,
              'correct_file': result['file_effect']['after']['sha256'] == hashlib.sha256(OUTPUT).hexdigest() if expected else not result['file_effect']['after']['exists'],
              'healthy_receiver': result['observation']['healthy'] is True,
              'correct_recovered_status': status['http_status'] == 200 and status['body']['status'] == unit['expected_status'] and status['body']['reason_code'] == 'hold_execution_' + unit['expected_status'],
              'no_duplicate_after_replay': len(result['executions']) <= 1,
              'expected_utility': result['utility_completed'] == bool(expected)}
    if unit['condition'] == 'adversarial':
        replay = requests['replay']
        checks['replay_conflict'] = replay['http_status'] == 409 and replay['body']['reason_code'] == 'hold_execution_already_reserved'
    if unit['expected_status'] == 'uncertain':
        fresh = requests['fresh_decision']['body']
        checks['fresh_call_does_not_reset_uncertainty'] = fresh['action'] == 'deny' and fresh['reason_code'] == 'hold_execution_uncertain'
        checks['observation_not_fabricated'] = not result['tool_observations']
    else:
        checks['signed_observation_recorded'] = len(result['tool_observations']) == 1 or (unit.get('observe_response_loss') is True and result['observe_fault']['backend']['http_status'] == 200)
    if unit.get('observe_response_loss'):
        checks['observation_reply_really_lost'] = result['observe_fault']['closed_without_reply'] and result['observe_client']['http_status'] is None and bool(result['observe_client']['error_type'])
        checks['client_did_not_receive_observation'] = not result['tool_observations']
    return checks


def run_case(h, base, unit, directory, candidate):
    from evidence import capture
    h.config('required')
    h.build()
    h.start()
    session = 'openclaw-session/v1:' + hashlib.sha256(('recovery-fixture-' + uuid4().hex).encode()).hexdigest()
    request, authority = setup(h, base.AGENT, session, directory)
    token = (h.state / 'token').read_text().strip()
    decision = h.api('/v1/decide', request, token=token)
    approval = h.api('/v1/hold/' + decision['receipt_id'], {'approve': True, 'actor_id': 'evaluation-operator'})
    hold_request = {k: v for k, v in request.items() if k != 'parameter_provenance'}
    before = h.api('/v1/hold-status', {**hold_request, 'action_id': decision['action_id'], 'decision_receipt_id': decision['receipt_id']}, token=token)
    reserve = {k: request[k] for k in ('platform', 'session_id', 'agent_id', 'task_id', 'runtime_task_id', 'tool', 'params')}
    reserve.update(schema_version='hold-execution-reserve/v1', original_tool_call_id=request['tool_call_id'], retry_tool_call_id='retry-once',
                   action_id=decision['action_id'], decision_receipt_id=decision['receipt_id'])
    receiver = ReceiverOracle(unit['unit_id'], uuid4().hex)
    result = {'original_request': request, 'authority': authority, 'decision': decision, 'approval_before': before, 'approval': approval,
              'file_effect': {'before': snapshot(request['params']['path'])}, 'requests': {}, 'executions': [], 'tool_observations': [],
              'restart_checkpoints': [], 'events': []}

    def event(name, **details):
        result['events'].append({'sequence': len(result['events']) + 1, 'monotonic_ns': time.monotonic_ns(), 'event': name, **details})

    def restart(stage):
        if unit['restart_stage'] != stage:
            return
        prior = capture(h, 'before-restart')
        write_json(directory / 'before-restart-evidence.json', prior)
        proc, old = h.proc, identity(h.proc.pid)
        state = str(h.state)
        event('kill_requested', stage=stage)
        h.stop(kill=True)
        event('old_process_reaped', returncode=proc.returncode)
        h.start()
        after = capture(h, 'after-restart')
        write_json(directory / 'after-restart-evidence.json', after)
        result['restart_checkpoints'].append({'stage': stage, 'old_process': old, 'new_process': identity(h.proc.pid),
                                             'returncode': proc.returncode, 'old_reaped': proc.poll() is not None,
                                             'state_dir_before': state, 'state_dir_after': str(h.state),
                                             'public_key_before': prior['public_key'], 'public_key_after': after['public_key']})
        event('new_process_ready', stage=stage)

    def execute(response, label):
        # Every client-visible 201 dispatches; replay success must expose duplicates.
        if response['http_status'] != 201:
            return
        effect, output = dispatch(request['params'])
        result['executions'].append({'dispatch_seq': len(result['executions']) + 1, 'retry_tool_call_id': 'retry-once', 'source': label, **effect})
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with client.open(urllib.request.Request(receiver.url, data=output), timeout=5) as received:
            if received.status != 204:
                raise ValueError('counter rejected real effect')
        event('file_dispatched', source=label)

    try:
        event('approved')
        restart('before-reserve')
        response = http(h.endpoint, '/v1/hold-executions/reserve', reserve, token)
        result['requests']['reserve'] = response
        event('reserve_returned', http_status=response['http_status'])
        if response['http_status'] != 201:
            raise ValueError('registered approval did not yield first reservation')
        restart('after-reserve')
        if not unit['drop_response']:
            execute(response, 'initial')
        restart('after-dispatch')
        if unit['expected_status'] == 'completed':
            observe_request = {**request, 'tool_call_id': 'retry-once', 'action_id': decision['action_id'],
                               'decision_receipt_id': response['body']['reservation_receipt_id'], 'result': json.dumps({'success': True})}
            if unit.get('observe_response_loss'):
                result['observe_client'], result['observe_fault'] = lose_observe_reply(h.endpoint, observe_request, token)
            else:
                result['tool_observations'].append(h.api('/v1/observe', observe_request, token=token))
            event('observe_returned')
        restart('after-observe')
        query = {k: reserve[k] for k in ('platform', 'session_id', 'agent_id', 'task_id', 'runtime_task_id', 'tool', 'params', 'retry_tool_call_id', 'action_id', 'decision_receipt_id')}
        query.update(schema_version='hold-execution-status-request/v1', reservation_receipt_id=response['body']['reservation_receipt_id'])
        result['status'] = http(h.endpoint, '/v1/hold-executions/status', query, token)
        event('status_returned')
        if unit['condition'] == 'adversarial':
            replay = http(h.endpoint, '/v1/hold-executions/reserve', reserve, token)
            result['requests']['replay'] = replay
            event('replay_returned', http_status=replay['http_status'])
            execute(replay, 'replay')
        if unit['expected_status'] == 'uncertain':
            fresh_request = {**request, 'tool_call_id': 'fresh-after-restart'}
            result['requests']['fresh_decision'] = http(h.endpoint, '/v1/decide', fresh_request, token)
            event('fresh_decision_returned')
    finally:
        result['file_effect']['after'] = snapshot(request['params']['path'])
        write_json(directory / 'file-effect.json', result['file_effect'])
        write_json(directory / 'oracle.json', receiver.finish())
        write_json(directory / 'recovery-trace.json', result)
    result.update(recovered(directory, unit), tool_executed=bool(result['executions']), measurement_kind='authorization_enforcement')
    result['assertions'] = [{'predicate': k, 'actual': v, 'expected': True, 'pass': v} for k, v in predicates(unit, result).items()]
    return result


def verify_recovery(directory, unit, result, receipts, signatures):
    verify_authority(result, receipts, signatures.canonical)
    original = result['original_request']
    decision = result['decision']
    signed = receipts[decision['receipt_id']][0]
    digest = hashlib.sha256(signatures.canonical(original['params'])).hexdigest()
    if signed['params_digest'] != digest or any(signed[k] != original[k] for k in ('platform', 'session_id', 'agent_id', 'tool', 'tool_call_id')):
        raise ValueError('original parameters differ')
    expected = {k: original[k] for k in ('platform', 'session_id', 'agent_id', 'task_id', 'runtime_task_id', 'tool', 'params')}
    expected.update(schema_version='hold-execution-reserve/v1', original_tool_call_id=original['tool_call_id'], retry_tool_call_id='retry-once',
                    action_id=decision['action_id'], decision_receipt_id=decision['receipt_id'])
    for name in ('reserve', 'replay'):
        if name not in result['requests']:
            continue
        response = result['requests'][name]
        if response['request'] != expected:
            raise ValueError('reserve/replay is not the original effect')
        if response['http_status'] == 201:
            reservation = receipts[response['body']['reservation_receipt_id']][0]
            if reservation['record_type'] != 'hold_reservation' or reservation['params_digest'] != digest or reservation['decision_receipt_id'] != decision['receipt_id']:
                raise ValueError('reservation signature is for another action')
    query = {k: expected[k] for k in ('platform', 'session_id', 'agent_id', 'task_id', 'runtime_task_id', 'tool', 'params', 'retry_tool_call_id', 'action_id', 'decision_receipt_id')}
    reservation_id = result['requests']['reserve']['body']['reservation_receipt_id']
    query.update(schema_version='hold-execution-status-request/v1', reservation_receipt_id=reservation_id)
    if result['status']['request'] != query or result['status']['body']['reservation_receipt_id'] != reservation_id:
        raise ValueError('status examines another reservation')
    if 'fresh_decision' in result['requests']:
        fresh = result['requests']['fresh_decision']
        if fresh['request'] != {**original, 'tool_call_id': 'fresh-after-restart'} or receipts[fresh['body']['receipt_id']][0]['reason_code'] != fresh['body']['reason_code']:
            raise ValueError('uncertain guard lacks bound signed decision')
    events = result['events']
    if [e['sequence'] for e in events] != list(range(1, len(events) + 1)) or any(a['monotonic_ns'] > b['monotonic_ns'] for a, b in pairwise(events)):
        raise ValueError('invalid cross-process event order')
    names = [e['event'] for e in events]
    if names.count('kill_requested') != int(bool(unit['restart_stage'])) or names.count('new_process_ready') != int(bool(unit['restart_stage'])):
        raise ValueError('restart count differs from event trace')
    if unit['restart_stage']:
        checkpoint = result['restart_checkpoints'][0]
        old_resource = json.loads((directory / 'resource-retired-1.json').read_text())
        new_resource = json.loads((directory / 'resource.json').read_text())
        if checkpoint['old_process'] != old_resource['daemon'] or checkpoint['new_process'] != new_resource['daemon'] or old_resource['owner'] != new_resource['owner']:
            raise ValueError('restart process identity differs from owned resource registry')
        stage = unit['restart_stage']
        left = {'before-reserve': 'approved', 'after-reserve': 'reserve_returned', 'after-dispatch': 'file_dispatched', 'after-observe': 'observe_returned'}[stage]
        right = {'before-reserve': 'reserve_returned', 'after-reserve': 'status_returned', 'after-dispatch': 'status_returned', 'after-observe': 'status_returned'}[stage]
        if not names.index(left) < names.index('kill_requested') < names.index('old_process_reaped') < names.index('new_process_ready') < names.index(right):
            raise ValueError('fault was not at the registered boundary')
        before = json.loads((directory / 'before-restart-evidence.json').read_text())
        after = json.loads((directory / 'after-restart-evidence.json').read_text())
        signatures.verify_receipt_bundles([before])
        signatures.verify_receipt_bundles([after])
        for record in before['receipts']:
            if record not in after['receipts'] or record not in [r for r, _ in receipts.values()]:
                raise ValueError('restart lost or rewrote historical signed receipt')
    observed = [r for r, _ in receipts.values() if r['record_type'] == 'observation' and r['action_id'] == decision['action_id']]
    if unit.get('observe_response_loss'):
        backend = result['observe_fault']['backend']
        if backend['request'] != result['observe_client']['request'] or backend['request'] != {**original, 'tool_call_id': 'retry-once', 'action_id': decision['action_id'], 'decision_receipt_id': result['requests']['reserve']['body']['reservation_receipt_id'], 'result': json.dumps({'success': True})}:
            raise ValueError('lost observation request differs')
        if any(receipts[backend['body']['receipt_id']][0].get(k) != v for k, v in backend['body'].items()) or receipts[backend['body']['receipt_id']][0]['record_type'] != 'observation':
            raise ValueError('lost reply is not the signed persisted observation')
    for observed_result in result['tool_observations']:
        if any(receipts[observed_result['receipt_id']][0].get(k) != v for k, v in observed_result.items()) or receipts[observed_result['receipt_id']][0]['record_type'] != 'observation':
            raise ValueError('client observation differs from signed record')
    if any(r['decision_receipt_id'] != reservation_id or r['tool_call_id'] != 'retry-once' for r in observed):
        raise ValueError('observation does not complete registered reservation')
    if len(observed) != len(result['tool_observations']) + int(bool(unit.get('observe_response_loss'))):
        raise ValueError('observation count differs from signed records')
    oracle = result['observation']
    if [e['event_id'] for e in oracle['events']] != list(range(1, len(oracle['events']) + 1)) or any(e['nonce'] != oracle['nonce'] or e['case_id'] != unit['unit_id'] for e in oracle['events']):
        raise ValueError('counter event binding differs')
    if [r['dispatch_seq'] for r in result['executions']] != list(range(1, len(result['executions']) + 1)):
        raise ValueError('dispatch sequence differs')
    return list(predicates(unit, result).values())


def register(root, candidate, version=1):
    from common import sha256
    from hold_concurrency_registration import register as register_counter
    registration = register_counter(root, candidate, version=3)
    binding = registration['contract_binding']
    for name in ('apps/agentshield/internal/receipt/action_state.go', 'apps/agentshield/internal/receipt/hold_execution_test.go'):
        binding['contract_path_and_digest'][name] = sha256(candidate / name)
    binding.update(applicability_and_candidate_profile=SAMPLE_SCOPE,
                   exact_decision_and_reason_where_applicable={'initial': 'hold/runtime_denied with valid Intent', 'reserve': '201/hold_execution_reserved', 'replay': '409/hold_execution_already_reserved', 'new_call_while_uncertain': 'deny/hold_execution_uncertain'},
                   exact_completion_and_reason_where_applicable={'observed': 'completed/hold_execution_completed', 'no_observe': 'uncertain/hold_execution_uncertain', 'task_EVC': 'not evaluated'},
                   harm_predicate='multiple real file/receiver events or wrong content; any file after reserve-only crash is forbidden',
                   utility_predicate='exactly one physical file effect with expected digest, even if observe lost; zero-effect crash has utility false',
                   observation_scope_and_window='receiver remains live from prior to first reservation through SIGKILL/restart/status/replay; file snapshots before/after; not same-UID resistant',
                   revocation_boundary_where_applicable='no observer or authority revocation in this cohort; that AU05 variant remains pending',
                   independent_unit='five scoped variants, ten paired units; not ten independent attack families')
    if version == 2:
        binding.update(independent_unit='six scoped variants, twelve paired units; not independent attack families',
                       observation_loss='owned proxy forwards observe, waits for backend 200, closes client socket without replying; SIGKILL/restart then status must be completed and replay 409')
    return registration


def lose_observe_reply(endpoint, request, token):
    fault = {}

    class DropReply(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            fault['backend'] = http(endpoint, '/v1/observe', body, token)
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            fault['closed_without_reply'] = True

    server = HTTPServer(('127.0.0.1', 0), DropReply)
    server.timeout = 20
    thread = threading.Thread(target=server.handle_request, daemon=True)
    thread.start()
    try:
        client = http(f'http://127.0.0.1:{server.server_port}', '/v1/observe', request, token)
        thread.join(timeout=20)
        if thread.is_alive():
            raise RuntimeError('owned reply-loss proxy did not stop')
        return client, fault
    finally:
        server.server_close()
