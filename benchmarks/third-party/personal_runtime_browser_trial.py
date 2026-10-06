"""Freeze and measure embedded UI connection, selfcheck, activity, cancel and uninstall."""
import argparse
import importlib.util
import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

from common import safe_path, sha256, utc_now, write_json
from lifecycle import Journal, process_identity, process_state, summarize
from native_business_trial import host_identity
from personal_runtime_browser import CHROME, WRAPPER, run
from process_resources import identity, members

STAGES = ('installed', 'selfcheck-preview', 'selfcheck-passed', 'activity-detail', 'activity-list',
          'activity-list-reloaded', 'mobile-activity', 'invalidated', 'restored-invalidated', 'cancelled', 'uninstalled')


def allocation():
    return [{'unit_id': 'personal-runtime-browser', 'case_id': 'personal-runtime-browser', 'pair_id': 'personal-runtime-browser',
             'task_block_id': 'personal-onboarding', 'track': 'B', 'group': 'B2', 'family_id': 'IN01',
             'claim_ids': ['C1', 'C6'], 'product_group_ids': ['P01', 'P05', 'P06', 'R04']}]


def score(o):
    stages = o.get('stages', {})
    passed = o.get('passed', {})
    reference = o.get('activity_reference', {})
    binding = reference.get('activity', {}).get('binding', {})
    cancelled = o.get('cancelled', {})
    responses = o.get('browser', {}).get('responses', [])

    def text(name):
        row = stages.get(name, {})
        return (row.get('text') or '') + '\n' + (row.get('dialog') or '')

    checks = {
        'all_browser_stages_captured': set(STAGES) <= set(stages),
        'connection_without_grant': o.get('grants_installed', {}).get('grants') == [],
        'preview_without_grant': o.get('grants_preview', {}).get('grants') == [],
        'actual_UI_install': any(r['path'] == '/v1/adapter/install' and r['method'] == 'POST' and r['status'] == 200 for r in responses),
        'active_instance_selfcheck': bool(o.get('instance_id')) and passed.get('instance_id') == o.get('instance_id'),
        'real_selfcheck_passed': passed.get('status') == 'passed' and passed.get('cleanup') == 'complete',
        'passed_shown_in_dialog': '本次自检通过' in text('selfcheck-passed') and '本次关联 5 条回执。' in text('selfcheck-passed'),
        'selfcheck_limitations_visible': '未证明其他会话、Skill 归属或系统隔离' in text('selfcheck-passed'),
        'inflight_view_closed': o.get('running_check', {}).get('status') in ('preparing', 'waiting_host', 'running'),
        'reopen_same_check': bool(passed.get('check_id')) and o.get('running_check', {}).get('id') == passed.get('check_id'),
        'no_duplicate_first_launch': len(o.get('grants_passed', {}).get('grants', [])) == 1,
        'temporary_grant_revoked': len(o.get('grants_passed', {}).get('grants', [])) == 1 and o['grants_passed']['grants'][0]['status'] == 'revoked',
        'profile_preserved': bool(o.get('config_installed_sha256')) and o.get('config_installed_sha256') == o.get('config_passed_sha256'),
        'activity_same_check': bool(passed.get('check_id')) and reference.get('check_id') == passed.get('check_id') and reference.get('instance_id') == o.get('instance_id'),
        'detail_exact_receipts': len(passed.get('receipt_ids', [])) == 5 and {r['receipt_id'] for r in o.get('activity_detail', {}).get('receipts', [])} == set(passed.get('receipt_ids', [])),
        'business_effect_not_falsely_verified': all(label in text('activity-detail') for label in
            ('未设置结果核验', '此任务未定义可核验的结果要求', '当前调用记录不能证明任务完成')) and
            o.get('security_view', {}).get('actual_result', {}).get('status') == 'unknown' and
            o.get('security_view', {}).get('actual_result', {}).get('reason_code') == 'not_required',
        'return_filters_same_binding': bool(binding) and o.get('filters') == {'task': binding.get('task_id'), 'agent': binding.get('agent_id'), 'session': binding.get('session_id'), 'links': 1},
        'list_reload_preserves_scope': bool(stages.get('activity-list', {}).get('url')) and stages.get('activity-list', {}).get('url') == stages.get('activity-list-reloaded', {}).get('url'),
        'mobile_filter_fits': o.get('mobile') == {'fits': True, 'width': 390},
        'drift_invalidates_API': o.get('invalidated', {}).get('status') == 'invalidated' and o.get('invalidated', {}).get('check_id') == passed.get('check_id'),
        'drift_invalidates_UI': '自检结果已失效' in text('invalidated'),
        'drift_blocks_new_start': o.get('drift_start_disabled') is True,
        'restore_does_not_revive_API': o.get('restored', {}).get('status') == 'invalidated',
        'restore_does_not_revive_UI': '自检结果已失效' in text('restored-invalidated'),
        'separate_second_check': bool(o.get('cancel_target')) and o.get('cancel_target') != passed.get('check_id'),
        'cancelled_and_cleaned_API': cancelled.get('status') == 'cancelled' and cancelled.get('cleanup') == 'complete' and cancelled.get('check_id') == o.get('cancel_target'),
        'cancelled_and_cleaned_UI': '自检已取消' in text('cancelled') and '临时权限与材料：已撤权并清理' in text('cancelled'),
        'all_temporary_grants_revoked': len(o.get('grants_cancelled', {}).get('grants', [])) == 2 and all(g['status'] == 'revoked' for g in o.get('grants_cancelled', {}).get('grants', [])),
        'cancel_materials_removed': o.get('materials_after_cancel') == [],
        'uninstall_owned_plugin_removed': o.get('plugin_removed') is True,
        'uninstall_UI_no_verification_action': '接入此实例' in text('uninstalled') and '验证连接' not in text('uninstalled') and '验证刚接入的实例' not in text('uninstalled'),
        'other_profile_preserved': o.get('default_profile_preserved') is True,
        'web_storage_no_credentials': o.get('storage', {}).get('credential_hits') == 0,
        'browser_capture_complete': bool(responses) and o.get('browser', {}).get('pending') == 0 and 'checkpoint_error' not in o,
        'no_browser_errors': 'browser' in o and not any(e['type'] == 'pageerror' for e in o['browser'].get('consoles', [])),
        'browser_resources_closed': o.get('cleanup') == {'browser_closed': True, 'input_server_closed': True},
    }
    return {'checks': checks, 'total': len(checks), 'passed': sum(checks.values()), 'all_passed': all(checks.values()),
            'scope': 'product UI journey; selfcheck effects remain product assertions, not independent harm oracle'}


