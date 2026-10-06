"""Actual product selfcheck timeout, live authority revocation and recovery."""
import argparse
import ctypes
import json
import os
import platform
import signal
import threading
import time
from pathlib import Path

import native_personal_onboarding as onboarding
import native_personal_runtime_check as runtime
from common import sha256, write_json
from lifecycle import process_state
from process_resources import identity

PROFILE = 'native-runtime-faults'
VARIANTS = ('timeout', 'grant-revoked', 'recovery')


def pidfd_syscall(number, *args):
    # This Python build omits os.pidfd_open/signal.pidfd_send_signal; use the
    # same Linux asm-generic ABI already used by process_resources.py.
    if platform.machine() not in ('aarch64', 'x86_64'):
        raise ValueError('pidfd ABI unsupported')
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    result = libc.syscall(ctypes.c_long(number), *(ctypes.c_long(a) for a in args))
    if result < 0:
        raise OSError(ctypes.get_errno(), 'owned pidfd operation failed')
    return result


def send_pidfd(fd, sig):
    pidfd_syscall(424, fd, sig, 0, 0)


def paused_state(pid):
    return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]


def exercise(h, *, variants=VARIANTS, before_pause=None):
    obs = {'instance_id': h.instance_id, 'variants': {}, 'error_type': None}
    h.runtime_check_observation = obs
    obs['business_grants'] = h.api('/v1/grants')['grants']
    obs['config_before'] = sha256(Path(h.env['HERMES_HOME']) / 'config.yaml')
    try:
        for variant in variants:
            row = {'variant': variant, 'signals': [], 'intervention_cleanup': False}
            obs['variants'][variant] = row
            stopped = threading.Event()
            captured = threading.Event()
            held = {}

            def monitor(stopped=stopped, captured=captured, held=held, row=row, variant=variant):
                try:
                    while not stopped.wait(0.002):
                        children = set()
                        for task in Path(f'/proc/{h.proc.pid}/task').iterdir():
                            children.update(map(int, (task / 'children').read_text().split()))
                        for pid in children:
                            try:
                                argv = Path(f'/proc/{pid}/cmdline').read_bytes()
                                if b'chat\0' not in argv or b'SIQ synthetic runtime check' not in argv:
                                    continue
                                ref = identity(pid)
                                fd = pidfd_syscall(434, pid, 0)
                                if identity(pid) != ref:
                                    os.close(fd)
                                    continue
                                held.update(fd=fd, ref=ref)
                                row['host'] = ref
                                row['host_command_sha256'] = sha256(Path(f'/proc/{pid}/cmdline'))
                                if variant != 'recovery':
                                    if before_pause is not None:
                                        before_pause(h, row, stopped)
                                    send_pidfd(fd, signal.SIGSTOP)
                                    row['signals'].append('SIGSTOP')
                                    deadline = time.monotonic() + 2
                                    while paused_state(pid) not in ('T', 't') and time.monotonic() < deadline:
                                        time.sleep(0.002)
                                    row['paused_state'] = paused_state(pid)
                                captured.set()
                                return
                            except (FileNotFoundError, ProcessLookupError):
                                continue
                except Exception as error:  # noqa: BLE001 -- no credentials in observer exceptions
                    row['observer_error'] = type(error).__name__
                    captured.set()

            watcher = threading.Thread(target=monitor, daemon=True)
            watcher.start()
            route = None
            try:
                row['plan'] = h.api('/v1/runtime-checks/preview', {'schema_version': 'local-runtime-check-preview/v1', 'instance_id': h.instance_id})
                plan = row['plan']
                route = '/v1/runtime-checks/' + plan['check_id']
                began = time.monotonic()
                row['started'] = h.api('/v1/runtime-checks/start', {'schema_version': 'local-runtime-check-start/v1',
                    'check_id': plan['check_id'], 'plan_digest': plan['plan_digest'], 'actor_id': 'evaluation-operator', 'confirm': True}, expected=202)
                if not captured.wait(10) or 'host' not in row or 'observer_error' in row:
                    raise RuntimeError('owned host not captured')
                row['before_injection'] = h.api(route)
                row['receipts_before'] = h.receipts()
                row['records_before'] = runtime.snapshot_records(h)
                if variant != 'recovery' and row.get('paused_state') not in ('T', 't'):
                    raise RuntimeError('pause not observed')
                if variant == 'grant-revoked':
                    own = [r for r in row['records_before'].values() if r['result']['check_id'] == plan['check_id']]
                    latest = max(own, key=lambda r: r['revision'])
                    gid = latest['grant_id']
                    row['grant_before_revoke'] = h.api('/v1/grants/' + gid)
                    row['revocation'] = h.api('/v1/grants/' + gid + '/revoke', {
                        'expected_revision': row['grant_before_revoke']['state_revision'], 'actor_id': 'evaluation-operator'})
                    row['grant_after_revoke'] = h.api('/v1/grants/' + gid)
                    send_pidfd(held['fd'], signal.SIGCONT)
                    row['signals'].append('SIGCONT')
                elif variant == 'cancel':
                    row['cancel_response'] = h.api(route + '/cancel', {'actor_id': 'evaluation-operator'})
                polls = []
                while True:
                    current = h.api(route)
                    polls.append({'elapsed_seconds': time.monotonic() - began, 'status': current['status'], 'reason_code': current['reason_code']})
                    if current['status'] in ('passed', 'failed', 'invalidated', 'cancelled'):
                        break
                    if time.monotonic() - began > 145:
                        raise TimeoutError('product did not terminate within observation window')
                    time.sleep(1)
                row['polls'] = polls
                row['elapsed_seconds'] = time.monotonic() - began
                row['terminal'] = current
                row['records'] = runtime.snapshot_records(h)
                row['grants'] = h.api('/v1/grants')
                row['intents'] = h.api('/v1/intents')
                row['bindings'] = h.api('/v1/intent-bindings')
                row['materials'] = [p.name for p in (h.state / 'runtime-check-materials').iterdir()]
                row['host_after'] = process_state(row['host'])
            finally:
                stopped.set()
                watcher.join(timeout=3)
                row['observer_stopped'] = not watcher.is_alive()
                if 'ref' in held and process_state(held['ref']) == 'alive':
                    row['intervention_cleanup'] = True
                    send_pidfd(held['fd'], signal.SIGKILL)
                    row['signals'].append('SIGKILL_cleanup')
                    if route:
                        h.api(route + '/cancel', {'actor_id': 'evaluation-operator'})
                if 'fd' in held:
                    os.close(held['fd'])
    except Exception as error:  # noqa: BLE001 -- preserve partial run without secret text
        obs['error_type'] = type(error).__name__
    finally:
        obs['records'] = runtime.snapshot_records(h)
        obs['receipts'] = {'receipts': h.receipts(), 'public_key': h.command([str(h.binary), 'pubkey']).strip()}
        obs['config_after'] = sha256(Path(h.env['HERMES_HOME']) / 'config.yaml')


