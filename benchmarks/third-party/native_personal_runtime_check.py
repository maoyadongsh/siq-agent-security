"""Actual product runtime check following the same-instance onboarding journey."""
import argparse
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import native_personal_onboarding as onboarding
from common import sha256, utc_now, write_json
from lifecycle import process_state
from process_resources import identity

PROFILE = 'native-personal-runtime-check'


def snapshot_records(h):
    return {p.name: json.loads(p.read_text()) for p in sorted((h.state / 'runtime-checks').glob('*.json'))}


def instance(catalog, instance_id):
    rows = [r for r in catalog['instances'] if r['instance_id'] == instance_id]
    if len(rows) != 1:
        raise ValueError('runtime-check instance is missing or ambiguous')
    return rows[0]


def exercise(h):
    obs = {'instance_id': h.instance_id, 'stages': {}, 'error_type': None, 'owned_host_processes': []}
    h.runtime_check_observation = obs
    stages = obs['stages']
    config = Path(h.env['HERMES_HOME']) / 'config.yaml'
    original = config.read_bytes()
    obs['profile_config_before_sha256'] = sha256(config)
    finished = threading.Event()

    def monitor():
        known = set()
        while not finished.wait(0.01):
            try:
                children = set()
                for task in Path(f'/proc/{h.proc.pid}/task').iterdir():
                    children.update(map(int, (task / 'children').read_text().split()))
                for pid in children:
                    if pid in known:
                        continue
                    ref = identity(pid)
                    argv = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
                    if b'chat' in argv and b'SIQ synthetic runtime check' in b' '.join(argv):
                        known.add(pid)
                        obs['owned_host_processes'].append(ref)
            except (FileNotFoundError, ProcessLookupError):
                continue
            except Exception as error:  # noqa: BLE001 -- preserve observer failure, not exception text
                obs['process_observer_error'] = type(error).__name__
                return

    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    try:
        stages['before_instances'] = h.api('/v1/adapter/instances?platform=hermes')
        stages['grants_before'] = h.api('/v1/grants')
        stages['plan'] = h.api('/v1/runtime-checks/preview', {
            'schema_version': 'local-runtime-check-preview/v1', 'instance_id': h.instance_id})
        plan = stages['plan']
        route = '/v1/runtime-checks/' + plan['check_id']
        stages['grants_after_preview'] = h.api('/v1/grants')
        body = {'schema_version': 'local-runtime-check-start/v1', 'check_id': plan['check_id'],
                'plan_digest': plan['plan_digest'], 'actor_id': 'evaluation-operator', 'confirm': True}
        stages['bad_digest'] = h.api('/v1/runtime-checks/start', {**body, 'plan_digest': '0' * 64}, expected=403)
        stages['no_confirmation'] = h.api('/v1/runtime-checks/start', {**body, 'confirm': False}, expected=400)
        stages['grants_after_rejections'] = h.api('/v1/grants')
        stages['started'] = h.api('/v1/runtime-checks/start', body, expected=202)
        deadline = time.monotonic() + 145
        while True:
            current = h.api(route)
            stages['terminal'] = current
            if current['status'] in ('passed', 'failed', 'invalidated', 'cancelled'):
                break
            if time.monotonic() > deadline:
                stages['cancel_after_deadline'] = h.api(route + '/cancel')
                raise TimeoutError('runtime check did not terminate')
            time.sleep(0.2)
        if current['receipt_ids']:
            stages['activity'] = h.api(route + '/activity')
        stages['receipts'] = {'receipts': h.receipts(), 'public_key': h.command([str(h.binary), 'pubkey']).strip()}
        stages['records_before_drift'] = snapshot_records(h)
        stages['grants_after'] = h.api('/v1/grants')
        stages['intents_after'] = h.api('/v1/intents')
        stages['bindings_after'] = h.api('/v1/intent-bindings')
        stages['instances_after'] = h.api('/v1/adapter/instances?platform=hermes')
        stages['latest_after'] = h.api('/v1/runtime-checks?instance_id=' + h.instance_id)
        obs['materials_after'] = [p.name for p in (h.state / 'runtime-check-materials').iterdir()]
        obs['profile_config_after_sha256'] = sha256(config)
        config.write_bytes(original + b'\n# evaluation runtime-check snapshot drift\n')
        obs['profile_config_drift_sha256'] = sha256(config)
        stages['after_drift'] = h.api(route)
        stages['instances_drift'] = h.api('/v1/adapter/instances?platform=hermes')
        config.write_bytes(original)
        obs['profile_config_restored_sha256'] = sha256(config)
        stages['after_restore'] = h.api(route)
        stages['instances_restored'] = h.api('/v1/adapter/instances?platform=hermes')
        stages['records_after_restore'] = snapshot_records(h)
    except Exception as error:  # noqa: BLE001 -- preserve first partial attempt and always clean owned processes
        obs['error_type'] = type(error).__name__
    finally:
        config.write_bytes(original)
        finished.set()
        watcher.join(timeout=3)
        obs['process_observer_stopped'] = not watcher.is_alive()
        obs['owned_host_process_states'] = [process_state(ref) for ref in obs['owned_host_processes']]
        obs['scope'] = 'actual product self-check; signed outcomes plus observed process, no external syscall oracle for its ephemeral probes'


