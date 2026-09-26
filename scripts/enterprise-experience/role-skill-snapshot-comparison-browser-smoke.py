"""Snapshot comparison UI: loopback synthetic fixtures only, not production acceptance."""
import argparse
import functools
import json
import re
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--framework', choices=('openclaw', 'hermes'), default='openclaw')
    args = parser.parse_args()
    hermes = args.framework == 'hermes'
    version = 'v2' if hermes else 'v1'
    args.out.mkdir(exist_ok=False)

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path.startswith('/agents/'):
                self.path = '/index.html'
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=args.web))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    now = '2026-09-25T00:00:00Z'
    state = {'agents': True, 'envs': True, 'cmp_error': 0, 'cmp_unavailable': False,
             'cmp_hold': False, 'cmp_empty': False}
    cmp_reads, delayed, errors, violations, checks = [], [], [], [], []
    roots = [{'kind': 'workspace_skills', 'locator_sha256': 'c' * 64},
             {'kind': 'project_agent_skills', 'locator_sha256': 'd' * 64}]
    if hermes:
        roots = [{'kind': 'profile_skills', 'locator_sha256': 'c' * 64}]

    def snapshot(obs_id, received_at):
        return {'observation_id': obs_id, 'observed_at': '2026-09-24T00:00:00Z',
                'received_at': received_at, 'environment_id': 'env-one', 'device_id': 'edge-one',
                'device_revoked': True, 'status': 'recorded_snapshot',
                'configuration': {'task_id': 'task-one', 'batch_digest': 'a' * 64,
                    'skill_source_roots': {'schema_version': f'enterprise-role-skill-roots/{version}',
                        'basis': 'hermes_profile_layout' if hermes else 'agent_workspace',
                        'status': 'layout_candidate' if hermes else 'declared', 'roots': roots},
                    'framework_source': {'schema_version': f'enterprise-framework-source/{version}',
                        'framework': args.framework, 'instance_key': 'b' * 64,
                        'config_sha256': 'e' * 64,
                        'evidence_id': '<script>window.__cmp_xss=1</script>'}}}

    def skill_obs(name='demo-skill'):
        return {'observation_id': 'smo-one', 'manifest_sha256': '1' * 64,
                'parser_version': 'enterprise-skill-manifest/v1', 'parse_status': 'parsed',
                'name': name, 'allowed_tools_present': False, 'declared_tools': [],
                'observed_at': '2026-09-25T01:00:00Z', 'batch_digest': '2' * 64}

    def comparison_body(obs_id, cursor):
        if state['cmp_unavailable']:
            return {'schema_version': f'enterprise-role-skill-snapshot-comparison/{version}',
                    'asset_id': 'agt_one', 'configuration_observation': snapshot(obs_id, now),
                    'status': 'snapshot_unavailable',
                    'comparison_basis': 'latest_skill_observations_against_saved_configuration',
                    'coverage': 'page_of_device_installations',
                    'items': [], 'next_cursor': None,
                    'runtime_status': 'unverified', 'effective_permissions': None}
        if cursor is None:
            items = [{'installation_id': 'ski_a', 'locator_sha256': 'f' * 64,
                      'relationship_status': 'historical_source_match',
                      'matched_sources': roots[:1], 'observation': skill_obs()}]
            next_cursor = 'ski_a'
        elif cursor == 'ski_a':
            items = [{'installation_id': 'ski_b', 'locator_sha256': 'f' * 64,
                      'relationship_status': 'unresolved', 'matched_sources': [], 'observation': None}]
            next_cursor = 'ski_b'
        else:
            items = [{'installation_id': 'ski_c', 'locator_sha256': 'f' * 64,
                      'relationship_status': 'outside_declared_sources',
                      'matched_sources': [], 'observation': skill_obs('outside-skill')}]
            next_cursor = None
        if state['cmp_empty']:
            items, next_cursor = [], None
        return {'schema_version': f'enterprise-role-skill-snapshot-comparison/{version}',
                'asset_id': 'agt_one', 'configuration_observation': snapshot(obs_id, now),
                'status': 'historical_comparison',
                'comparison_basis': 'latest_skill_observations_against_saved_configuration',
                'coverage': 'page_of_device_installations',
                'items': items, 'next_cursor': next_cursor,
                'runtime_status': 'unverified', 'effective_permissions': None}

    def intercept(route):
        request = route.request
        url = urlparse(request.url)
        if url.hostname != '127.0.0.1' or url.port != server.server_port or request.method != 'GET':
            violations.append('unexpected network/write')
            route.abort()
            return
        if not url.path.startswith('/api/'):
            route.continue_()
            return
        code, body = 200, {}
        if url.path.endswith('/console-context'):
            body = {'schema_version': 'console-context/v1', 'evaluated_at': now,
                    'tenant': {'id': 'fixture', 'name': 'Fixture'},
                    'actor': {'id': 'fixture', 'type': 'user'},
                    'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
                    'access': dict.fromkeys(['workspace', 'overview', 'agents', 'permissions',
                                            'findings', 'policies', 'changes', 'runtime_bindings',
                                            'environments', 'audit', 'settings'], True),
                    'actions': dict.fromkeys(['confirm_assets', 'manage_environment', 'enroll_devices',
                                             'manage_policy', 'propose_change', 'approve_change'], False)}
            body['access']['agents'] = state['agents']
            body['access']['environments'] = state['envs']
        elif url.path == '/api/v1/agents/agt_one':
            body = {'id': 'agt_one', 'name': '对照验收角色', 'framework': args.framework,
                    'status': 'candidate', 'updated_at': now, 'attributes': {}, 'evidence_ids': []}
        elif re.search(r'/configuration-observations/[^/]+/skill-installation-sources', url.path):
            m = re.search(r'/configuration-observations/([^/]+)/skill-installation-sources', url.path)
            obs_id = m.group(1)
            cursor = parse_qs(url.query).get('cursor', [None])[0]
            cmp_reads.append((obs_id, cursor))
            if state['cmp_hold']:
                delayed.append(route)
                return
            body = comparison_body(obs_id, cursor)
            if state['cmp_error']:
                code, body = state['cmp_error'], {'detail': 'fixture unavailable'}
        elif url.path.endswith('/configuration-observations'):
            body = {'schema_version': f'enterprise-role-configuration-history/{version}', 'asset_id': 'agt_one',
                    'coverage': 'recorded_configuration_observations', 'runtime_status': 'unverified',
                    'effective_permissions': None,
                    'items': [snapshot('rco_b', now), snapshot('rco_a', '2026-09-24T00:00:00Z')],
                    'next_cursor': None}
        elif url.path.endswith('/evidence'):
            body = []
        else:
            code, body = 404, {'detail': 'uncovered fixture'}
        route.fulfill(status=code, content_type='application/json', body=json.dumps(body))

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 1000}, service_workers='block')
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/*', intercept)
            page.goto(f'http://127.0.0.1:{server.server_port}/agents/agt_one')

            hist = page.get_by_role('region', name='角色配置历史', exact=True)
            expect(hist).to_contain_text('已保存配置快照')

            def open_row(index):
                """Expand the <details> row (idempotent) so its compare button is in the a11y tree."""
                details = hist.locator('details').nth(index)
                if details.evaluate('(e) => !e.open'):
                    details.locator('summary').click()
                return details.get_by_role('button', name='与最新技能观察对照')

            # 1. explicit-select-only: zero comparison requests before click
            assert not cmp_reads, f'comparison request before click: {cmp_reads}'
            expect(hist.get_by_role('button', name='与最新技能观察对照')).to_have_count(0)
            checks.append('explicit_select_only_zero_requests_before_click')

            # 2. keyboard + focus (must run before any mouse click so :focus-visible holds)
            summary = hist.locator('details').nth(0).locator('summary')
            summary.focus()
            summary.press('Enter')
            expect(hist.locator('details').nth(0)).to_have_attribute('open', '')
            assert summary.evaluate('(e) => e.matches(":focus-visible")')
            checks.append('keyboard_operable_visible_focus')

            # 3. click compare for rco_b, verify data
            open_row(0).click()
            cmp = page.get_by_role('region', name='快照与最新技能观察对照', exact=True)
            expect(cmp).to_contain_text('rco_b')
            expect(cmp).to_contain_text('ski_a')
            expect(cmp).to_contain_text('历史目录来源匹配')
            expect(cmp).to_contain_text('对照已保存配置与最新已记录技能观察')
            expect(cmp).to_contain_text('不是配置时刻的安装还原')
            if hermes:
                expect(hist).to_contain_text('Hermes')
                expect(hist).not_to_contain_text('OpenClaw')
                expect(hist).to_contain_text('已记录 profile 本地布局候选')
                expect(cmp).to_contain_text('不涵盖外部目录、受信任项目来源或加载优先级')
            assert cmp_reads[-1] == ('rco_b', None)
            checks.append('selected_snapshot_data_displayed')

            # 4. pagination: next page
            cmp.get_by_role('button', name='下一页对照').click()
            expect(cmp).to_contain_text('ski_b')
            expect(cmp).to_contain_text('来源未确认')
            assert cmp_reads[-1] == ('rco_b', 'ski_a')
            checks.append('pagination_next_page_same_snapshot')

            # 4. pagination failure: 503 on third page, retry same cursor
            state['cmp_error'] = 503
            cmp.get_by_role('button', name='下一页对照').click()
            expect(cmp.get_by_role('alert')).to_contain_text('快照技能对照读取失败')
            expect(cmp).to_contain_text('ski_b')
            assert cmp_reads[-1] == ('rco_b', 'ski_b')
            state['cmp_error'] = 0
            cmp.get_by_role('button', name='重试本页对照').click()
            expect(cmp).to_contain_text('ski_c')
            assert cmp_reads[-1] == ('rco_b', 'ski_b')
            checks.append('pagination_failure_retry_same_cursor_retains_prior_data')

            # 5. close, then A→B late response isolation
            cmp.get_by_role('button', name='关闭对照').click()
            expect(cmp).to_have_count(0)
            state['cmp_hold'] = True
            open_row(0).click()
            assert len(delayed) == 1
            state['cmp_hold'] = False
            cmp.get_by_role('button', name='关闭对照').click()
            open_row(1).click()
            expect(cmp).to_contain_text('rco_a')
            late = comparison_body('rco_b', None)
            late['items'][0]['observation']['name'] = 'late-success-marker'
            delayed.pop().fulfill(status=200, content_type='application/json',
                                  body=json.dumps(late))
            page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
            expect(cmp).to_contain_text('rco_a')
            expect(cmp).not_to_contain_text('late-success-marker')
            checks.append('a_to_b_late_success_cannot_override')

            # 6. unavailable no-fallback
            state['cmp_unavailable'] = True
            cmp.get_by_role('button', name='关闭对照').click()
            open_row(0).click()
            expect(cmp).to_contain_text('该快照不可对照')
            expect(cmp).to_contain_text('不回退最新配置')
            expect(cmp).not_to_contain_text('ski_a')
            state['cmp_unavailable'] = False
            checks.append('unavailable_no_fallback')

            # 7. empty page
            state['cmp_empty'] = True
            cmp.get_by_role('button', name='关闭对照').click()
            open_row(0).click()
            expect(cmp).to_contain_text('当前页没有安装记录')
            expect(cmp).to_contain_text('不代表设备未安装技能')
            state['cmp_empty'] = False
            checks.append('empty_page_not_absence')

            # 8. 403 / 404
            state['cmp_error'] = 403
            cmp.get_by_role('button', name='关闭对照').click()
            open_row(0).click()
            expect(cmp.get_by_role('alert')).to_contain_text('当前账号无权读取该快照的技能对照')
            state['cmp_error'] = 404
            cmp.get_by_role('button', name='重试本页对照').click()
            expect(cmp.get_by_role('alert')).to_contain_text('不可读取或不存在')
            expect(cmp).not_to_contain_text('fixture unavailable')
            state['cmp_error'] = 0
            checks.append('403_404_safe_messages_no_raw_body')

            # 9. close / refresh cleanup
            cmp.get_by_role('button', name='关闭对照').click()
            expect(cmp).to_have_count(0)
            hist.get_by_role('button', name='刷新配置历史').click()
            expect(cmp).to_have_count(0)
            checks.append('close_refresh_clears_selection')

            # 10. XSS plain text (payload lives in the history row evidence_id)
            open_row(0).click()
            expect(hist).to_contain_text('<script>window.__cmp_xss=1</script>')
            assert page.evaluate('window.__cmp_xss === undefined')
            expect(hist.locator('script')).to_have_count(0)
            expect(cmp.locator('script')).to_have_count(0)
            checks.append('xss_rendered_as_plain_text')

            # 11. responsive: 375 / 768 / 1280 no overflow (panel already open from step 10)
            expect(cmp).to_be_visible()
            expect(cmp).to_contain_text('demo-skill')
            cmp.locator('details summary').first.click()
            for width in (375, 768, 1280):
                page.set_viewport_size({'width': width, 'height': 1000})
                cmp.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                assert page.locator('.content').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
                assert cmp.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
                assert cmp.locator('.kv-list').evaluate_all(
                    '(els) => els.every(e => getComputedStyle(e).display === '
                    '(innerWidth <= 640 ? "block" : "grid"))')
                # The content scrolls inside the console, not the document.
                # Use a taller capture viewport so expanded details are not
                # clipped by that scroll container; width checks above use 1000px height.
                page.set_viewport_size({'width': width, 'height': 2200})
                cmp.scroll_into_view_if_needed()
                cmp.screenshot(path=str(args.out / f'snapshot-comparison-{width}.png'), animations='disabled')
            checks.append('responsive_no_overflow_375_768_1280')

            # 13. dual-permission-denial: zero requests
            state['agents'] = False
            state['envs'] = False
            count = len(cmp_reads)
            page.reload()
            expect(page.get_by_role('heading', name='当前账号无法访问此页面', exact=True)).to_be_visible()
            expect(page.get_by_role('region', name='角色配置历史', exact=True)).to_have_count(0)
            assert len(cmp_reads) == count
            checks.append('dual_permission_denial_zero_requests')

            # 14. no writes / external / uncaught errors
            assert not errors, f'uncaught errors: {errors}'
            assert not violations, f'violations: {violations}'
            checks.append('no_write_external_network_or_uncaught_error')

            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    report = {'scope': 'isolated-mock-only-not-production', 'framework': args.framework, 'checks': checks,
              'errors': errors, 'violations': violations, 'comparison_reads': cmp_reads}
    (args.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
