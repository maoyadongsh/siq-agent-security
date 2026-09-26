"""Environment pagination/coverage/selection UI: loopback fixtures, not production acceptance."""
import argparse
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright


def environment(n, name=None):
    return {'id': f'env-{n:02d}', 'tenant_id': 't-fixture', 'name': name or f'环境-{n}',
            'env_type': 'host', 'mode': 'discovery', 'risk_level': 'low', 'last_heartbeat_at': None}


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
            if '.' not in self.path.split('/')[-1]:
                self.path = '/index.html'
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=args.web))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state = {'page2_error': False}
    reads, errors, violations, uncovered, checks = [], [], [], [], []
    now = '2026-09-26T00:00:00Z'
    next_cursor = 'cursor-page-2'
    xss_name = '环境-51<img src=x onerror=window.__env_xss=1>'

    def list_headers(returned, truncated, cursor, total):
        headers = {'x-siq-list-limit': '50', 'x-siq-list-returned': str(returned),
                   'x-siq-list-truncated': '1' if truncated else '0',
                   'x-siq-list-total': str(total)}
        if cursor:
            headers['x-siq-next-cursor'] = cursor
        return headers

    def intercept(route):
        request = route.request
        url = urlparse(request.url)
        if url.hostname != '127.0.0.1' or url.port != server.server_port:
            violations.append('unexpected external network')
            route.abort()
            return
        if url.path == '/api/iam/api/v1/auth/refresh' and request.method == 'POST':
            route.fulfill(status=200, content_type='application/json',
                          body=json.dumps({'access_token': 'fixture-smoke-token'}))
            return
        if not url.path.startswith('/api/'):
            route.continue_()
            return
        if request.method != 'GET':
            violations.append(f'unexpected business write {request.method} {url.path}')
            route.abort()
            return
        code, body, headers = 200, {}, {}
        if url.path.endswith('/console-context'):
            body = {'schema_version': 'console-context/v1', 'evaluated_at': now,
                    'tenant': {'id': 'fixture', 'name': 'Fixture'}, 'actor': {'id': 'fixture', 'type': 'user'},
                    'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
                    'access': dict.fromkeys(['workspace', 'overview', 'agents', 'permissions', 'findings',
                                             'policies', 'changes', 'runtime_bindings', 'environments',
                                             'audit', 'settings'], True),
                    'actions': dict.fromkeys(['confirm_assets', 'manage_environment', 'enroll_devices',
                                              'manage_policy', 'propose_change', 'approve_change'], False)}
        elif url.path == '/api/v1/environments/access':
            body = {'schema_version': 'environment-onboarding-access/v1', 'can_create': True,
                    'can_enroll': True, 'can_scan': True, 'can_view_assets': True}
        elif url.path == '/api/v1/environments':
            cursor = parse_qs(url.query).get('cursor', [None])[0]
            reads.append(cursor)
            if cursor == next_cursor and state['page2_error']:
                route.fulfill(status=503, content_type='application/json', body='{"detail":"fixture unavailable"}')
                return
            if cursor == next_cursor:
                items, returned, truncated, cursor_out = [environment(51, xss_name)], 1, False, None
            else:
                items, returned, truncated, cursor_out = [environment(n) for n in range(1, 51)], 50, True, next_cursor
            headers = list_headers(returned, truncated, cursor_out, 77)
            body = items
        elif '/onboarding' in url.path:
            env_id = url.path.split('/')[-2]
            body = {'schema_version': 'environment-onboarding/v1', 'environment_id': env_id, 'evaluated_at': now,
                    'heartbeat_stale_seconds': 0, 'device_count': 0, 'devices': [], 'devices_truncated': False,
                    'evidence_count': 0, 'last_evidence_at': None, 'scans': [], 'scans_truncated': False}
        else:
            code, body = 404, {'detail': 'uncovered fixture'}
            uncovered.append(url.path)
        headers['content-type'] = 'application/json'
        route.fulfill(status=code, headers=headers,
                      body=json.dumps(body) if not isinstance(body, str) else body)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000}, service_workers='block')
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/*', intercept)
            page.goto(f'http://127.0.0.1:{server.server_port}/environments')
            coverage = page.locator('.environment-list-coverage')
            list_error = page.locator('.environment-list-error')
            list_note = page.locator('.environment-list-note')
            table = page.locator('tbody')
            expect(coverage).to_contain_text('已显示 50 条')
            expect(table.get_by_text('环境-50')).to_be_visible()
            expect(table.get_by_text('环境-51')).to_have_count(0)
            load_more = page.get_by_role('button', name='加载更多环境')
            expect(load_more).to_be_visible()
            assert page.url.endswith('/environments')
            checks.append('first_page_50_with_coverage_and_more_button')

            load_more.focus()
            assert load_more.evaluate('(e) => e.matches(":focus-visible")')
            load_more.press('Enter')
            expect(table.get_by_text('环境-51')).to_be_visible()
            expect(coverage).to_contain_text('已显示 51 条')
            expect(page.get_by_role('button', name='加载更多环境')).to_have_count(0)
            assert page.url.endswith('/environments')
            checks.append('explicit_click_loads_51_keyboard_focus_visible_url_stable')

            table.locator('tr', has_text='环境-51').get_by_role('button', name='查看接入进度').click()
            assert 'environment=env-51' in page.url
            expect(list_note).to_have_count(0)
            expect(table.get_by_text(xss_name)).to_be_visible()
            assert page.evaluate('window.__env_xss === undefined')
            checks.append('url_selection_mounts_panels_server_name_rendered_as_text')

            state['page2_error'] = True
            page.get_by_role('button', name='刷新环境列表').click()
            expect(table.get_by_text('环境-50')).to_be_visible()
            expect(list_note).to_contain_text('URL 指定的环境')
            page.get_by_role('button', name='加载更多环境').click()
            expect(list_error).to_contain_text('失败')
            expect(table.get_by_text('环境-50')).to_be_visible()
            expect(table.get_by_text('环境-51')).to_have_count(0)
            assert 'environment=env-51' in page.url
            checks.append('pagination_failure_keeps_rows_selection_and_shows_error')

            state['page2_error'] = False
            page.get_by_role('button', name='加载更多环境').click()
            expect(table.get_by_text('环境-51')).to_be_visible()
            expect(list_error).to_have_count(0)
            expect(coverage).to_contain_text('已显示 51 条')
            assert reads[-2:] == [next_cursor, next_cursor]
            checks.append('retry_same_cursor_recovers_without_stale_mixing')

            page.get_by_role('button', name='刷新环境列表').click()
            expect(coverage).to_contain_text('已显示 50 条')
            expect(table.get_by_text('环境-51')).to_have_count(0)
            assert reads[-1] is None
            assert 'environment=env-51' in page.url
            checks.append('refresh_rereads_page1_without_cursor_or_url_mixing')

            for width in (375, 768, 1440):
                page.set_viewport_size({'width': width, 'height': 1000})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.screenshot(path=str(args.out / f'environments-{width}.png'),
                                animations='disabled', full_page=False)
                page.locator('.environment-list-footer').scroll_into_view_if_needed()
                page.screenshot(path=str(args.out / f'environments-pagination-{width}.png'),
                                animations='disabled', full_page=False)
            checks.append('responsive_no_horizontal_overflow_screenshots_captured')

            assert not errors and not violations
            checks.append('no_write_request_no_external_network_no_uncaught_error')
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    report = {'scope': 'isolated-mock-only-not-production', 'checks': checks, 'errors': errors,
              'violations': violations, 'list_read_cursors': reads, 'uncovered_read_paths': uncovered}
    (args.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