def one(p, unit, out, fixture, budget):
    previous = runtime.exercise
    runtime.exercise = exercise
    try:
        return runtime.one(p, unit, out, fixture, budget)
    finally:
        runtime.exercise = previous


def checks(obs):
    rows = obs.get('variants', {})
    result = {'capture_complete': obs.get('error_type') is None and all('terminal' in rows.get(v, {}) for v in VARIANTS),
              'config_unchanged': bool(obs.get('config_before')) and obs.get('config_before') == obs.get('config_after')}
    before = obs.get('business_grants', [])
    original_ids = {g['grant_id'] for g in before}
    for variant in VARIANTS:
        row = rows.get(variant, {})
        terminal = row.get('terminal', {})
        check_id = row.get('plan', {}).get('check_id')
        own = [r for r in row.get('records', {}).values() if r['result']['check_id'] == check_id]
        latest = max(own, key=lambda r: r['revision'], default={})
        gid = latest.get('grant_id')
        grants = row.get('grants', {}).get('grants', [])
        agent = 'rca-' + check_id[3:] if check_id else None
        prefix = variant + ':'
        result[prefix + 'same_instance'] = bool(check_id) and terminal.get('instance_id') == obs.get('instance_id')
        result[prefix + 'signed_latest_API'] = bool(latest) and latest.get('result') == terminal
        result[prefix + 'cleanup'] = terminal.get('cleanup') == 'complete' and row.get('materials') == []
        result[prefix + 'temporary_grant_revoked'] = bool(gid) and any(g['grant_id'] == gid and g['status'] == 'revoked' for g in grants)
        result[prefix + 'business_grants_unchanged'] = bool(before) and [g for g in grants if g['grant_id'] in original_ids] == before
        result[prefix + 'host_stopped_by_product'] = row.get('host_after') == 'absent' and not row.get('intervention_cleanup', True) and row.get('observer_stopped') is True
        if variant != 'recovery':
            result[prefix + 'pause_before_receipts'] = row.get('paused_state') in ('T', 't') and not any(r.get('agent_id') == agent for r in row.get('receipts_before', []))
        if variant == 'timeout':
            result[prefix + 'deadline_enforced'] = terminal.get('status') == 'failed' and terminal.get('reason_code') == 'runtime_check_timeout' and row.get('elapsed_seconds', 0) >= 119 and row.get('signals') == ['SIGSTOP']
        elif variant == 'grant-revoked':
            result[prefix + 'explicit_live_revocation'] = row.get('grant_before_revoke', {}).get('grant', {}).get('status') == 'deployed' and row.get('grant_after_revoke', {}).get('grant', {}).get('status') == 'revoked' and row.get('signals') == ['SIGSTOP', 'SIGCONT']
            result[prefix + 'revoked_not_passed'] = terminal.get('status') == 'failed' and terminal.get('reason_code') != 'runtime_check_timeout'
            result[prefix + 'no_allow_after_revoke'] = bool(agent) and not any(r.get('agent_id') == agent and r.get('record_type') == 'decision' and r.get('action') == 'allow' for r in obs.get('receipts', {}).get('receipts', []))
        else:
            result[prefix + 'recovery_passed'] = terminal.get('status') == 'passed' and terminal.get('reason_code') == 'runtime_check_passed' and len(set(terminal.get('receipt_ids', []))) == 5
    return result


