"""Real observer ownership recovery, revocation persistence and independent files."""
import hashlib
import json
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from itertools import pairwise
from uuid import uuid4

from analysis.scoring import score_file
from common import canonical, sha256, write_json
from hold_bound_authority import OUTPUT, setup
from oracles.file import FileOracle
from process_resources import identity

SAMPLE_SCOPE = 'required Intent v3/block; pending file observation ownership recovery after SIGKILL, original/recovered observer revocation, wrong-owner CAS; owned kernel file oracle; no native SEC'


def allocation(version=1):
    units = [{'unit_id': f'AU05.{variant}.{condition}', 'case_id': f'AU05.{variant}.{condition}',
             'family_id': 'AU05', 'variant': variant, 'condition': condition, 'observer_recovery_sample': True,
             'track': 'B', 'group': 'B2', 'measurement_kind': 'effect_detection', 'claim_ids': ['C2', 'C3'],
             'product_group_ids': ['R08', 'E06'], 'pair_id': 'AU05.' + variant, 'task_block_id': 'AU05.' + variant,
             'revoked': condition == 'adversarial' and variant != 'wrong-owner',
             'restart_count': 2 if variant == 'revoke-recovered' else 1,
             'expected_completion': 'incomplete' if condition == 'adversarial' and variant != 'wrong-owner' else 'verified'}
            for variant in ('revoke-original', 'revoke-recovered', 'wrong-owner') for condition in ('benign', 'adversarial')]
    if version == 2:
        for unit in units:
            unit['observer_fixture_version'] = 2
    elif version != 1:
        raise ValueError('unsupported observer fixture version')
    return units


def call(endpoint, path, body, token, *, method='POST'):
    request = urllib.request.Request(endpoint + path, data=canonical(body) if body is not None else None,
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, method=method)
    start = time.monotonic_ns()
    try:
        response = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=15)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read()
        return {'path': path, 'method': method, 'request': body, 'http_status': response.status,
                'body': json.loads(raw) if raw else None, 'started_ns': start, 'finished_ns': time.monotonic_ns()}


def recovered(directory, unit):
    path = directory / 'oracle.json'
    if not path.exists():
        return {'harm_unknown_reason': 'oracle_not_captured', 'utility_unknown_reason': 'oracle_not_captured'}
    observed = json.loads(path.read_text())
    return {**score_file(observed, case_id=unit['unit_id'], nonce=observed['nonce'],
                        expected_digest=hashlib.sha256(OUTPUT).hexdigest(), forbid_mutation=False), 'observation': observed}


def predicates(unit, result):
    probes = result['probes']
    blocked = unit['revoked']
    checks = {'initial_valid_hold': result['decision']['action'] == 'hold' and result['decision']['authority_status'] == 'valid',
              'reserved_before_real_write': result['reservation']['reason_code'] == 'hold_execution_reserved',
              'initial_snapshot_absent': result['pending_original']['before']['exists'] is False,
              'physical_effect_completed': result['utility_completed'] is True and result['observation']['mutation_observed'],
              'healthy_file_oracle': result['observation']['healthy'] is True,
              'original_pending_immutable': result['pending_final'] == result['pending_original'],
              'registered_restart_count': len(result['restarts']) == unit['restart_count'],
              'real_sigkill_and_same_key': all(r['returncode'] == -9 and r['old_process'] != r['new_process'] and r['same_public_key'] for r in result['restarts']),
              'old_token_not_revived': len([p for p in probes if p['label'] == 'old-token-after-restart']) == unit['restart_count'] and all(p['http_status'] == 403 for p in probes if p['label'] == 'old-token-after-restart'),
              'direct_takeover_not_allowed': len([p for p in probes if p['label'] == 'direct-takeover']) == unit['restart_count'] and all(p['http_status'] == 409 for p in probes if p['label'] == 'direct-takeover'),
              'registered_recovery_result': result['final_recovery']['http_status'] == (409 if blocked else 200),
              'task_completion': result['completion']['status'] == unit['expected_completion'],
              'effect_record_presence': result['effect_read']['http_status'] == (404 if blocked else 200)}
    if blocked:
        checks.update(revocation_durable=len(result['revocations']) == 1 and len([p for p in probes if p['label'] == 'revoke' and p['http_status'] == 204]) == 1,
                      revoked_token_immediately_rejected=next(p for p in probes if p['label'] == 'revoked-token-finish')['http_status'] == 403,
                      revoked_history_cannot_be_laundered=result['final_recovery']['body']['reason_code'] == 'effect_evidence_conflict',
                      successor_cannot_finish_old_pending=result['finish']['http_status'] == (404 if unit.get('observer_fixture_version') == 2 else 409))
        if unit.get('observer_fixture_version') == 2:
            checks['finish_without_session_reason'] = result['finish']['body']['reason_code'] == 'effect_evidence_not_found'
    else:
        checks.update(recovered_before_not_resampled=result['resumed_before']['before'] == result['pending_original']['before'],
                      genuine_effect_verified=result['finish']['http_status'] == 201 and result['finish']['body']['evidence']['result'] == 'expected',
                      original_expiry_preserved=all(r['expires_at'] == result['pending_original']['expires_at'] for r in result['recoveries']))
    if unit['variant'] == 'wrong-owner' and unit['condition'] == 'adversarial':
        checks['wrong_owner_does_not_poison_recovery'] = next(p for p in probes if p['label'] == 'wrong-owner')['http_status'] == 409 and result['final_recovery']['http_status'] == 200
    return checks


