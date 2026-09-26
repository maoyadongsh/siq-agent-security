"""Role/skill source UI, synthetic responses only; not production acceptance."""
import argparse
import functools
import json
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
    state = {'allowed': True, 'error': False, 'unavailable': False, 'hold': False}
    reads, delayed, errors, violations, checks = [], [], [], [], []
    source = {'schema_version': f'enterprise-framework-source-view/{version}', 'asset_id': 'agt-one',
              'status': 'historical_reported_source', 'runtime_status': 'unverified',
              'skill_relationship_status': 'unresolved', 'effective_permissions': None,
              'source': {'framework': args.framework, 'instance_key': 'a' * 64, 'config_sha256': 'b' * 64,
                         'environment_id': 'env-one', 'device_id': 'edge-one', 'device_revoked': True,
                         'evidence_id': 'ev-one', 'observation_id': 'obs-one', 'observed_at': now}}
    roots = [{'kind': 'workspace_skills', 'locator_sha256': 'c' * 64},
             {'kind': 'project_agent_skills', 'locator_sha256': 'd' * 64}]
    if hermes:
        roots = [{'kind': 'profile_skills', 'locator_sha256': 'c' * 64}]

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
                    'tenant': {'id': 'fixture', 'name': 'Fixture'}, 'actor': {'id': 'fixture', 'type': 'user'},
                    'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
                    'access': dict.fromkeys(['workspace', 'overview', 'agents', 'permissions', 'findings',
                                            'policies', 'changes', 'runtime_bindings', 'environments',
                                            'audit', 'settings'], True),
                    'actions': dict.fromkeys(['confirm_assets', 'manage_environment', 'enroll_devices',
                                             'manage_policy', 'propose_change', 'approve_change'], False)}
            body['access']['environments'] = state['allowed']
        elif url.path == '/api/v1/agents/agt-one':
            body = {'id': 'agt-one', 'name': 'Fixture role', 'framework': args.framework,
                    'status': 'candidate', 'updated_at': now, 'attributes': {}, 'evidence_ids': []}
        elif url.path.endswith('/framework-source'):
            body = source
        elif url.path.endswith('/skill-installation-sources'):
            cursor = parse_qs(url.query).get('cursor', [None])[0]
            reads.append(cursor)
            if state['hold']:
                delayed.append(route)
                return
            body = {'schema_version': f'enterprise-role-skill-sources-view/{version}', 'asset_id': 'agt-one',
                    'status': 'historical_comparison', 'framework_source': source,
                    'declared_roots': {'schema_version': f'enterprise-role-skill-roots/{version}',
                                       'status': 'layout_candidate' if hermes else 'declared',
                                       'basis': 'hermes_profile_layout' if hermes else 'agent_workspace',
                                       'roots': roots},
                    'coverage': 'page_of_device_installations', 'runtime_status': 'unverified',
                    'effective_permissions': None, 'items': [], 'next_cursor': None if cursor else 'ski_one'}
            body['items'] = [{'installation_id': 'ski_two' if cursor else 'ski_one', 'locator_sha256': 'e' * 64,
                              'relationship_status': 'unresolved' if cursor else 'historical_source_match',
                              'matched_sources': [] if cursor else roots[:1], 'observation': None if cursor else {
                                  'observation_id': 'smo-one', 'manifest_sha256': 'f' * 64,
                                  'batch_digest': '1' * 64, 'parser_version': 'enterprise-skill-manifest/v1',
                                  'parse_status': 'parsed', 'name': '<script>bad()</script>',
                                  'allowed_tools_present': False, 'declared_tools': [], 'observed_at': now}}]
            if state['unavailable']:
                body.update(status='source_unavailable', declared_roots=None, items=[], next_cursor=None)
            if state['error']:
                code, body = 503, {'detail': 'fixture unavailable'}
        elif url.path.endswith('/evidence'):
            body = []
        else:
            code, body = 404, {'detail': 'uncovered fixture'}
        # Explicit content type also covers empty arrays in Playwright fixtures.
        route.fulfill(status=code, content_type='application/json', body=json.dumps(body))

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 1000})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/*', intercept)
            page.goto(f'http://127.0.0.1:{server.server_port}/agents/agt-one')
            panel = page.get_by_role('region', name='角色与技能安装来源', exact=True)
            expect(panel).to_contain_text('历史目录来源匹配')
            expect(panel).to_contain_text('已吊销，仅保留历史')
            expect(panel).to_contain_text('不证明当前存在')
            if hermes:
                expect(panel).to_contain_text('Hermes profile 本地技能布局候选')
                expect(panel).to_contain_text('不涵盖外部目录、受信任项目来源或实际加载')
                expect(panel).not_to_contain_text('两个已声明的工作区')
            summary = panel.locator('summary')
            summary.focus()
            summary.press('Enter')
            expect(panel.locator('details')).to_have_attribute('open', '')
            assert summary.evaluate('(e) => e.matches(":focus-visible")')
            assert panel.locator('script').count() == 0
            expect(summary).to_contain_text('<script>bad()</script>')
            checks.append('keyboard_text_only_and_historical_semantics')
            for width in (375, 768, 1280):
                page.set_viewport_size({'width': width, 'height': 1000})
                panel.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                assert page.locator('.content').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
                page.screenshot(path=str(args.out / f'role-sources-{width}.png'), animations='disabled')
            checks.append('responsive_no_overflow')
            state['error'] = True
            panel.get_by_role('button', name='下一页安装来源').click()
            expect(panel.get_by_role('alert')).to_contain_text('读取失败')
            assert reads[-1] == 'ski_one'
            state['error'] = False
            panel.get_by_role('button', name='重试本页来源').click()
            expect(panel).to_contain_text('来源未确认')
            expect(panel).not_to_contain_text('历史目录来源匹配')
            assert reads[-1] == 'ski_one'
            panel.get_by_role('button', name='上一页安装来源').click()
            expect(panel).to_contain_text('历史目录来源匹配')
            checks.append('pagination_retains_cursor_and_no_mixed_pages')
            state['error'] = True
            panel.get_by_role('button', name='重新核对技能来源').click()
            expect(panel.get_by_role('alert')).to_contain_text('读取失败')
            expect(panel).not_to_contain_text('历史目录来源匹配')
            state.update(error=False, unavailable=True)
            panel.get_by_role('button', name='重新核对技能来源').click()
            expect(panel).to_contain_text('不代表未安装技能')
            checks.append('error_and_unavailable_not_empty')
            state.update(unavailable=False, hold=True)
            panel.get_by_role('button', name='重新核对技能来源').click()
            expect(panel.get_by_role('status')).to_contain_text('正在核对')
            assert len(delayed) == 1
            state['hold'] = False
            panel.get_by_role('button', name='重新核对技能来源').click()
            expect(panel).to_contain_text('历史目录来源匹配')
            delayed.pop().fulfill(status=503, json={'detail': 'stale failure'})
            page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
            expect(panel.get_by_role('alert')).to_have_count(0)
            checks.append('stale_failure_cannot_override_refresh')
            state['allowed'] = False
            count = len(reads)
            page.reload()
            expect(page.get_by_role('heading', name='Fixture role', exact=True)).to_be_visible()
            expect(panel).to_have_count(0)
            assert len(reads) == count
            checks.append('permission_filter_prevents_requests')
            assert not errors and not violations
            checks.append('no_write_external_network_or_uncaught_error')
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    report = {'scope': 'isolated-mock-only-not-production', 'framework': args.framework, 'checks': checks,
              'errors': errors, 'violations': violations, 'read_cursors': reads}
    (args.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