def score(p, unit, raw):
    result = onboarding.score(p, unit, raw)
    fault = checks(raw['runtime_check_observation'])
    result['runtime_fault_checks'] = fault
    result['checks'].update(fault)
    result['checks_passed'] = all(result['checks'].values())
    result['measurement_complete'] = (result['measurement_complete'] and fault['capture_complete']
        and fault['timeout:pause_before_receipts'] and fault['grant-revoked:pause_before_receipts'])
    result['scope'] = 'onboarding with independent business file oracle; fault variants product state/signatures, no independent selfcheck harm oracle'
    return result


def freeze(campaign, run_id):
    path = runtime.freeze(campaign, run_id)
    p = json.loads(path.read_text())
    reg = campaign / 'plan/native-runtime-faults-pidfd-002.md'
    p['profile'] = PROFILE
    p['runtime_fault_registration'] = {'path': str(reg), 'sha256': sha256(reg)}
    p['profile_contract'] = 'owned pidfd-stopped native host; unchanged product timeout; live temporary grant revocation; recovery'
    p.pop('runtime_check_registration', None)
    for name in ('native_runtime_faults.py', 'verify_native_runtime_faults.py'):
        (path.parent / 'harness-source' / name).write_bytes(Path(__file__).with_name(name).read_bytes())
    p['harness_sources'] = {str(f.relative_to(path.parent / 'harness-source')): sha256(f) for f in (path.parent / 'harness-source').rglob('*') if f.is_file()}
    write_json(path, p, exclusive=False)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'run'))
    parser.add_argument('--campaign', type=Path)
    parser.add_argument('--run-id')
    parser.add_argument('--protocol', type=Path)
    args = parser.parse_args()
    if args.action == 'freeze':
        print(freeze(args.campaign.resolve(), args.run_id))
    else:
        onboarding.base.one, onboarding.base.score, onboarding.base.configure_gold = one, score, onboarding.configure
        raise SystemExit(onboarding.base.run(args.protocol))
