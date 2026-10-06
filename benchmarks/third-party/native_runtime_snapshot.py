"""Real product selfcheck snapshot changes and independent business authority status."""
import argparse
import json
from pathlib import Path

import native_personal_onboarding as onboarding
import native_personal_runtime_check as runtime
import native_runtime_faults as faults
from common import sha256, write_json

PROFILE = 'native-runtime-snapshot'
VARIANTS = ('workspace-control', 'skill-content', 'plugin-entry', 'plugin-manifest', 'plugin-config', 'service-mode', 'business-grant', 'business-identity')
INVALIDATES = {'plugin-entry', 'plugin-manifest', 'plugin-config', 'service-mode'}
REVOKES = {'business-grant', 'business-identity'}


def diagnosis(catalog, instance_id):
    d = runtime.instance(catalog, instance_id)['diagnosis']
    return {'configuration_state': d['configuration_state'], 'runtime_state': d['runtime_state'],
            'checks': {c['code']: c['status'] for c in d['checks']}}


def exercise(h, variant):
    obs = {'variant': variant, 'instance_id': h.instance_id, 'error_type': None}
    profile = Path(h.env['HERMES_HOME'])
    paths = {'workspace-control': h.workspace / 'snapshot-unrelated.txt',
             'skill-content': profile / 'skills/intent-fixture/SKILL.md',
             'plugin-entry': profile / 'plugins/siq-agent-security/__init__.py',
             'plugin-manifest': profile / 'plugins/siq-agent-security/plugin.yaml',
             'plugin-config': profile / 'plugins/siq-agent-security/config.json'}
    changed, original = None, None
    try:
        faults.exercise(h, variants=('recovery',))
        obs['baseline'] = h.runtime_check_observation
        base = obs['baseline']['variants'].get('recovery', {})
        if obs['baseline']['error_type'] or base.get('terminal', {}).get('status') != 'passed':
            raise ValueError('baseline selfcheck did not pass')
        route = '/v1/runtime-checks/' + base['plan']['check_id']
        obs['before_instances'] = h.api('/v1/adapter/instances?platform=hermes')
        cfg = json.loads((profile / 'plugins/siq-agent-security/config.json').read_text())
        rid = cfg['runtime_identity_id']
        obs['identity_before'] = next(r for r in h.api('/v1/runtime-identities')['items'] if r['identity_id'] == rid)
        gid = obs['identity_before']['grant_ref']['grant_id']
        obs['grant_before'] = h.api('/v1/grants/' + gid)
        if variant in paths:
            changed = paths[variant]
            original = changed.read_bytes() if changed.exists() else None
            obs['mutation'] = {'path': str(changed), 'before_sha256': sha256(changed) if changed.exists() else None,
                               'kind': 'owned_file_bytes'}
            changed.write_bytes((original or b'') + (b'\n ' if variant == 'plugin-config' else b'\n# SIQ snapshot evaluation change\n'))
            obs['mutation']['changed_sha256'] = sha256(changed)
        elif variant == 'service-mode':
            obs['mutation'] = {'kind': 'service_mode', 'before': h.api('/v1/config')}
            obs['mutation']['response'] = h.api('/v1/config', {'enforcement_mode': 'warn'})
            obs['mutation']['changed'] = h.api('/v1/config')
        elif variant == 'business-grant':
            obs['mutation'] = {'kind': 'business_grant_revoke', 'response': h.api('/v1/grants/' + gid + '/revoke',
                {'expected_revision': obs['grant_before']['state_revision'], 'actor_id': 'evaluation-operator'})}
        elif variant == 'business-identity':
            obs['mutation'] = {'kind': 'business_identity_revoke', 'response': h.api('/v1/runtime-identities/' + rid + '/revoke',
                {'schema_version': 'local-runtime-identity-revoke/v1', 'actor_id': 'evaluation-operator'})}
            obs['mutation']['signed_revocation'] = json.loads((h.state / 'runtime-identity-revocations' / (rid + '.json')).read_text())
        else:
            raise ValueError('unregistered snapshot variant')
        obs['after_change'] = h.api(route)
        obs['changed_instances'] = h.api('/v1/adapter/instances?platform=hermes')
        obs['changed_latest'] = h.api('/v1/runtime-checks?instance_id=' + h.instance_id)
        obs['grant_after'] = h.api('/v1/grants/' + gid)
        obs['identity_after'] = next(r for r in h.api('/v1/runtime-identities')['items'] if r['identity_id'] == rid)
        obs['records_after_change'] = runtime.snapshot_records(h)
        if changed is not None:
            if original is None:
                changed.unlink()
            else:
                changed.write_bytes(original)
            obs['mutation']['restored_sha256'] = sha256(changed) if changed.exists() else None
        elif variant == 'service-mode':
            h.api('/v1/config', {'enforcement_mode': obs['mutation']['before']['enforcement_mode']})
            obs['mutation']['restored'] = h.api('/v1/config')
        obs['after_restore'] = h.api(route)
        obs['restored_instances'] = h.api('/v1/adapter/instances?platform=hermes')
        obs['identity_restored'] = next(r for r in h.api('/v1/runtime-identities')['items'] if r['identity_id'] == rid)
        faults.exercise(h, variants=('recovery',))
        obs['fresh'] = h.runtime_check_observation
        obs['old_after_fresh'] = h.api(route)
        obs['latest_after_fresh'] = h.api('/v1/runtime-checks?instance_id=' + h.instance_id)
        obs['fresh_instances'] = h.api('/v1/adapter/instances?platform=hermes')
    except Exception as error:  # noqa: BLE001 -- retain partial observation without secret exception text
        obs['error_type'] = type(error).__name__
    finally:
        if changed is not None:
            if original is None:
                changed.unlink(missing_ok=True)
            else:
                changed.write_bytes(original)
        if variant == 'service-mode' and obs.get('mutation', {}).get('before'):
            h.api('/v1/config', {'enforcement_mode': obs['mutation']['before']['enforcement_mode']})
        obs['records_final'] = runtime.snapshot_records(h)
        obs['receipts_final'] = {'receipts': h.receipts(), 'public_key': h.command([str(h.binary), 'pubkey']).strip()}
        h.runtime_check_observation = obs


