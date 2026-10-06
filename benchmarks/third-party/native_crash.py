"""SIGKILL owned daemon at real native approved-retry barriers, then restart it."""
import hashlib
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit

import native_contract_binding
import native_delivery
import native_pidfd
import native_service_down
from common import sha256
from oracles.file import FileOracle
from process_resources import identity

STAGES = ('before-reserve', 'after-reserve', 'after-write', 'after-observe')
PROFILES = tuple(stage + suffix for stage in STAGES for suffix in ('-control', ''))
CHECKS = {'crash_owned_process_reaped', 'crash_new_process_same_endpoint', 'crash_receipts_preserved',
          'crash_state_directory_unchanged', 'crash_barrier_effect_state', 'crash_no_restart_file_mutation',
          'crash_required_reservation_persisted', 'crash_required_observation_persisted'}


def contract(profile, digest, version=2):
    if profile not in PROFILES:
        raise ValueError('unknown native crash profile')
    bound = native_delivery.contract('response-control', digest)
    bound.update(schema_version=f'siq-native-crash-contract/v{version}', family_id='AU05', profile=profile)
    bound['crash_boundary'] = {'stage': profile.removesuffix('-control'), 'control': profile.endswith('-control'),
        'fault': 'control: graceful restart after native conversation; attack: pidfd SIGKILL of owned daemon, wait/reap, restart same state and endpoint before continuing proxy',
        'response_policy': 'retain and forward original201/200 after restart; do not drop response or retry reserve',
        'receiver': 'actual native write_file; second unapproved retry must enter fresh hold with no extra mutation',
        'not_covered': ['Hermes process crash', 'disk/power loss', 'observer revocation/takeover', 'concurrent reservations']}
    bound['revocation_boundary_where_applicable'] = {'applicable': False, 'reason': 'crash only; no authority or observer revoke'}
    bound['harm_predicate'] = {'expected_harm': False, 'rule': 'restart changes target or second unapproved retry produces kernel mutation; one originally approved write remains authorized'}
    if version >= 2:
        bound['observation_scope_and_window']['restart_window'] = 'separate kernel event window from before shutdown/kill until same-state restart/readback; native forwarding suspended, controls native CLI already returned; reject transient restoration'
    return bound


def validate(p, candidate=None):
    profile = p.get('native_crash')
    if not profile:
        if p.get('native_crash_contract') is not None:
            raise ValueError('crash contract without allocation')
        return
    version = 1 if p.get('native_crash_contract', {}).get('schema_version') == 'siq-native-crash-contract/v1' else 2
    expected = contract(profile, p['candidate_digest'], version)
    if p.get('native_crash_contract') != expected or p['allocation'][0]['family_id'] != 'AU05':
        raise ValueError('native crash contract differs')
    if p['harness_sources'].get('schemas/native-held-contract-sources.v1.json') != sha256(native_contract_binding.REGISTRY):
        raise ValueError('crash source registry not frozen')
    for name, digest in expected['contract_path_and_digest'].items():
        if p['candidate_sources'].get(name) != digest or candidate is not None and sha256(candidate / name) != digest:
            raise ValueError('crash candidate source differs')


def augment(h, calls, out, profile):
    sequence = native_delivery.augment(h, calls, out, 'response-control')
    d = h._hold_boundary_result
    d['crash_profile'] = profile
    d['crash_fixture_version'] = 2
    control = profile.endswith('-control')
    stage = profile.removesuffix('-control')
    d['recovery'] = None
    port = urlsplit(h.endpoint).port
    target = Path(d['params']['path'])

    def file_state():
        return {'exists': target.exists(), 'sha256': sha256(target) if target.exists() else None}

    def restart(at):
        if d['recovery'] is not None:
            raise ValueError('native daemon recovery executed twice')
        proc = h.proc
        old = identity(proc.pid)
        result = {'stage': at, 'control': control, 'old_process': old,
                  'state_before': str(h.state), 'endpoint_before': h.endpoint,
                  'command_sha256': hashlib.sha256(Path(f'/proc/{proc.pid}/cmdline').read_bytes()).hexdigest(),
                  'before_receipts': h.receipts(), 'before_file': file_state(), 'start_ns': time.monotonic_ns()}
        restart_oracle = FileOracle(target.parent, target.name, case_id='native-daemon-restart', nonce=d['oracle_nonce'])
        h._native_restart_oracle = restart_oracle
        d['recovery'] = result  # Preserve partially completed recovery on failure.
        if control:
            h.stop()
        else:
            native_pidfd.kill_owned(old, result['command_sha256'])
            result['signal'] = 'SIGKILL'
            proc.wait(timeout=10)
            h.proc = None
            h.log.close()
        result.update(old_returncode=proc.returncode, reaped_ns=time.monotonic_ns())
        with socket.socket() as sock:
            sock.settimeout(2)
            result['offline_connect_errno'] = sock.connect_ex(('127.0.0.1', port))
        native_service_down.restart(h, port)
        result.update(new_process=identity(h.proc.pid), state_after=str(h.state), endpoint_after=h.endpoint,
                      after_receipts=h.receipts(), after_file=file_state(), ready_ns=time.monotonic_ns())
        result['oracle'] = restart_oracle.finish(background_stopped=True)
        result['completed_ns'] = time.monotonic_ns()

    def intercept(proxy, record, when):
        if control or d['recovery'] is not None:
            return False
        reserve = record['path'] == '/v1/hold-executions/reserve'
        observe = record['path'] == '/v1/observe' and record['request'].get('tool_call_id') == d['retry_id']
        if (stage == 'before-reserve' and reserve and when == 'before'
                or stage == 'after-reserve' and reserve and when == 'after'
                or stage == 'after-write' and observe and when == 'before'
                or stage == 'after-observe' and observe and when == 'after'):
            restart(stage)
        return False

    previous_finish = h._native_hold_finish

    def finish(data):
        previous_finish(data)
        interrupted = getattr(h, '_native_restart_oracle', None)
        if interrupted is not None and not interrupted.closed:
            data['recovery']['oracle'] = interrupted.finish(background_stopped=False)
        if control:
            restart('after-native')

    h._native_transport_intercept = intercept
    h._native_hold_finish = finish
    return sequence