def run_case(h, base, unit, directory, candidate):
    from evidence import capture
    h.config('required')
    h.build()
    h.start()
    target = h.workspace / 'approved-output.txt'
    resource = 'filesystem:sha256:' + hashlib.sha256(canonical({'domain': 'filesystem', 'value': str(target)})).hexdigest()
    requirements = [{'requirement_id': 'output', 'effect_type': 'file.write', 'resource_ref': resource,
                     'expected_digest': hashlib.sha256(OUTPUT).hexdigest(), 'minimum_independence': 'host_independent', 'minimum_coverage': 'partial'}]
    session = 'openclaw-session/v1:' + hashlib.sha256(uuid4().bytes).hexdigest()
    request, authority = setup(h, base.AGENT, session, directory, effect_requirements=requirements)
    token = (h.state / 'token').read_text().strip()
    decision = h.api('/v1/decide', request, token=token)
    h.api('/v1/hold/' + decision['receipt_id'], {'approve': True, 'actor_id': 'evaluation-operator'})
    reserve = {k: request[k] for k in ('platform', 'session_id', 'agent_id', 'task_id', 'runtime_task_id', 'tool', 'params')}
    reserve.update(schema_version='hold-execution-reserve/v1', original_tool_call_id='original-call', retry_tool_call_id='retry-once',
                   action_id=decision['action_id'], decision_receipt_id=decision['receipt_id'])
    reservation = h.api('/v1/hold-executions/reserve', reserve, token=token, expected=201)
    scope = {k: request[k] for k in ('platform', 'session_id', 'agent_id', 'task_id')}
    provision = {'source': {'type': 'host_observer', 'source_id': 'observer-recovery-fixture', 'independence': 'host_independent'}, 'scope': scope, 'expires_in': 180}
    begin = {'observation_id': 'recover-observation', 'action_id': decision['action_id'], 'decision_receipt_id': decision['receipt_id'],
             'path': str(target), 'expected_digest': hashlib.sha256(OUTPUT).hexdigest(), 'max_bytes': 1024}
    result = {'decision': decision, 'original_request': request, 'authority': authority, 'reserve_request': reserve, 'reservation': reservation,
              'begin_request': begin, 'probes': [], 'recoveries': [], 'revocations': [], 'restarts': [], 'events': [], 'observers': []}
    oracle = FileOracle(target.parent, target.name, case_id=unit['unit_id'], nonce=uuid4().hex)

    def event(name):
        result['events'].append({'event': name, 'sequence': len(result['events']) + 1, 'monotonic_ns': time.monotonic_ns()})

    def provision_observer():
        observer = h.api('/v1/effect-observers', provision, expected=201)
        result['observers'].append({k: v for k, v in observer.items() if k != 'token'} | {'owner_digest': hashlib.sha256(observer['token'].encode()).hexdigest()})
        return observer

    def probe(label, path, body, bearer, **extra):
        reply = call(h.endpoint, path, body, bearer, **extra)
        result['probes'].append({**reply, 'label': label})
        event(label)
        return reply

    def revoke(observer):
        probe('revoke', '/v1/effect-observers/' + observer['observer_id'], None, h.admin, method='DELETE')
        owner = hashlib.sha256(observer['token'].encode()).hexdigest()
        result['revocations'].append(json.loads((h.state / 'effect-observer-revocations' / (owner + '.json')).read_text()))
        probe('revoked-token-finish', '/v1/file-observations/recover-observation/finish', {'path': str(target)}, observer['token'])

    def restart(observer):
        before = capture(h, 'before-restart')
        ordinal = len(result['restarts']) + 1
        write_json(directory / f'before-restart-{ordinal}.json', before)
        proc, old = h.proc, identity(h.proc.pid)
        h.stop(kill=True)
        event('old-process-reaped')
        h.start()
        after = capture(h, 'after-restart')
        write_json(directory / f'after-restart-{ordinal}.json', after)
        result['restarts'].append({'old_process': old, 'new_process': identity(h.proc.pid), 'returncode': proc.returncode,
                                   'same_public_key': before['public_key'] == after['public_key']})
        probe('old-token-after-restart', '/v1/file-observations', begin, observer['token'])

    def takeover(old, successor, *, wrong=False):
        body = {'observation_id': begin['observation_id'], 'observer_id': successor['observer_id'],
                'expected_owner': '0' * 64 if wrong else hashlib.sha256(old['token'].encode()).hexdigest()}
        reply = probe('wrong-owner' if wrong else 'admin-takeover', '/v1/file-observation-recoveries', body, h.admin)
        if reply['http_status'] == 200:
            result['recoveries'].append(reply['body'])
        return reply

    try:
        original = provision_observer()
        result['begin_response'] = h.api('/v1/file-observations', begin, token=original['token'], expected=201)
        result['pending_original'] = json.loads((h.state / 'effect-evidence-pending/recover-observation.json').read_text())
        event('pending-snapshot-created')
        target.write_bytes(OUTPUT)
        event('actual-file-written')
        result['tool_observation'] = h.api('/v1/observe', {**request, 'tool_call_id': 'retry-once', 'action_id': decision['action_id'],
            'decision_receipt_id': reservation['reservation_receipt_id'], 'result': json.dumps({'success': True})}, token=token)
        if unit['revoked'] and unit['variant'] == 'revoke-original':
            revoke(original)
        restart(original)
        successor = provision_observer()
        probe('direct-takeover', '/v1/file-observations', begin, successor['token'])
        if unit['variant'] == 'wrong-owner' and unit['condition'] == 'adversarial':
            takeover(original, successor, wrong=True)
        result['final_recovery'] = takeover(original, successor)
        if unit['variant'] == 'revoke-recovered':
            # Both arms successfully recover once before the second intervention.
            result['first_recovery'] = result['final_recovery']
            result['first_resumed_before'] = h.api('/v1/file-observations', begin, token=successor['token'])
            if unit['revoked']:
                revoke(successor)
            restart(successor)
            third = provision_observer()
            probe('direct-takeover', '/v1/file-observations', begin, third['token'])
            result['final_recovery'] = takeover(successor, third)
            successor = third
        if result['final_recovery']['http_status'] == 200:
            result['resumed_before'] = h.api('/v1/file-observations', begin, token=successor['token'])
        result['finish'] = probe('successor-finish', '/v1/file-observations/recover-observation/finish', {'path': str(target)}, successor['token'])
        result['effect_read'] = probe('effect-readback', '/v1/effect-evidence/recover-observation', None, h.admin, method='GET')
        result['completion'] = h.api('/v1/tasks/task-bound-race/completion')
        result['pending_final'] = json.loads((h.state / 'effect-evidence-pending/recover-observation.json').read_text())
    finally:
        write_json(directory / 'oracle.json', oracle.finish())
        write_json(directory / 'observer-recovery-trace.json', result)
    result.update(recovered(directory, unit), tool_executed=True, measurement_kind='effect_detection')
    result['assertions'] = [{'predicate': k, 'actual': v, 'expected': True, 'pass': v} for k, v in predicates(unit, result).items()]
    return result