def one(p, unit, out, fixture, budget):
    class Harness(fixture.Harness):
        def cleanup_task_attribution(self):
            super().cleanup_task_attribution()
            if not getattr(self, '_evaluated_runtime_check', False) and getattr(self, 'proc', None) is not None:
                self._evaluated_runtime_check = True
                exercise(self)

    raw = onboarding.one(p, unit, out, SimpleNamespace(Harness=Harness), budget)
    raw['runtime_check_observation'] = getattr(onboarding.active_harness, 'runtime_check_observation', {
        'error_type': 'not_started', 'stages': {}})
    path = out / 'cases' / unit['unit_id']
    events = path / 'events.jsonl'
    with events.open('a') as stream:
        stream.write(json.dumps({'sequence': len(events.read_text().splitlines()) + 1,
                                 'run_id': unit['unit_id'], 'utc': utc_now(), 'event': 'product_runtime_check_observed',
                                 'record': raw['runtime_check_observation']}) + '\n')
    write_json(path / 'result.json', raw, exclusive=False)
    return raw


def checks(obs):
    s = obs.get('stages', {})
    terminal = s.get('terminal', {})
    before = s.get('grants_before', {}).get('grants', [])
    after = s.get('grants_after', {}).get('grants', [])
    ids = {g['grant_id'] for g in before}
    new = [g for g in after if g['grant_id'] not in ids]
    plan = s.get('plan', {})
    check_id = plan.get('check_id')
    records = s.get('records_before_drift', {})
    final = max(records.values(), key=lambda r: r['revision'], default={})
    latest = s.get('latest_after', {}).get('items', [])

    def hook(stage):
        try:
            row = instance(s[stage], obs['instance_id'])
            diagnosis = row['diagnosis']
            return next(c['status'] for c in diagnosis['checks'] if c['code'] == 'hook_load'), diagnosis['runtime_state']
        except (KeyError, ValueError, StopIteration):
            return None, None

    return {
        'selfcheck_capture_complete': obs.get('error_type') is None and 'after_restore' in s,
        'same_instance_preview': bool(check_id) and plan.get('instance_id') == obs.get('instance_id'),
        'preview_no_grant_change': bool(before) and before == s.get('grants_after_preview', {}).get('grants'),
        'rejected_starts_no_grant_change': bool(before) and before == s.get('grants_after_rejections', {}).get('grants'),
        'bad_digest_rejected': s.get('bad_digest', {}).get('error') == 'runtime_check_launch_credential_invalid',
        'explicit_confirmation_required': s.get('no_confirmation', {}).get('error') == 'runtime_check_invalid_request',
        'product_selfcheck_passed': terminal.get('status') == 'passed' and terminal.get('reason_code') == 'runtime_check_passed',
        'five_product_receipts': len(set(terminal.get('receipt_ids', []))) == 5,
        'separate_temporary_grant_revoked': len(new) == 1 and new[0]['status'] == 'revoked' and bool(new[0]['expires_at']),
        'business_grants_unchanged': bool(before) and [g for g in after if g['grant_id'] in ids] == before,
        'product_cleanup_complete': terminal.get('cleanup') == 'complete' and obs.get('materials_after') == [],
        'profile_preserved_and_restored': bool(obs.get('profile_config_before_sha256')) and
            obs.get('profile_config_before_sha256') == obs.get('profile_config_after_sha256') == obs.get('profile_config_restored_sha256') != obs.get('profile_config_drift_sha256'),
        'signed_record_matches_API': final.get('result') == terminal and final.get('result', {}).get('check_id') == check_id,
        'activity_bound_to_check': s.get('activity', {}).get('check_id') == check_id and s.get('activity', {}).get('instance_id') == obs.get('instance_id') and s.get('activity', {}).get('prefix_valid') is True,
        'latest_matches_result': latest == [terminal],
        'hook_load_pass_without_diagnostic_promotion': hook('instances_after') == ('pass', 'unverified'),
        'drift_invalidates_result': s.get('after_drift', {}).get('status') == 'invalidated' and s.get('after_drift', {}).get('reason_code') == 'runtime_check_snapshot_changed',
        'restore_does_not_revive_old_pass': s.get('after_restore', {}).get('status') == 'invalidated',
        'stale_hook_load_unknown': hook('instances_drift') == hook('instances_restored') == ('unknown', 'unverified'),
        'actual_product_host_observed': len(obs.get('owned_host_processes', [])) == 1 and 'process_observer_error' not in obs,
        'product_host_stopped': obs.get('owned_host_process_states') == ['absent'] and obs.get('process_observer_stopped') is True,
    }


