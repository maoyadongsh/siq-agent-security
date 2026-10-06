"""Pause a real bound host after its first read observation; revoke or cancel."""
import argparse
import json
import time
from pathlib import Path

import native_personal_onboarding as onboarding
import native_personal_runtime_check as runtime
import native_runtime_faults as faults
from common import sha256, write_json

PROFILE = 'bound-runtime-faults'
VARIANTS = ('grant-revoked', 'cancel', 'recovery')


def own_receipts(receipts, cid):
    return [r for r in receipts if r.get('agent_id') == 'rca-' + cid[3:]]


def first_read_seen(receipts, cid):
    return any(r.get('tool_call_id') == 'rc-first' and r.get('record_type') == 'observation'
               for r in own_receipts(receipts, cid))


def before_pause(h, row, stopped):
    cid = row['plan']['check_id']
    deadline = time.monotonic() + 8
    while not stopped.is_set() and time.monotonic() < deadline:
        records = []
        for path in (h.state / 'receipts/local').glob('*.jsonl'):
            # Appends may end with an incomplete line; never synthesize a record.
            for line in path.read_bytes().splitlines(keepends=True):
                if line.endswith(b'\n'):
                    records.append(json.loads(line))
        if first_read_seen(records, cid):
            row['trigger_receipts'] = own_receipts(records, cid)
            return
        time.sleep(0.001)
    raise TimeoutError('first read checkpoint not observed')


def exercise(h):
    faults.exercise(h, variants=VARIANTS, before_pause=before_pause)


def one(p, unit, out, fixture, budget):
    previous = runtime.exercise
    runtime.exercise = exercise
    try:
        return runtime.one(p, unit, out, fixture, budget)
    finally:
        runtime.exercise = previous


def stage_measured(row):
    cid = row.get('plan', {}).get('check_id')
    if not cid:
        return False
    receipts = own_receipts(row.get('receipts_before', []), cid)
    decisions = [r for r in receipts if r.get('record_type') == 'decision']
    observations = [r for r in receipts if r.get('record_type') == 'observation']
    first = [r for r in decisions if r.get('tool_call_id') == 'rc-first' and r.get('action') == 'allow']
    observed = [r for r in observations if r.get('tool_call_id') == 'rc-first']
    return (row.get('paused_state') in ('T', 't') and row.get('before_injection', {}).get('status') == 'running'
            and len(first) == len(observed) == 1 and observed[0].get('decision_receipt_id') == first[0]['receipt_id']
            and observed[0].get('action_id') == first[0]['action_id']
            and not any(r.get('tool_call_id') == 'rc-last' for r in receipts))


def checks(obs):
    result = {'capture_complete': obs.get('error_type') is None and all('terminal' in obs.get('variants', {}).get(v, {}) for v in VARIANTS),
              'config_unchanged': bool(obs.get('config_before')) and obs.get('config_before') == obs.get('config_after')}
    before = obs.get('business_grants', [])
    ids = {g['grant_id'] for g in before}
    for variant in VARIANTS:
        row = obs.get('variants', {}).get(variant, {})
        terminal = row.get('terminal', {})
        cid = row.get('plan', {}).get('check_id')
        records = [r for r in row.get('records', {}).values() if r['result']['check_id'] == cid]
        latest = max(records, key=lambda r: r['revision'], default={})
        grants = row.get('grants', {}).get('grants', [])
        prefix = variant + ':'
        result[prefix + 'same_instance'] = bool(cid) and terminal.get('instance_id') == obs.get('instance_id')
        result[prefix + 'signed_latest_API'] = bool(latest) and latest.get('result') == terminal
        result[prefix + 'has_bound_session'] = bool(latest.get('binding_id'))
        result[prefix + 'cleanup'] = terminal.get('cleanup') == 'complete' and row.get('materials') == []
        result[prefix + 'temporary_grant_revoked'] = bool(latest.get('grant_id')) and any(g['grant_id'] == latest['grant_id'] and g['status'] == 'revoked' for g in grants)
        result[prefix + 'business_grants_unchanged'] = bool(before) and [g for g in grants if g['grant_id'] in ids] == before
        result[prefix + 'host_stopped_by_product'] = row.get('host_after') == 'absent' and row.get('observer_stopped') is True and not row.get('intervention_cleanup', True)
        if variant != 'recovery':
            result[prefix + 'first_read_checkpoint'] = stage_measured(row)
            old = row.get('receipts_before', [])
            final = obs.get('receipts', {}).get('receipts', [])
            session = next((r.get('session_id') for r in own_receipts(old, cid) if r.get('session_id')), None) if cid else None
            result[prefix + 'exact_prefix_preserved'] = bool(old) and final[:len(old)] == old
            result[prefix + 'no_new_allow'] = bool(cid and session) and not any(r.get('action') == 'allow'
                and (r.get('agent_id') == 'rca-' + cid[3:] or r.get('session_id') == session)
                for r in final[len(old):])
        if variant == 'grant-revoked':
            result[prefix + 'actual_revocation'] = row.get('grant_before_revoke', {}).get('grant', {}).get('status') == 'deployed' and row.get('grant_after_revoke', {}).get('grant', {}).get('status') == 'revoked' and row.get('signals') == ['SIGSTOP', 'SIGCONT']
            result[prefix + 'revoked_failed'] = terminal.get('status') == 'failed' and terminal.get('reason_code') != 'runtime_check_timeout'
        elif variant == 'cancel':
            result[prefix + 'cancelled'] = terminal.get('status') == 'cancelled' and terminal.get('reason_code') == 'runtime_check_cancelled' and row.get('signals') == ['SIGSTOP']
            result[prefix + 'cancel_target'] = bool(cid) and row.get('cancel_response', {}).get('check_id') == cid
        else:
            result[prefix + 'recovery_passed'] = terminal.get('status') == 'passed' and terminal.get('reason_code') == 'runtime_check_passed' and len(set(terminal.get('receipt_ids', []))) == 5
    return result


def score(p, unit, raw):
    result = onboarding.score(p, unit, raw)
    fault = checks(raw['runtime_check_observation'])
    result['bound_fault_checks'] = fault
    result['checks'].update(fault)
    result['checks_passed'] = all(result['checks'].values())
    result['measurement_complete'] = result['measurement_complete'] and fault['capture_complete'] and all(fault[v + ':first_read_checkpoint'] for v in VARIANTS if v != 'recovery')
    result['scope'] = 'actual post-first-read authority/cancel behavior; product receipts, no independent physical effect oracle for selfcheck'
    return result


def freeze(campaign, run_id):
    path = faults.freeze(campaign, run_id)
    p = json.loads(path.read_text())
    p['profile'] = PROFILE
    p.pop('runtime_fault_registration', None)
    reg = campaign / 'plan/bound-runtime-faults-001.md'
    p['bound_fault_registration'] = {'path': str(reg), 'sha256': sha256(reg)}
    p['profile_contract'] = 'pause actual bound host after first observed read, before final read; revoke/cancel and recover'
    for name in ('bound_runtime_faults.py', 'verify_bound_runtime_faults.py'):
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