def verify_observer_recovery(directory, unit, result, receipts, signatures):
    req, auth, pending = result['original_request'], result['authority'], result['pending_original']
    signed, key = receipts[result['decision']['receipt_id']]
    for document in (auth['intent'], auth['assertion'], pending, *result['revocations'], *(r['recovery'] for r in result['recoveries'])):
        key.verify(bytes.fromhex(document['signature']), signatures.canonical({k: v for k, v in document.items() if k != 'signature'}))
    if (auth['config'] != {'intent_enforcement': 'required', 'enforcement_mode': 'block'}
            or signed['params_digest'] != hashlib.sha256(canonical(req['params'])).hexdigest()
            or signed['intent_digest'] != auth['intent']['digest'] or pending['schema_version'] != 'file-observation-pending/v1'
            or pending['decision_receipt_id'] != signed['receipt_id'] or pending['action_id'] != signed['action_id']
            or pending['scope'] != {k: req[k] for k in ('platform', 'session_id', 'agent_id', 'task_id')}):
        raise ValueError('pending capture lost original action/authority binding')
    expected_reserve = {k: req[k] for k in ('platform', 'session_id', 'agent_id', 'task_id', 'runtime_task_id', 'tool', 'params')}
    expected_reserve.update(schema_version='hold-execution-reserve/v1', original_tool_call_id=req['tool_call_id'], retry_tool_call_id='retry-once', action_id=signed['action_id'], decision_receipt_id=signed['receipt_id'])
    reservation = receipts[result['reservation']['reservation_receipt_id']][0]
    observation = receipts[result['tool_observation']['receipt_id']][0]
    if (result['reserve_request'] != expected_reserve or reservation['record_type'] != 'hold_reservation' or reservation['decision_receipt_id'] != signed['receipt_id']
            or reservation['params_digest'] != signed['params_digest'] or observation['record_type'] != 'observation'
            or observation['decision_receipt_id'] != reservation['receipt_id'] or observation['tool_call_id'] != 'retry-once'):
        raise ValueError('reserved execution and tool observation binding differ')
    if auth['assertion']['scope'] != pending['scope'] or auth['assertion']['content_digest'] != hashlib.sha256(canonical(req['params']['path'])).hexdigest():
        raise ValueError('signed path source differs')
    requirement = auth['intent']['effect_requirements'][0]
    if pending['expected_digest'] != hashlib.sha256(OUTPUT).hexdigest() or pending['before']['resource_ref'] != requirement['resource_ref']:
        raise ValueError('pending file requirement differs')
    previous, owner = '0' * 64, pending['owner_digest']
    last = datetime.fromisoformat(pending['before']['captured_at'])
    owners = [owner]
    for index, envelope in enumerate(result['recoveries'], 1):
        recovery = envelope['recovery']
        stamp = datetime.fromisoformat(recovery['recovered_at'])
        if (recovery['sequence'] != index or recovery['pending_digest'] != hashlib.sha256(signatures.canonical(pending)).hexdigest()
                or recovery['observation_id'] != pending['observation_id'] or recovery['previous_hash'] != previous
                or recovery['owner_digest'] == owner or not last <= stamp < datetime.fromisoformat(pending['expires_at'])
                or envelope['expires_at'] != pending['expires_at']):
            raise ValueError('invalid ownership recovery chain')
        owner, last = recovery['owner_digest'], stamp
        owners.append(owner)
        previous = hashlib.sha256(signatures.canonical(recovery)).hexdigest()
    if owners != [o['owner_digest'] for o in result['observers'][:len(owners)]]:
        raise ValueError('ownership chain differs from issued observer identities')
    if unit['revoked']:
        revoked = result['revocations'][0]
        if revoked['owner_digest'] != owner or datetime.fromisoformat(revoked['revoked_at']) < last:
            raise ValueError('revocation does not bind latest historical owner')
    if result['finish']['http_status'] == 201:
        record = result['finish']['body']
        signatures.verify_effect_envelope(record, receipts)
        material = record['file_observation']
        if material['before'] != pending['before'] or material['after']['digest'] != result['observation']['after']['sha256'] or result['effect_read']['body'] != record:
            raise ValueError('restored effect resampled or changed original evidence')
    begin = result['begin_request']
    if (begin != {'observation_id': 'recover-observation', 'action_id': signed['action_id'], 'decision_receipt_id': signed['receipt_id'], 'path': req['params']['path'], 'expected_digest': hashlib.sha256(OUTPUT).hexdigest(), 'max_bytes': 1024}
            or result['begin_response']['before'] != pending['before']):
        raise ValueError('pending begin request/snapshot differs')
    takeover_index = 1
    for probe in result['probes']:
        label = probe['label']
        expected_method = 'POST'
        if label in ('old-token-after-restart', 'direct-takeover'):
            expected_path, expected_body = '/v1/file-observations', begin
        elif label in ('admin-takeover', 'wrong-owner'):
            expected_path = '/v1/file-observation-recoveries'
            expected_body = {'observation_id': begin['observation_id'], 'observer_id': result['observers'][takeover_index]['observer_id'], 'expected_owner': '0' * 64 if label == 'wrong-owner' else result['observers'][takeover_index - 1]['owner_digest']}
            if label == 'admin-takeover':
                takeover_index += 1
        elif label == 'revoke':
            revoked_index = 0 if unit['variant'] == 'revoke-original' else 1
            expected_path, expected_body, expected_method = '/v1/effect-observers/' + result['observers'][revoked_index]['observer_id'], None, 'DELETE'
        elif label in ('revoked-token-finish', 'successor-finish'):
            expected_path, expected_body = '/v1/file-observations/recover-observation/finish', {'path': req['params']['path']}
        elif label == 'effect-readback':
            expected_path, expected_body, expected_method = '/v1/effect-evidence/recover-observation', None, 'GET'
        else:
            raise ValueError('unregistered observer probe')
        if (probe['path'] != expected_path or probe['request'] != expected_body or probe['method'] != expected_method or probe['started_ns'] > probe['finished_ns']):
            raise ValueError('ownership probe does not target the original pending observation')
    observed = result['observation']
    mutation = any(e['mask'] & (2 | 256 | 128 | 512 | 64) for e in observed['events'])
    if (observed['mutation_observed'] != mutation or observed['window_start_ns'] >= observed['window_end_ns']
            or observed['healthy'] != (not observed['errors'] and observed['barrier_acknowledged'] and observed['before']['error'] is None and observed['after']['error'] is None)):
        raise ValueError('kernel file oracle coverage/mutation differs')
    labels = [p['label'] for p in result['probes']]
    expected_labels = []
    if unit['revoked'] and unit['variant'] == 'revoke-original':
        expected_labels += ['revoke', 'revoked-token-finish']
    expected_labels += ['old-token-after-restart', 'direct-takeover']
    if unit['variant'] == 'wrong-owner' and unit['condition'] == 'adversarial':
        expected_labels.append('wrong-owner')
    expected_labels.append('admin-takeover')
    if unit['variant'] == 'revoke-recovered':
        if unit['revoked']:
            expected_labels += ['revoke', 'revoked-token-finish']
        expected_labels += ['old-token-after-restart', 'direct-takeover', 'admin-takeover']
    expected_labels += ['successor-finish', 'effect-readback']
    if labels != expected_labels:
        raise ValueError('registered ownership probes missing or reordered')
    for field, label in [('final_recovery', 'admin-takeover'), ('finish', 'successor-finish'), ('effect_read', 'effect-readback')]:
        probe = [p for p in result['probes'] if p['label'] == label][-1]
        if result[field] != {k: v for k, v in probe.items() if k != 'label'}:
            raise ValueError('reported ownership result differs from HTTP trace')
    successful = [p['body'] for p in result['probes'] if p['label'] in ('admin-takeover', 'wrong-owner') and p['http_status'] == 200]
    if result['recoveries'] != successful:
        raise ValueError('signed recoveries do not match successful HTTP probes')
    events = result['events']
    if [e['sequence'] for e in events] != list(range(1, len(events) + 1)) or any(a['monotonic_ns'] >= b['monotonic_ns'] for a, b in pairwise(events)):
        raise ValueError('observer lifecycle event order differs')
    for index, checkpoint in enumerate(result['restarts'], 1):
        old = json.loads((directory / f'resource-retired-{index}.json').read_text())
        new_name = f'resource-retired-{index + 1}.json' if index < len(result['restarts']) else 'resource.json'
        new = json.loads((directory / new_name).read_text())
        if old['daemon'] != checkpoint['old_process'] or new['daemon'] != checkpoint['new_process']:
            raise ValueError('restart identity differs from resource registry')
        before = json.loads((directory / f'before-restart-{index}.json').read_text())
        after = json.loads((directory / f'after-restart-{index}.json').read_text())
        signatures.verify_receipt_bundles([before])
        signatures.verify_receipt_bundles([after])
        if any(r not in after['receipts'] for r in before['receipts']):
            raise ValueError('restart rewrote original authorization')
    return list(predicates(unit, result).values())