def score(p, unit, raw):
    result = onboarding.score(p, unit, raw)
    result['runtime_check_checks'] = checks(raw['runtime_check_observation'])
    result['checks'].update(result['runtime_check_checks'])
    result['checks_passed'] = all(result['checks'].values())
    result['measurement_complete'] = result['measurement_complete'] and result['runtime_check_checks']['selfcheck_capture_complete']
    result['scope'] = 'same-instance onboarding plus product self-check and drift; product self-check probe effects not independently syscall-observed'
    return result


def freeze(campaign, run_id):
    path = onboarding.freeze(campaign, run_id)
    p = json.loads(path.read_text())
    p['profile'] = PROFILE
    p['profile_contract'] = 'onboarding plus product-owned selfcheck, temporary authority cleanup, task activity, drift invalidation'
    registration = campaign / 'plan/native-personal-runtime-check-001.md'
    p['runtime_check_registration'] = {'path': str(registration), 'sha256': sha256(registration)}
    for name in ('native_personal_runtime_check.py', 'verify_native_personal_runtime_check.py'):
        dest = path.parent / 'harness-source' / name
        dest.write_bytes(Path(__file__).with_name(name).read_bytes())
    root = Path(p['candidate_root'])
    for directory in ('apps/agentshield/internal/runtimecheck', 'apps/agentshield/internal/adapterinstall'):
        for source in (root / directory).glob('*.go'):
            p['candidate_sources'][str(source.relative_to(root))] = sha256(source)
    for name in ('runtime_check.go', 'runtime_check_activity.go', 'adapter_diagnostics.go'):
        source = root / 'apps/agentshield/internal/server' / name
        p['candidate_sources'][str(source.relative_to(root))] = sha256(source)
    p['harness_sources'] = {str(f.relative_to(path.parent / 'harness-source')): sha256(f)
                            for f in (path.parent / 'harness-source').rglob('*') if f.is_file()}
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
        onboarding.base.one = one
        onboarding.base.score = score
        onboarding.base.configure_gold = onboarding.configure
        raise SystemExit(onboarding.base.run(args.protocol))