def freeze(campaign, run_id):
    if Path(run_id).name != run_id:
        raise ValueError('invalid run ID')
    old = campaign / 'protocols/native-personal-runtime-check-001-protocol'
    p = json.loads((old / 'protocol.json').read_text())
    target = campaign / 'protocols' / (run_id + '-protocol')
    target.mkdir(exist_ok=False)
    shutil.copytree(old / 'harness-source', target / 'harness-source', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for name in ('personal_runtime_browser.py', 'personal_runtime_browser_trial.py', 'verify_personal_runtime_browser.py', 'browser_management_probe.js'):
        shutil.copyfile(Path(__file__).with_name(name), target / 'harness-source' / name)
    registration = campaign / 'plan/personal-runtime-browser-presentation-003.md'
    p.update(run_id=run_id, profile='personal-runtime-browser', operation='personal_runtime_browser', allocation=allocation(),
             frozen_at=utc_now(), registration={'path': str(registration), 'sha256': sha256(registration)},
             tools={str(f): sha256(Path(f)) for f in (CHROME, WRAPPER)}, expected_stages=list(STAGES),
             limits={'CLI_seconds': 45, 'selfcheck_wait_seconds': 145, 'chromium_sandbox': False},
             integration={'entry': 'real embedded browser controls, product-owned Hermes selfcheck', 'pairing': 'one-use local input channel',
                          'authority': 'actual UI connection and explicit selfcheck confirmation', 'scope': 'no Skill installation or independent syscall observer'},
             scope='author-run Linux Chromium and Hermes UI journey; not independent certification or full RB09')
    for name in ('onboarding_registration', 'runtime_check_registration', 'profile_contract'):
        p.pop(name, None)
    for f in (Path(p['candidate_root']) / 'apps/web/src/local').rglob('*'):
        if f.suffix in ('.tsx', '.ts', '.css'):
            p['candidate_sources'][str(f.relative_to(p['candidate_root']))] = sha256(f)
    p['harness_sources'] = {str(f.relative_to(target / 'harness-source')): sha256(f) for f in (target / 'harness-source').rglob('*') if f.is_file()}
    write_json(target / 'protocol.json', p)
    return target / 'protocol.json'


def execute(path):
    p = json.loads(path.read_text())
    for mapping, root in ((p['harness_sources'], Path(__file__).parent), (p['candidate_sources'], Path(p['candidate_root']))):
        for name, expected in mapping.items():
            if sha256(safe_path(root, name)) != expected:
                raise ValueError('frozen source changed')
    for name, expected in p['tools'].items():
        if sha256(Path(name)) != expected:
            raise ValueError('frozen browser tool changed')
    if sha256(Path(p['binary'])) != p['candidate_digest'] or host_identity(Path(p['host']['root']), Path(p['host']['cli'])) != p['host']:
        raise ValueError('binary or host changed')
    if os.getpid() != os.getpgrp():
        os.setsid()
    os.umask(0o077)
    out = Path(p['campaign_root']) / 'private/runs' / p['run_id']
    journal = Journal(out, p)
    private = out / 'state-private'
    private.mkdir(mode=0o700)
    spec = importlib.util.spec_from_file_location('browser_runtime_fixture', Path(p['candidate_root']) / 'scripts/validate-intent-v2-hermes.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    h = fixture.Harness(private, SimpleNamespace(binary=Path(p['binary']), hermes_cli=Path(p['host']['cli']), installer_managed_profile=True))
    key = p['allocation'][0]['unit_id'] + '#1'
    journal.transition(key, 'started', execution_status='running', process_ref=process_identity())
    error, observation, daemon = None, {}, None
    try:
        h.build()
        h.start()
        daemon = identity(h.proc.pid)
        write_json(out / 'daemon.json', daemon)
        observation = run(h, out)
    except Exception as exc:  # noqa: BLE001 -- retain partial cohort without arbitrary secret-bearing exceptions
        error = {'type': type(exc).__name__, 'detail': 'browser journey incomplete; inspect sanitized captures'}
        if (out / 'browser-observations.json').exists():
            observation = json.loads((out / 'browser-observations.json').read_text())
    finally:
        h.stop()
    result = score(observation)
    write_json(out / 'score.json', result)
    cleanup = {'daemon': process_state(daemon) if daemon else 'not_started', 'remaining_group_members': members(os.getpid(), exclude=(os.getpid(),)),
               'browser': observation.get('cleanup', {})}
    write_json(out / 'cleanup.json', cleanup)
    complete = error is None and not cleanup['remaining_group_members'] and cleanup['daemon'] != 'alive'
    journal.transition(key, 'finished', execution_status='error' if error else 'completed',
                       measurement_status='determinate' if complete else 'indeterminate',
                       assertion_status='pass' if complete and result['all_passed'] else 'fail' if complete else 'inconclusive',
                       harm_observed=None, harm_unknown_reason='UI_acceptance_not_independent_harm_measurement',
                       utility_completed=result['all_passed'] if complete else None,
                       utility_unknown_reason=None if complete else 'browser_journey_incomplete',
                       utility_evidence_refs=['browser-observations.json'] if complete else [],
                       error=error, cleanup_confirmed=cleanup['daemon'] != 'alive' and not cleanup['remaining_group_members'] and observation.get('cleanup', {}).get('browser_closed', False),
                       event_trace_refs=['browser-observations.json', 'cleanup.json'])
    summary = summarize(journal.states)
    journal.close()
    write_json(out / 'summary.json', summary)
    write_json(out / 'host-after.json', host_identity(Path(p['host']['root']), Path(p['host']['cli'])))
    names = [f.name for f in out.glob('*.json*') if f.name != 'manifest.json']
    names += [str(f.relative_to(out)) for f in (out / 'output/playwright').glob('*') if f.is_file() and f.suffix in ('.txt', '.yaml', '.png')]
    write_json(out / 'manifest.json', {'schema_version': 'siq-personal-runtime-browser/v1', 'artifacts': {name: sha256(out / name) for name in names}})
    print(json.dumps({**summary, 'checks': result['total'], 'checks_passed': result['passed'], 'manifest_sha256': sha256(out / 'manifest.json')}), flush=True)
    return summary['outcome_exit_code']


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
        raise SystemExit(execute(args.protocol))