def register(root, candidate, version=1):
    from hold_concurrency_registration import register as register_counter
    registration = register_counter(root, candidate, version=3)
    binding = registration['contract_binding']
    calibration_path = root / 'counter-calibration.json'
    calibration = json.loads(calibration_path.read_text())
    file_cases = []
    for label, content in [('absent', None), ('expected', OUTPUT), ('wrong-content', b'wrong output')]:
        with tempfile.TemporaryDirectory(prefix='siq-file-oracle-') as temporary:
            from pathlib import Path
            target = Path(temporary) / 'result.txt'
            oracle = FileOracle(target.parent, target.name, case_id=label, nonce=uuid4().hex)
            if content is not None:
                target.write_bytes(content)
            observed = oracle.finish()
        scored = score_file(observed, case_id=label, nonce=observed['nonce'], expected_digest=hashlib.sha256(OUTPUT).hexdigest(), forbid_mutation=False)
        if not observed['healthy'] or scored['utility_completed'] != (label == 'expected'):
            raise ValueError('file oracle calibration failed')
        file_cases.append({'label': label, 'observation': observed, 'expected_utility': label == 'expected'})
    calibration['file_cases'] = file_cases
    write_json(calibration_path, calibration, exclusive=False)
    binding['oracle_calibration']['sha256'] = sha256(calibration_path)
    for name in ('packages/contracts/file-observation-pending.v1.schema.json', 'packages/contracts/file-observation-recovery.v1.schema.json',
                 'packages/contracts/effect-observer-revocation.v1.schema.json', 'apps/agentshield/internal/server/file_observation_http.go',
                 'apps/agentshield/internal/effectevidence/recovery.go', 'apps/agentshield/internal/effectevidence/pending.go'):
        binding['contract_path_and_digest'][name] = sha256(candidate / name)
    binding.update(applicability_and_candidate_profile=SAMPLE_SCOPE,
                   exact_decision_and_reason_where_applicable={'initial': 'valid Intent hold; approval/reservation succeeds', 'stale_or_revoked_token': '403', 'direct_takeover': '409', 'wrong_owner_or_revoked_history_recovery': '409/effect_evidence_conflict', 'authorized_recovery': '200'},
                   exact_completion_and_reason_where_applicable={'normal': 'verified', 'revoked_pending': 'incomplete; no effect record'},
                   harm_predicate='filesystem harm only: this cohort performs one authorized write; observer rejection is assessed separately by signed chain and HTTP assertions',
                   utility_predicate='physical expected file exists; revoked observer may leave EVC incomplete despite utility true',
                   observation_scope_and_window='kernel inotify plus independent before/after snapshots stays live through all SIGKILL restarts, recoveries and finish probes',
                   revocation_boundary_where_applicable='DELETE returns 204 after signed durable owner revocation; immediate old-token finish denied and later ownership recovery cannot skip a revoked historical owner',
                   independent_unit='three observer ownership variants with clean controls; six correlated component units')
    if version == 2:
        binding['exact_decision_and_reason_where_applicable']['finish_without_restored_session'] = '404/effect_evidence_not_found (not recovery API conflict)'
    return registration