def one(p, unit, out, fixture, budget):
    previous = runtime.exercise
    runtime.exercise = lambda h: exercise(h, p['snapshot_variant'])
    try:
        return runtime.one(p, unit, out, fixture, budget)
    finally:
        runtime.exercise = previous


def checks(obs, variant):
    wanted = 'invalidated' if variant in INVALIDATES else 'passed'
    base = obs.get('baseline', {}).get('variants', {}).get('recovery', {})
    fresh = obs.get('fresh', {}).get('variants', {}).get('recovery', {})
    result = {'snapshot_capture_complete': obs.get('error_type') is None and obs.get('variant') == variant and 'fresh_instances' in obs,
              'snapshot_baseline_passed': base.get('terminal', {}).get('status') == 'passed',
              'snapshot_expected_old_status': obs.get('after_change', {}).get('status') == wanted and obs.get('after_change', {}).get('reason_code') == ('runtime_check_snapshot_changed' if variant in INVALIDATES else 'runtime_check_passed'),
              'snapshot_restore_old_status': obs.get('after_restore', {}).get('status') == wanted,
              'snapshot_old_stays_after_fresh': obs.get('old_after_fresh', {}).get('status') == wanted,
              'snapshot_fresh_check_passed': fresh.get('terminal', {}).get('status') == 'passed',
              'snapshot_distinct_check_ids': bool(base.get('plan')) and bool(fresh.get('plan')) and base['plan']['check_id'] != fresh['plan']['check_id'],
              'snapshot_latest_joins_old': obs.get('changed_latest', {}).get('items') == [obs.get('after_change')],
              'snapshot_latest_joins_fresh': obs.get('latest_after_fresh', {}).get('items') == [fresh.get('terminal')],
              'snapshot_cleanup': all(r.get('terminal', {}).get('cleanup') == 'complete' and r.get('materials') == [] and r.get('host_after') == 'absent' and r.get('observer_stopped') is True and r.get('intervention_cleanup') is False for r in (base, fresh))}
    try:
        before, after, restored, final = [diagnosis(obs[k], obs['instance_id']) for k in ('before_instances', 'changed_instances', 'restored_instances', 'fresh_instances')]
        result['snapshot_diagnosis_separates_scope'] = before['checks']['hook_load'] == final['checks']['hook_load'] == 'pass' and after['checks']['hook_load'] == restored['checks']['hook_load'] == ('unknown' if variant in INVALIDATES else 'pass') and all(d['runtime_state'] == 'unverified' for d in (before, after, restored, final))
        result['snapshot_business_authority_diagnosis'] = before['checks']['instance_authority'] == 'pass' and after['checks']['instance_authority'] == ('fail' if variant in REVOKES or variant == 'skill-content' else 'pass') and restored['checks']['instance_authority'] == final['checks']['instance_authority'] == ('fail' if variant in REVOKES else 'pass')
    except (KeyError, ValueError, StopIteration):
        result['snapshot_diagnosis_separates_scope'] = result['snapshot_business_authority_diagnosis'] = False
    mutation = obs.get('mutation', {})
    if mutation.get('kind') == 'owned_file_bytes':
        changed = mutation.get('before_sha256') != mutation.get('changed_sha256') and mutation.get('before_sha256') == mutation.get('restored_sha256')
    elif variant == 'service-mode':
        changed = mutation.get('before', {}).get('enforcement_mode') == mutation.get('restored', {}).get('enforcement_mode') == 'block' and mutation.get('changed', {}).get('enforcement_mode') == 'warn'
    elif variant == 'business-grant':
        changed = obs.get('grant_before', {}).get('grant', {}).get('status') == 'approved' and obs.get('grant_after', {}).get('grant', {}).get('status') == 'revoked' and obs.get('identity_after', {}).get('status') == 'grant_unavailable'
    else:
        changed = mutation.get('response', {}).get('revoked') is True and obs.get('identity_before', {}).get('status') == 'issued' and obs.get('identity_after', {}).get('status') == 'revoked'
    result['snapshot_actual_change_and_restoration'] = changed
    expected_changed = 'revoked' if variant == 'business-identity' else 'grant_unavailable' if variant in ('business-grant', 'skill-content') else 'issued'
    expected_restored = expected_changed if variant in REVOKES else 'issued'
    result['snapshot_identity_scope_readback'] = obs.get('identity_before', {}).get('status') == 'issued' and obs.get('identity_after', {}).get('status') == expected_changed and obs.get('identity_restored', {}).get('status') == expected_restored
    result['snapshot_unrelated_grants_unchanged'] = all(x.get('error_type') is None and [g for g in x.get('variants', {}).get('recovery', {}).get('grants', {}).get('grants', []) if g['grant_id'] in {a['grant_id'] for a in x.get('business_grants', [])}] == x.get('business_grants') for x in (obs.get('baseline', {}), obs.get('fresh', {})))
    return result


