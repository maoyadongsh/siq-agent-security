#!/usr/bin/env python3
"""Real paired daemon + runtime capture + output UI, synthetic content only."""
import argparse
import importlib.util
import json
import re
import shutil
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('fixture', ROOT / 'scripts/validate-intent-v2-hermes.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    args.binary = args.binary.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=False)
    args.installer_managed_profile = True
    checks = {}
    with tempfile.TemporaryDirectory(prefix='siq-output-e153-') as raw:
        args.hermes_cli = Path(raw) / 'unused-hermes-cli'
        h = fixture.Harness(Path(raw), args)
        shutil.copy2(args.binary, h.binary)
        try:
            h.start()
            target = next(i for i in h.api('/v1/adapter/instances?platform=hermes')['instances'] if i['active'])
            agent = 'hri-' + target['instance_id'][3:]
            skill = Path(raw) / 'output-skill'
            skill.mkdir()
            (skill / 'SKILL.md').write_text('---\nname: output-fixture\ndescription: Read synthetic output.\nallowed-tools: read_file\n---\nRead an approved fixture.\n')
            admission = h.api('/v1/admit', {'path': str(skill)})['admission']
            grant = h.api('/v1/grants', {'admission_id': admission['admission_id'], 'platform': 'hermes',
                'subject_id': agent, 'subject_type': 'agent_instance', 'redact_secrets': True})
            grant_path = '/v1/grants/' + grant['grant']['grant_id']
            def action(name, **extra):
                nonlocal grant
                response = h.api(grant_path + '/' + name,
                    {'expected_revision': grant['state_revision'], 'actor_id': 'fixture-human', **extra})
                grant = h.api(grant_path)
                return response
            action('patch-desired', tools=['read_file'], filesystem={'read_only': [str(h.workspace)], 'read_write': []})
            for index, conflict in enumerate(grant['grant']['overlap_conflicts']):
                if conflict['resolution'] == 'unresolved':
                    action('resolve-overlap', index=index)
            challenge = action('challenge')['challenge']
            action('approve', challenge_id=challenge['challenge_id'], nonce=challenge['nonce'])
            action('deploy')
            issued = h.api('/v1/runtime-identities', {'schema_version': 'local-runtime-identity-create/v1',
                'instance_id': target['instance_id'], 'grant_id': grant['grant']['grant_id'],
                'expected_grant_revision': grant['state_revision'], 'actor_id': 'fixture-human', 'session_ttl_seconds': 600}, expected=201)
            credential = Path(issued['credential_path']).read_text().strip()
            session = 'output-ui-session'
            binding = h.api('/v1/runtime-sessions', {'schema_version': 'local-runtime-session-enroll/v1', 'session_id': session}, token=credential)
            decision = h.api('/v1/decide', {'platform': 'hermes', 'agent_id': agent, 'session_id': session,
                'tool': 'read_file', 'params': {'path': str(h.workspace / 'company-a/report.txt')}}, token=credential)
            assert decision['action'] == 'allow'
            binding = next(item['binding'] for item in h.api('/v1/task-activities')['items']
                           if item['binding'] and item['binding']['session_id'] == session)
            pairing = h.command([str(h.binary), 'pair', '--port', h.endpoint.rsplit(':', 1)[1]])
            code = re.search(r'\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b', pairing).group()
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 1000}, locale='zh-CN')
                errors, reads = [], []
                page.on('pageerror', lambda _: errors.append('pageerror'))
                page.on('request', lambda r: reads.append(r.url) if '/outputs/read?' in r.url else None)
                page.goto(h.endpoint + '/activities')
                page.get_by_label('配对码', exact=True).fill(code)
                page.get_by_role('button', name='建立管理会话', exact=True).click()
                expect(page.get_by_role('heading', name='运行记录', exact=True)).to_be_visible()
                page.goto(h.endpoint + '/activities?task_id=' + binding['task_id'])
                page.get_by_role('link', name='查看活动记录', exact=True).click()
                panel = page.get_by_role('region', name='本次运行的已采集输出', exact=True)
                expect(panel.get_by_text('输出内容保存尚未开启。', exact=False)).to_be_visible()
                checks['disabled_has_clear_next_step'] = True
                h.api('/v1/raw-task-content/activation', {'schema_version': 'local-raw-task-content-activate/v1',
                    'actor_id': 'fixture-human', 'retention_seconds': 3600, 'budget_bytes': 64 << 20}, expected=201)
                h.api('/v1/raw-task-content/grants', {'schema_version': 'local-raw-task-content-grant-create/v1',
                    'task_id': binding['task_id'], 'kinds': ['output'], 'actor_id': 'fixture-human',
                    'duration_seconds': 600, 'retention_seconds': 3600, 'max_plaintext_bytes': 4096}, expected=201)
                panel.get_by_role('button', name='刷新输出列表').click()
                expect(panel.get_by_text('本次运行暂无可关联的已采集输出。', exact=False)).to_be_visible()
                checks['authorization_does_not_invent_output'] = True
                marker = 'SYNTHETIC_OUTPUT <script>window.outputInjected=true</script>'
                captured = h.api('/v1/raw-task-content/native-captures', {'schema_version': 'local-raw-task-content-native-capture/v1',
                    'platform': 'hermes', 'agent_id': agent, 'session_id': session, 'kind': 'output',
                    'fields': [{'path': '/result', 'value': marker, 'secret': False},
                               {'path': '/api_key', 'value': 'synthetic-secret-never-display', 'secret': True}]}, token=credential, expected=201)
                panel.get_by_role('button', name='刷新输出列表').click()
                button = panel.get_by_role('button', name='查看输出 1', exact=True)
                expect(button).to_be_visible()
                assert len(reads) == 0 and marker not in page.locator('body').inner_text()
                checks['metadata_does_not_fetch_plaintext'] = True
                button.click()
                dialog = page.get_by_role('dialog', name='查看已采集输出', exact=True)
                expect(dialog.get_by_role('button', name='确认查看输出')).to_be_disabled()
                page.set_viewport_size({'width': 375, 'height': 812})
                assert dialog.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
                page.screenshot(path=str(args.out_dir / 'confirm-mobile.png'), full_page=True, animations='disabled')
                dialog.get_by_role('checkbox').check()
                dialog.get_by_role('button', name='确认查看输出').click()
                expect(dialog.get_by_role('region', name='本次运行输出正文')).to_contain_text(marker)
                assert len(reads) == 1 and not page.evaluate('Boolean(window.outputInjected)')
                assert 'synthetic-secret-never-display' not in page.locator('body').inner_text()
                checks['explicit_read_escaped_text_and_secret_omission'] = True
                page.screenshot(path=str(args.out_dir / 'output-mobile.png'), full_page=True, animations='disabled')
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.screenshot(path=str(args.out_dir / 'output-desktop.png'), full_page=True, animations='disabled')
                page.keyboard.press('Escape')
                expect(dialog).to_have_count(0)
                assert marker not in page.locator('body').inner_text()
                expect(button).to_be_focused()
                checks['close_clears_and_restores_focus'] = True
                page.reload()
                expect(button).to_be_visible()
                assert len(reads) == 1 and marker not in page.locator('body').inner_text()
                checks['reload_only_lists_metadata'] = True
                # Let the real response arrive after closing the reader. No
                # synthetic success body is supplied and no second write runs.
                page.evaluate('''() => {
                    window.outputOriginalFetch = window.fetch;
                    window.fetch = (...args) => window.outputOriginalFetch(...args).then(response =>
                        String(args[0]).includes('/outputs/read?')
                          ? new Promise(resolve => setTimeout(() => resolve(response), 700)) : response);
                }''')
                button.click()
                dialog.get_by_role('checkbox').check()
                with page.expect_response(lambda r: '/outputs/read?' in r.url):
                    dialog.get_by_role('button', name='确认查看输出').click()
                dialog.get_by_role('button', name='关闭并清除').click()
                page.wait_for_timeout(850)
                assert marker not in page.locator('body').inner_text()
                page.evaluate('window.fetch = window.outputOriginalFetch; delete window.outputOriginalFetch')
                checks['late_content_response_cannot_reopen_closed_reader'] = True
                # Simulate transport failure, never fake a successful content response.
                page.route('**/outputs/read?*', lambda route: route.abort())
                button.click()
                dialog.get_by_role('checkbox').check()
                dialog.get_by_role('button', name='确认查看输出').click()
                expect(dialog.get_by_role('alert')).to_contain_text('暂时无法核验')
                page.unroute('**/outputs/read?*')
                dialog.get_by_role('checkbox').check()
                dialog.get_by_role('button', name='确认查看输出').click()
                expect(dialog.get_by_role('region', name='本次运行输出正文')).to_contain_text(marker)
                checks['read_failure_can_explicitly_retry'] = True
                dialog.get_by_role('button', name='关闭并清除').click()
                h.api('/v1/decide', {'platform': 'hermes', 'agent_id': agent, 'session_id': session,
                    'tool': 'read_file', 'params': {'path': str(h.workspace / 'company-a/report.txt')}}, token=credential)
                panel.get_by_role('button', name='刷新输出列表').click()
                expect(panel.get_by_role('alert')).to_contain_text('运行记录或输出已变化')
                page.get_by_role('button', name='刷新详情', exact=True).click()
                expect(button).to_be_visible()
                checks['stale_snapshot_requires_detail_refresh'] = True
                h.api('/v1/raw-task-content/records/' + captured['record_id'] + '/delete',
                    {'schema_version': 'local-raw-task-content-record-delete/v1', 'task_id': binding['task_id'],
                     'confirm_record_id': captured['record_id']})
                button.click()
                dialog.get_by_role('checkbox').check()
                dialog.get_by_role('button', name='确认查看输出').click()
                expect(dialog.get_by_role('alert')).to_contain_text('已不存在')
                dialog.get_by_role('button', name='关闭并清除').click()
                panel.get_by_role('button', name='刷新输出列表').click()
                expect(panel.get_by_text('本次运行暂无可关联的已采集输出。', exact=False)).to_be_visible()
                checks['deleted_record_not_revealed_from_stale_list'] = True
                assert not errors
                assert marker not in page.evaluate('JSON.stringify({...localStorage,...sessionStorage})')
                checks['no_script_errors_or_plaintext_storage'] = True
                browser.close()
        finally:
            h.stop()
    (args.out_dir / 'result.json').write_text(json.dumps({'passed': True, 'checks': checks,
        'scope': 'real local management/runtime HTTP + UI; synthetic capture, no Hermes host process'}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'checks': len(checks)}))


if __name__ == '__main__':
    main()
