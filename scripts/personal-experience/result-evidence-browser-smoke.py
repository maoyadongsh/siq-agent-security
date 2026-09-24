#!/usr/bin/env python3
"""Real signed task results and host file observations, isolated candidate UI.

Synthetic fixture writes only; no model, native runtime, or business report.
Only transport faults and a mismatched response are injected in browser tests.
"""
import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('fixture', ROOT / 'scripts/validate-intent-v2-hermes.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def create_result(h, kind):
    task, session = 'result-' + kind, 'session-' + kind
    path = h.workspace / (kind + '.txt')
    content = b'synthetic expected output\n'
    resource = 'filesystem:sha256:' + hashlib.sha256(json.dumps(
        {'domain': 'filesystem', 'value': str(path)}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    now = datetime.now(UTC)
    def stamp(delta):
        return (now + timedelta(seconds=delta)).strftime('%Y-%m-%dT%H:%M:%SZ')
    intent = {'schema_version': 'intent/v3', 'intent_id': 'intent-' + kind, 'task_id': task,
        'principal': {'type': 'user', 'id': 'synthetic-operator'},
        'agent': {'id': fixture.AGENT, 'platform': 'hermes'}, 'purpose': 'Synthetic result UX validation',
        'allowed_tools': ['write_file'], 'allowed_effects': ['file.write'],
        'resource_constraints': [{'domain': 'filesystem', 'operator': 'prefix', 'value': str(h.workspace)}],
        'parameter_constraints': [], 'provenance_constraints': [{'parameter_path': '/path',
            'allowed_source_types': ['USER'], 'minimum_trust': 'trusted', 'required': False}],
        'effect_requirements': [{'requirement_id': 'req-' + kind, 'effect_type': 'file.write', 'resource_ref': resource,
            'expected_digest': hashlib.sha256(content).hexdigest(), 'minimum_independence': 'host_independent', 'minimum_coverage': 'partial'}],
        'issued_at': stamp(-60), 'valid_from': stamp(-60), 'expires_at': stamp(3600),
        'authority': {'issuer': 'local-admin', 'revision': 'r1', 'evidence_ids': []}}
    h.api('/v1/intents', intent, expected=201)
    h.api('/v1/intent-bindings', {'platform': 'hermes', 'session_id': session,
        'agent_id': fixture.AGENT, 'intent_id': intent['intent_id']}, expected=201)
    decision = h.api('/v1/decide', {'platform': 'hermes', 'session_id': session, 'agent_id': fixture.AGENT,
        'tool': 'write_file', 'tool_call_id': kind, 'params': {'path': str(path), 'content': 'synthetic'}},
        token=(h.state / 'token').read_text().strip())
    assert decision['action'] == 'allow', 'synthetic write must be explicitly allowed'
    record = None
    if kind != 'missing':
        observer = h.api('/v1/effect-observers', {'source': {'type': 'host_observer', 'source_id': 'synthetic-result-observer',
            'independence': 'host_independent'}, 'scope': {'platform': 'hermes', 'session_id': session,
            'agent_id': fixture.AGENT, 'task_id': task}, 'expires_in': 600}, expected=201)['token']
        h.api('/v1/file-observations', {'observation_id': 'observation-' + kind, 'action_id': decision['action_id'],
            'decision_receipt_id': decision['receipt_id'], 'path': str(path),
            'expected_digest': hashlib.sha256(content).hexdigest(), 'max_bytes': 1024}, token=observer, expected=201)
        if kind in ('verified', 'conflicting'):
            path.write_bytes(content if kind == 'verified' else b'synthetic unexpected output\n')
        record = h.api('/v1/file-observations/observation-' + kind + '/finish', {'path': str(path)}, token=observer, expected=201)
    completion = h.api('/v1/tasks/' + task + '/completion')
    expected = {'missing': ('incomplete', 'effect_evidence_missing'), 'failed': ('incomplete', 'effect_failed'),
                'verified': ('verified', 'effects_verified'), 'conflicting': ('conflicting', 'effect_evidence_conflicting')}
    assert (completion['status'], completion['reason_code']) == expected[kind], completion['reason_code']
    # Material comes from server filesystem reads, not a client supplied completed flag.
    if record:
        independent = h.api('/v1/effect-evidence/' + record['evidence']['effect_evidence_id'])
        assert independent == record
    return task, completion, record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--out-dir', required=True, type=Path)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=False)
    checks, records = {}, {}
    with tempfile.TemporaryDirectory(prefix='siq-result-ux-') as directory:
        root = Path(directory)
        h = fixture.Harness(root, SimpleNamespace(installer_managed_profile=True, hermes_cli=root / 'unavailable'))
        shutil.copy2(args.binary, h.binary)
        try:
            h.start()
            h.setup_authority()
            for kind in ('missing', 'failed', 'conflicting', 'verified'):
                records[kind] = create_result(h, kind)
                checks['backend_' + kind + '_independent_readback'] = True
            decision_token = (h.state / 'token').read_text().strip()
            h.api('/v1/effect-evidence/' + records['verified'][2]['evidence']['effect_evidence_id'], token=decision_token, expected=403)
            checks['decision_credential_cannot_read_result_evidence'] = True
            h.api('/v1/decide', {'platform': 'hermes', 'session_id': fixture.SESSION, 'agent_id': fixture.AGENT,
                'tool': 'read_file', 'params': {'path': str(h.workspace / 'company-a/report.txt')}}, token=decision_token)
            pairing = h.command([str(h.binary), 'pair', '--port', h.endpoint.rsplit(':', 1)[1]])
            code = re.search(r'\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b', pairing).group()
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000}, locale='zh-CN')
                errors, writes = [], []
                page.on('pageerror', lambda _: errors.append('pageerror'))
                page.goto(h.endpoint + '/activities')
                page.get_by_label('配对码', exact=True).fill(code)
                page.get_by_role('button', name='建立管理会话', exact=True).click()
                expect(page.get_by_role('heading', name='运行记录', exact=True)).to_be_visible()
                page.on('request', lambda r: writes.append(r.url.split(h.endpoint)[-1].split('?')[0]) if r.method in ('POST', 'PUT', 'DELETE', 'PATCH') else None)
                labels = {'missing': '结果待核验', 'failed': '观测到执行失败', 'conflicting': '结果需要核查', 'verified': '结果核验通过'}
                for kind, label in labels.items():
                    task, completion, record = records[kind]
                    page.goto(h.endpoint + '/activities?task_id=' + task)
                    expect(page.locator('tbody tr')).to_have_count(1)
                    page.get_by_role('link', name='查看活动记录', exact=True).click()
                    panel = page.get_by_role('region', name='任务安全视图', exact=True)
                    expect(panel.locator('.badge').filter(has_text=label).first).to_be_visible()
                    item = page.get_by_role('region', name='结果要求 1', exact=True)
                    expect(item).to_be_visible()
                    expect(item.get_by_text('req-' + kind, exact=True)).not_to_be_visible()
                    expect(panel.get_by_text(re.compile('正式报告和业务文件请到发起任务的业务系统查看'))).to_be_visible()
                    checks[kind + '_clear_result_without_invented_report'] = True
                    if record:
                        button = item.get_by_role('button', name='查看证据 1', exact=True)
                        button.click()
                        dialog = page.get_by_role('dialog', name='效果证据详情', exact=True)
                        expect(dialog.get_by_text('宿主独立观测', exact=True)).to_be_visible()
                        expect(dialog.get_by_text('部分覆盖', exact=True)).to_be_visible()
                        dialog.get_by_role('button', name='刷新证据', exact=True).focus()
                        page.keyboard.press('Tab')
                        expect(dialog.get_by_text('技术详情：来源与标识', exact=True)).to_be_focused()
                        page.keyboard.press('Enter')
                        checks[kind + '_keyboard_reaches_technical_details'] = True
                        expect(dialog.get_by_text('任务：' + task, exact=True)).to_be_visible()
                        expect(dialog.get_by_text('证据：' + record['evidence']['effect_evidence_id'], exact=True)).to_be_visible()
                        page.keyboard.press('Escape')
                        expect(dialog).not_to_be_visible()
                        expect(button).to_be_focused()
                        checks[kind + '_same_task_evidence_escape_focus'] = True
                    else:
                        expect(item.get_by_role('button')).to_have_count(0)
                    page.reload()
                    expect(page.get_by_role('region', name='结果要求 1').locator('.badge')).to_have_text(label)
                    checks[kind + '_persisted_after_reload'] = True
                # No requirements must remain unknown despite allowed calls.
                verified_url = page.url
                page.goto(h.endpoint + '/activities?task_id=task-native-fixture')
                page.get_by_role('link', name='查看活动记录', exact=True).click()
                expect(page.get_by_text('未设置结果核验', exact=True)).to_be_visible()
                expect(page.get_by_role('region', name='结果要求 1')).to_have_count(0)
                checks['allowed_call_without_requirements_does_not_claim_success'] = True
                page.goto(verified_url)
                # Still on the verified task; explicit refresh removes old observation on failure.
                button = page.get_by_role('region', name='结果要求 1').get_by_role('button', name='查看证据 1', exact=True)
                button.click()
                dialog = page.get_by_role('dialog', name='效果证据详情')
                expect(dialog.get_by_role('heading', name='文件写入 · 观测到完成', exact=True)).to_be_visible()
                route = '**/v1/effect-evidence/*'
                page.route(route, lambda r: r.fulfill(status=503, json={'error': 'synthetic_unavailable'}))
                dialog.get_by_role('button', name='刷新证据', exact=True).click()
                expect(dialog.get_by_role('alert')).to_be_visible()
                expect(dialog.get_by_role('heading', name='文件写入 · 观测到完成', exact=True)).to_have_count(0)
                checks['refresh_failure_removes_old_success'] = True
                page.unroute(route)
                dialog.get_by_role('button', name='重试读取证据', exact=True).click()
                expect(dialog.get_by_role('heading', name='文件写入 · 观测到完成', exact=True)).to_be_visible()
                checks['explicit_read_retry_recovers_real_record'] = True
                wrong = records['failed'][2]
                page.route(route, lambda r: r.fulfill(json=wrong))
                dialog.get_by_role('button', name='刷新证据', exact=True).click()
                expect(dialog.get_by_role('alert')).to_be_visible()
                expect(dialog.get_by_role('heading', name='文件写入 · 观测到失败', exact=True)).to_have_count(0)
                checks['other_task_response_rejected'] = True
                page.unroute(route)
                dialog.get_by_role('button', name='重试读取证据', exact=True).click()
                expect(dialog.get_by_role('heading', name='文件写入 · 观测到完成', exact=True)).to_be_visible()
                page.set_viewport_size({'width': 375, 'height': 812})
                expect(dialog).to_be_visible()
                checks['evidence_dialog_fits_375'] = dialog.evaluate('el => {const r=el.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth && el.scrollWidth <= el.clientWidth;}')
                page.screenshot(path=str(args.out_dir / 'evidence-mobile.png'), full_page=True, animations='disabled')
                dialog.get_by_role('button', name='关闭证据详情', exact=True).click()
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.locator('.content').evaluate('el => el.scrollTop = 0')
                expect(page.get_by_role('heading', name='运行详情', exact=True)).to_be_in_viewport()
                page.screenshot(path=str(args.out_dir / 'results-desktop.png'), full_page=True, animations='disabled')
                # A failed summary cannot leave previously confirmed results visible.
                page.route('**/security-view?*', lambda r: r.fulfill(status=409, json={'error': 'task_activity_snapshot_changed'}))
                page.get_by_role('button', name='刷新详情', exact=True).click()
                expect(page.get_by_role('alert').filter(has_text='证据已变化')).to_be_visible()
                expect(page.get_by_role('region', name='结果要求 1')).to_have_count(0)
                checks['stale_snapshot_removes_prior_results'] = True
                page.unroute('**/security-view?*')
                page.get_by_role('button', name='刷新详情', exact=True).click()
                expect(page.get_by_role('region', name='结果要求 1').locator('.badge')).to_have_text('结果核验通过')
                checks['detail_refresh_recovers_current_snapshot'] = True
                checks['reading_results_has_no_domain_writes'] = all(route == '/v1/session/restore' for route in writes)
                checks['no_browser_errors'] = not errors
                assert all(checks.values()), {'failed': [k for k, v in checks.items() if not v], 'write_routes': writes}
                browser.close()
            h.stop()
            h.start()
            for kind, (task, completion, record) in records.items():
                assert h.api('/v1/tasks/' + task + '/completion') == completion
                if record:
                    assert h.api('/v1/effect-evidence/' + record['evidence']['effect_evidence_id']) == record
                checks[kind + '_signed_result_survives_server_restart'] = True
        finally:
            h.stop()
    payload = {'schema_version': 'siq.result-evidence-browser/v1', 'passed': all(checks.values()), 'checks': checks,
        'binary_sha256': hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope': 'Real isolated daemon, signed intents and decisions, real host file observations; synthetic writes, no native model or business output. Only errors and other-task response injected.',
        'completion_states': {key: {'status': value[1]['status'], 'reason_code': value[1]['reason_code']} for key, value in records.items()}}
    (args.out_dir / 'result.sanitized.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': payload['passed'], 'checks': len(checks)}))


if __name__ == '__main__':
    main()