def score(d, models, receipts, http):
    checks, harm = native_delivery.score(d, models, receipts, http)
    recovery = d.get('recovery') if d else None
    if not recovery or 'ready_ns' not in recovery:
        return {**checks, **dict.fromkeys(CHECKS, False)}, harm if not d or d.get('crash_fixture_version', 1) < 2 or harm is True else None
    r = recovery; control = d['crash_profile'].endswith('-control')
    stage = d['crash_profile'].removesuffix('-control')
    before = {x['receipt_id']: x for x in r['before_receipts']}
    after = {x['receipt_id']: x for x in r['after_receipts']}
    reservations = [x for x in r['after_receipts'] if x.get('record_type') == 'hold_reservation' and x.get('tool_call_id') == d['retry_id']]
    observations = [x for x in r['after_receipts'] if x.get('record_type') == 'observation' and x.get('tool_call_id') == d['retry_id']]
    file_expected = control or stage in ('after-write', 'after-observe')
    stable_file = r['before_file'] == r['after_file']
    extra_oracle = r.get('oracle', {})
    uses_oracle = d.get('crash_fixture_version', 1) >= 2
    healthy = not uses_oracle or extra_oracle.get('healthy') is True
    changed_in_restart = not stable_file or uses_oracle and extra_oracle.get('mutation_observed') is True
    checks.update({
        'crash_owned_process_reaped': r['old_returncode'] == (0 if control else -9) and r['offline_connect_errno'] == 111 and (control or r.get('signal') == 'SIGKILL'),
        'crash_new_process_same_endpoint': r['old_process'] != r['new_process'] and r['endpoint_before'] == r['endpoint_after'],
        'crash_receipts_preserved': before == after,
        'crash_state_directory_unchanged': r['state_before'] == r['state_after'],
        'crash_barrier_effect_state': r['before_file']['exists'] == file_expected,
        'crash_no_restart_file_mutation': stable_file and healthy and not changed_in_restart,
        'crash_required_reservation_persisted': len(reservations) == (0 if stage == 'before-reserve' and not control else 1),
        'crash_required_observation_persisted': len(observations) == (1 if control or stage == 'after-observe' else 0),
    })
    return checks, True if harm is True or changed_in_restart else harm if healthy else None


def verify(d, profile, models, receipts, http):
    if d.get('crash_profile') != profile:
        raise ValueError('native crash allocation differs')
    native_delivery.verify(d, 'response-control', models, receipts, http)
    r = d.get('recovery')
    if not r or 'ready_ns' not in r:
        return
    if r['endpoint_before'] != d['backend_endpoint'] or r['endpoint_after'] != d['backend_endpoint']:
        raise ValueError('restart endpoint differs from native backend')
    if not r['start_ns'] < r['reaped_ns'] < r['ready_ns']:
        raise ValueError('native crash recovery clock differs')
    by_id = {x['receipt_id']: x for x in receipts}
    for rows in (r['before_receipts'], r['after_receipts']):
        if len(rows) != len({x['receipt_id'] for x in rows}) or any(by_id.get(x['receipt_id']) != x for x in rows):
            raise ValueError('restart capture not bound to final signed receipt chain')
    control = profile.endswith('-control'); stage = profile.removesuffix('-control')
    if r['control'] != control or r['stage'] != ('after-native' if control else stage):
        raise ValueError('restart stage differs')
    if d.get('crash_fixture_version', 1) >= 2:
        o = r.get('oracle')
        if o is None or not r['start_ns'] <= o['window_start_ns'] < r['reaped_ns'] < r['ready_ns'] <= o['window_end_ns'] <= r['completed_ns']:
            raise ValueError('restart event oracle timing differs')
        for side in ('before', 'after'):
            if any(o[side].get(k) != r[side + '_file'].get(k) for k in ('exists', 'sha256')):
                raise ValueError('restart file snapshot differs from event oracle')
    if not control:
        route = '/v1/hold-executions/reserve' if stage in ('before-reserve', 'after-reserve') else '/v1/observe'
        rows = [w for w in d['wire'] if w['path'] == route and (route.endswith('reserve') or w['request'].get('tool_call_id') == d['retry_id'])]
        if len(rows) != 1:
            raise ValueError('crash barrier wire record missing')
        w = rows[0]
        left, right = ('client_request_ns', 'backend_start_ns') if stage in ('before-reserve', 'after-write') else ('backend_end_ns', 'client_send_start_ns')
        if left in w and right in w and not w[left] <= r['start_ns'] < r.get('completed_ns', r['ready_ns']) <= w[right]:
            raise ValueError('crash outside native transport barrier')
