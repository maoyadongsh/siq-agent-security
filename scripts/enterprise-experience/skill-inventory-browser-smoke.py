#!/usr/bin/env python3
"""Isolated enterprise skill UI checks; mocked API, no live credentials or uploads."""
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
    parser.add_argument('--web', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=False)

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path.startswith('/agents'):
                self.path = '/index.html'
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(args.web.resolve())))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    mode = {'value': 'ok'}
    history = {'mode': 'ok', 'calls': 0}
    checks = {}
    context = {
        'schema_version': 'console-context/v1', 'evaluated_at': '2026-09-25T00:00:00Z',
        'tenant': {'id': 'fixture', 'name': 'Fixture'}, 'actor': {'id': 'fixture', 'type': 'user'},
        'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
        'access': dict.fromkeys(('workspace overview agents permissions findings policies changes '
                                'runtime_bindings environments audit settings').split(), True),
        'actions': dict.fromkeys(('confirm_assets manage_environment enroll_devices '
                                 'manage_policy propose_change approve_change').split(), False),
    }

    def item(key):
        return {
            'installation_id': 'ski_' + key, 'locator_sha256': 'a' * 64,
            'environment': {'id': 'env_a', 'name': 'Fixture Environment'},
            'device': {'id': 'edge_a', 'identity': 'fixture-device', 'revoked': True},
            'presence': 'observed_not_verified_current', 'relationship_status': 'unresolved',
            'effective_permissions': None,
            'latest_observation': {
                'observation_id': 'smo_' + key, 'manifest_sha256': 'b' * 64,
                'parser_version': 'enterprise-skill-manifest/v1', 'parse_status': 'parsed',
                'name': 'skill-' + key, 'allowed_tools_present': True, 'declared_tools': ['read_file'],
                'observed_at': '2026-09-25T00:00:00Z', 'batch_digest': 'c' * 64,
            },
        }

    def route(request):
        assert request.request.method == 'GET', 'unexpected browser write'
        url = urlparse(request.request.url)
        status, body = 200, []
        if url.path.endswith('/console-context'):
            body = context
        elif url.path.endswith('/observations'):
            history['calls'] += 1
            second = bool(parse_qs(url.query).get('cursor'))
            observation = item('a')['latest_observation'].copy()
            observation.update(observation_id='smo_old' if second else 'smo_new',
                               name='historical-old' if second else 'historical-new',
                               observed_at='2026-09-24T00:00:00Z' if second else '2026-09-25T00:00:00Z')
            body = {'schema_version': 'enterprise-skill-history/v1', 'installation_id': 'ski_a',
                    'items': [observation], 'next_cursor': None if second else 'smo_new'}
            if history['mode'] == 'fail':
                status, body = 503, {'detail': 'unavailable'}
            elif history['mode'] == 'denied':
                status, body = 403, {'detail': 'forbidden'}
        elif url.path.endswith('/skill-installations'):
            second = bool(parse_qs(url.query).get('cursor'))
            body = {'schema_version': 'enterprise-skill-inventory/v1',
                    'items': [item('b' if second else 'a')], 'next_cursor': None if second else 'ski_a'}
            if mode['value'] == 'denied':
                status, body = 403, {'detail': 'forbidden'}
            elif mode['value'] == 'empty':
                body.update(items=[], next_cursor=None)
            elif mode['value'] == 'invalid':
                body['items'][0]['effective_permissions'] = ['allowed']
        request.fulfill(status=status, json=body)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda _: errors.append('pageerror'))
            page.route('**/api/v1/**', route)
            page.goto(f'http://127.0.0.1:{server.server_port}/agents/skills')
            expect(page.get_by_role('heading', name='skill-a', exact=True)).to_be_visible()
            expect(page.get_by_text('已连接', exact=True)).to_be_visible()
            expect(page.get_by_text('尚未核验', exact=True)).to_be_visible()
            assert history['calls'] == 0
            summary = page.get_by_text('查看历史观察', exact=True)
            summary.focus()
            summary.press('Enter')
            expect(page.get_by_role('heading', name='historical-new', exact=False)).to_be_visible()
            checks['history_loaded_only_on_keyboard_expand'] = True
            history['mode'] = 'fail'
            page.get_by_role('button', name='加载更多技能历史', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('已保留此前读取的历史')
            expect(page.get_by_role('heading', name='historical-new', exact=False)).to_be_visible()
            history['mode'] = 'ok'
            page.get_by_role('button', name='重试技能历史').click()
            expect(page.get_by_role('heading', name='historical-old', exact=False)).to_be_visible()
            expect(page.get_by_role('alert')).to_have_count(0)
            checks['history_pagination_failure_and_retry'] = True
            page.get_by_role('heading', name='historical-old', exact=False).scroll_into_view_if_needed()
            page.screenshot(path=str(args.out_dir / 'history-desktop.png'), animations='disabled')
            page.set_viewport_size({'width': 375, 'height': 812})
            assert page.evaluate('document.querySelector(".content").scrollWidth <= document.querySelector(".content").clientWidth + 1')
            page.screenshot(path=str(args.out_dir / 'history-mobile.png'), animations='disabled')
            page.set_viewport_size({'width': 1440, 'height': 1000})
            summary.click()
            expect(page.get_by_role('heading', name='historical-new', exact=False)).to_have_count(0)
            summary.click()
            expect(page.get_by_role('heading', name='historical-new', exact=False)).to_be_visible()
            history['mode'] = 'denied'
            page.get_by_role('button', name='加载更多技能历史', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('历史读取失败')
            expect(page.get_by_role('heading', name='historical-new', exact=False)).to_have_count(0)
            checks['history_permission_denial_clears_rows'] = True
            summary.click()
            page.get_by_role('button', name='加载更多技能').click()
            expect(page.get_by_role('heading', name='skill-b', exact=True)).to_be_visible()
            page.get_by_label('搜索已加载的技能、环境或设备').fill('skill-b')
            expect(page.get_by_role('heading', name='skill-a', exact=True)).to_have_count(0)
            checks['pagination_and_loaded_search'] = True
            page.screenshot(path=str(args.out_dir / 'desktop.png'))
            mode['value'] = 'denied'
            page.get_by_role('button', name='刷新技能清单').click()
            expect(page.get_by_role('alert')).to_contain_text('缺少资产或环境读取权限')
            expect(page.get_by_role('heading', name='skill-b', exact=True)).to_have_count(0)
            mode['value'] = 'ok'
            page.get_by_role('button', name='重试读取技能').click()
            expect(page.get_by_role('heading', name='skill-a', exact=True)).to_be_visible()
            checks['refresh_clears_stale_data_and_retry'] = True
            mode['value'] = 'denied'
            page.get_by_role('button', name='加载更多技能').click()
            expect(page.get_by_role('alert')).to_contain_text('缺少资产或环境读取权限')
            expect(page.get_by_role('heading', name='skill-a', exact=True)).to_have_count(0)
            checks['permission_revocation_clears_loaded_records'] = True
            mode['value'] = 'invalid'
            page.get_by_role('button', name='刷新技能清单').click()
            expect(page.get_by_role('alert')).to_contain_text('读取失败')
            checks['invalid_effective_claim_rejected'] = True
            mode['value'] = 'empty'
            page.get_by_role('button', name='刷新技能清单').click()
            expect(page.get_by_text('这不证明设备没有安装技能', exact=False)).to_be_visible()
            checks['empty_not_absence'] = True
            mode['value'] = 'ok'
            page.set_viewport_size({'width': 375, 'height': 812})
            page.get_by_role('button', name='刷新技能清单').click()
            expect(page.get_by_role('heading', name='skill-a', exact=True)).to_be_visible()
            page.get_by_text('查看溯源摘要', exact=True).focus()
            page.get_by_text('查看溯源摘要', exact=True).press('Enter')
            expect(page.get_by_text('位置摘要：', exact=False)).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert page.evaluate(
                'Array.from(document.querySelectorAll("main, section, article"))'
                '.every(e => e.scrollWidth <= e.clientWidth + 1)'
            ), 'nested horizontal overflow'
            page.screenshot(path=str(args.out_dir / 'mobile.png'), full_page=True)
            checks['mobile_375_no_horizontal_overflow'] = True
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    result = {'passed': True, 'checks': checks, 'scope': 'mocked API browser only',
              'production_deployed': False, 'fixture_server_stopped': not worker.is_alive()}
    (args.out_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