def score(p, unit, raw):
    result = onboarding.score(p, unit, raw)
    extra = checks(raw['runtime_check_observation'], p['snapshot_variant'])
    result['snapshot_checks'] = extra
    result['checks'].update(extra)
    result['checks_passed'] = all(result['checks'].values())
    result['measurement_complete'] = result['measurement_complete'] and extra['snapshot_capture_complete']
    result['scope'] = 'product selfcheck snapshot versus business authority status; real native host; no independent syscall oracle for selfcheck probes'
    return result


def freeze(campaign, run_id, variant):
    if variant not in VARIANTS:
        raise ValueError('unknown snapshot variant')
    path = faults.freeze(campaign, run_id)
    p = json.loads(path.read_text())
    p.update(profile=PROFILE, snapshot_variant=variant, profile_contract='two actual product selfchecks bracketing one isolated snapshot or business-authority change')
    p.pop('runtime_fault_registration', None)
    reg = campaign / 'plan/native-runtime-snapshot-002.md'
    p['snapshot_registration'] = {'path': str(reg), 'sha256': sha256(reg)}
    for name in ('native_runtime_snapshot.py', 'verify_native_runtime_snapshot.py'):
        (path.parent / 'harness-source' / name).write_bytes(Path(__file__).with_name(name).read_bytes())
    root = Path(p['candidate_root'])
    for source in (root / 'apps/agentshield/internal/runtimeidentity').glob('*.go'):
        p['candidate_sources'][str(source.relative_to(root))] = sha256(source)
    p['harness_sources'] = {str(f.relative_to(path.parent / 'harness-source')): sha256(f) for f in (path.parent / 'harness-source').rglob('*') if f.is_file()}
    write_json(path, p, exclusive=False)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'run'))
    parser.add_argument('--campaign', type=Path)
    parser.add_argument('--run-id')
    parser.add_argument('--variant', choices=VARIANTS)
    parser.add_argument('--protocol', type=Path)
    args = parser.parse_args()
    if args.action == 'freeze':
        print(freeze(args.campaign.resolve(), args.run_id, args.variant))
    else:
        onboarding.base.one, onboarding.base.score, onboarding.base.configure_gold = one, score, onboarding.configure
        raise SystemExit(onboarding.base.run(args.protocol))
