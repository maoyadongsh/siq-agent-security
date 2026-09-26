"""Configuration history UI: loopback synthetic fixtures only, not production acceptance."""
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
    args = parser.parse_args()
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
    state = {'allowed': True, 'error': False, 'hold': False, 'empty': False}
    reads, delayed, errors, violations, checks = [], [], [], [], []
    now = '2026-09-25T00:00:00Z'

    def snapshot(identifier, missing=False):
        return {'observation_id': identifier, 'observed_at': '2026-09-24T00:00:00Z', 'received_at': now,
                'environment_id': 'env-one', 'device_id': 'edge-one', 'device_revoked': True,
                'status': 'snapshot_unavailable' if missing else 'recorded_snapshot',
                'configuration': None if missing else {'task_id': 'task-one', 'batch_digest': 'a' * 64,
                    'skill_source_roots': None, 'framework_source': {
                        'schema_version': 'enterprise-framework-source/v1', 'framework': 'openclaw',
                        'instance_key': 'b' * 64, 'config_sha256': 'c' * 64,
                        'evidence_id': '<script>window.__history_xss=1</script>'}}}

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
        elif url.path == '/api/v1/agents/agt_one':
            body = {'id': 'agt_one', 'name': '历史验收角色', 'framework': 'openclaw',
                    'status': 'candidate', 'updated_at': now, 'attributes': {}, 'evidence_ids': []}
        elif url.path.endswith('/configuration-observations'):
            cursor = parse_qs(url.query).get('cursor', [None])[0]
            reads.append(cursor)
            if state['hold']:
                delayed.append(route)
                return
            body = {'schema_version': 'enterprise-role-configuration-history/v1', 'asset_id': 'agt_one',
                    'coverage': 'recorded_configuration_observations', 'runtime_status': 'unverified',
                    'effective_permissions': None,
                    'items': [snapshot('rco_x', True)] if cursor else [snapshot('rco_z')],
                    'next_cursor': None if cursor else 'rco_z'}
            if state['empty']:
                body.update(items=[], next_cursor=None)
            if state['error']:
                code, body = 503, {'detail': 'fixture unavailable'}
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
            state['hold'] = True
            page.goto(f'http://127.0.0.1:{server.server_port}/agents/agt_one')
            panel = page.get_by_role('region', name='角色配置历史', exact=True)
            expect(panel.get_by_role('status')).to_contain_text('正在读取配置历史')
            expect(panel).not_to_contain_text('本页 0')
            assert len(delayed) == 1
            state['hold'] = False
            panel.get_by_role('button', name='刷新配置历史').click()
            expect(panel).to_contain_text('已保存配置快照')
            delayed.pop().fulfill(status=503, content_type='application/json', body='{"detail":"stale"}')
            page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
            expect(panel.get_by_role('alert')).to_have_count(0)
            checks.append('loading_without_zero_and_stale_failure_ignored')
            summary = panel.locator('summary')
            summary.focus()
            summary.press('Enter')
            expect(panel.locator('details')).to_have_attribute('open', '')
            assert summary.evaluate('(e) => e.matches(":focus-visible")')
            expect(panel).to_contain_text('<script>window.__history_xss=1</script>')
            assert page.evaluate('window.__history_xss === undefined')
            expect(panel).to_contain_text('本快照未记录，不从最新配置补填')
            expect(panel).to_contain_text('已吊销，仅保留历史')
            expect(panel).to_contain_text('不是原批重新验签证明')
            checks.append('keyboard_plain_text_missing_roots_historical_boundaries')
            for width in (375, 768, 1280):
                page.set_viewport_size({'width': width, 'height': 1000})
                panel.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                assert page.locator('.content').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
                assert panel.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
                panel.screenshot(path=str(args.out / f'configuration-history-{width}.png'), animations='disabled')
            checks.append('responsive_expanded_evidence_no_overflow')
            state['error'] = True
            panel.get_by_role('button', name='下一页配置历史').click()
            expect(panel.get_by_role('alert')).to_contain_text('读取失败')
            expect(panel).not_to_contain_text('已保存配置快照')
            state['error'] = False
            panel.get_by_role('button', name='重试本页配置历史').click()
            expect(panel).to_contain_text('配置快照不可核对')
            assert reads[-2:] == ['rco_z', 'rco_z']
            panel.get_by_role('button', name='上一页配置历史').click()
            expect(panel).to_contain_text('已保存配置快照')
            checks.append('pagination_retry_same_cursor_previous_no_mixing')
            state['empty'] = True
            panel.get_by_role('button', name='刷新配置历史').click()
            expect(panel).to_contain_text('当前页无可读配置历史')
            expect(panel).to_contain_text('不代表未安装智能体或技能')
            checks.append('empty_is_not_absence_or_protection')
            state['allowed'] = False
            count = len(reads)
            page.reload()
            expect(page.get_by_role('heading', name='历史验收角色', exact=True)).to_be_visible()
            expect(panel).to_have_count(0)
            assert len(reads) == count
            checks.append('permission_denial_prevents_history_requests')
            assert not errors and not violations
            checks.append('no_write_external_network_or_uncaught_error')
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    report = {'scope': 'isolated-mock-only-not-production', 'checks': checks, 'errors': errors,
              'violations': violations, 'read_cursors': reads}
    (args.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
