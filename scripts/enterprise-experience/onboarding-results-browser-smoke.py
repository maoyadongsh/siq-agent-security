"""Isolated result-first onboarding browser test; all API responses are fixtures."""
import argparse
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

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
            if self.path.startswith(('/environments', '/agents')):
                self.path = '/index.html'
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(args.web.resolve())))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state = {'mode': 'empty', 'calls': 0, 'writes': 0}
    held = []
    now = '2026-09-25T00:00:00Z'

    def progress(environment='env'):
        value = {'schema_version': 'environment-onboarding/v1', 'environment_id': environment, 'evaluated_at': now,
                     'heartbeat_stale_seconds': 300, 'device_count': 0, 'devices': [], 'devices_truncated': False,
                     'evidence_count': 0, 'last_evidence_at': None, 'scans': [], 'scans_truncated': False}
        if state['mode'] == 'complete':
            value.update(device_count=1, evidence_count=1, last_evidence_at=now, devices=[{
                'id': 'edge', 'device_identity': 'fixture-device', 'version': 'fixture', 'registered_at': now,
                'last_seen_at': now, 'status': 'online', 'connectors': ['openclaw']}], scans=[{
                'id': 'scan', 'connector': 'openclaw', 'status': 'delivered', 'created_at': now, 'expires_at': now,
                'device_identity': 'fixture-device', 'candidate_count': 1, 'evidence_count': 1}])
        return value

    def route(request):
        if request.request.method != 'GET':
            state['writes'] += 1
            request.fulfill(status=403, json={'detail': 'fixture denies mutations'})
            return
        path = urlparse(request.request.url).path
        body, status = [], 200
        if path.endswith('/console-context'):
            body = {'schema_version': 'console-context/v1', 'evaluated_at': now,
                        'tenant': {'id': 'fixture', 'name': 'Fixture'}, 'actor': {'id': 'fixture', 'type': 'user'},
                        'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
                        'access': dict.fromkeys(['workspace', 'overview', 'agents', 'permissions', 'findings',
                                              'policies', 'changes', 'runtime_bindings', 'environments', 'audit', 'settings'], True),
                        'actions': dict.fromkeys(['confirm_assets', 'manage_environment', 'enroll_devices',
                                               'manage_policy', 'propose_change', 'approve_change'], False)}
        elif path.endswith('/environments/access'):
            body = {'schema_version': 'environment-onboarding-access/v1', 'can_create': False,
                        'can_enroll': False, 'can_scan': False, 'can_view_assets': True}
        elif path.endswith('/environments'):
            body = [{'id': 'env', 'name': 'Fixture Linux', 'env_type': 'host', 'mode': 'discovery'},
                    {'id': 'env2', 'name': 'Second Linux', 'env_type': 'host', 'mode': 'discovery'}]
        elif path.endswith('/onboarding'):
            state['calls'] += 1
            if state['mode'] == 'hold' and '/env/' in path:
                held.append(request)
                return
            if state['mode'] == 'denied':
                status, body = 403, {'detail': 'forbidden'}
            else:
                body = progress(path.split('/')[-2])
        request.fulfill(status=status, json=body)

    checks = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 1000})
            errors = []
            page.on('pageerror', lambda _: errors.append('pageerror'))
            page.route('**/api/v1/**', route)
            page.clock.install()
            page.goto(f'http://127.0.0.1:{server.server_port}/environments?environment=env')
            result = page.get_by_label('自动接入结果')
            expect(result).to_contain_text('尚未收到设备注册')
            expect(page.get_by_label('设备可访问的控制面根地址')).not_to_be_visible()
            checks['result_first_manual_collapsed'] = True
            state['mode'] = 'complete'
            page.clock.run_for(15000)
            expect(result).to_contain_text('已完成发现')
            expect(result).to_contain_text('尚未自动纳管')
            checks['automatic_completion_readback'] = True
            toggle = page.get_by_role('checkbox', name='每 15 秒自动更新进度（仅查询，不提交任务）')
            toggle.uncheck()
            before = state['calls']
            page.clock.run_for(30000)
            assert state['calls'] == before
            checks['pause_no_poll'] = True
            toggle.check()
            page.evaluate("Object.defineProperty(document, 'visibilityState', {configurable: true, value: 'hidden'})")
            page.clock.run_for(30000)
            assert state['calls'] == before
            page.evaluate("Object.defineProperty(document, 'visibilityState', {configurable: true, value: 'visible'})")
            toggle.uncheck()
            checks['hidden_page_no_poll'] = True
            state['mode'] = 'denied'
            page.get_by_role('button', name='刷新接入进度', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('当前无法读取接入进度')
            expect(result).to_have_count(0)
            checks['failure_clears_success_not_zero'] = True
            state['mode'] = 'hold'
            toggle.check()
            page.clock.run_for(15000)
            expect(page.get_by_role('button', name='刷新接入进度', exact=True)).to_be_disabled()
            before = state['calls']
            assert len(held) == 1
            state['mode'] = 'complete'
            held.pop().fulfill(status=200, json=progress())
            expect(result).to_contain_text('已完成发现')
            assert state['calls'] == before
            summary = page.get_by_text('高级：手动接入、补扫与详细记录', exact=True)
            summary.focus()
            page.keyboard.press('Enter')
            expect(page.get_by_label('设备可访问的控制面根地址')).to_be_visible()
            page.keyboard.press('Enter')
            expect(page.get_by_label('设备可访问的控制面根地址')).not_to_be_visible()
            checks['pending_disabled_manual_keyboard'] = True
            page.screenshot(path=str(args.out_dir / 'desktop.png'), full_page=True, animations='disabled')
            page.set_viewport_size({'width': 375, 'height': 844})
            page.clock.run_for(500)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            page.screenshot(path=str(args.out_dir / 'mobile.png'), full_page=True, animations='disabled')
            result.scroll_into_view_if_needed()
            result.screenshot(path=str(args.out_dir / 'mobile-results.png'), animations='disabled')
            state['mode'] = 'hold'
            page.get_by_role('button', name='刷新接入进度', exact=True).click()
            expect(page.get_by_role('button', name='刷新接入进度', exact=True)).to_be_disabled()
            page.get_by_role('list', name='环境列表').get_by_role('listitem').filter(has_text='Second Linux').get_by_role('button').click()
            expect(page.get_by_role('heading', name='Second Linux · 接入进度')).to_be_visible()
            expect(result).to_contain_text('尚未收到设备注册')
            state['mode'] = 'complete'
            held.pop().fulfill(status=200, json=progress())
            page.clock.run_for(100)
            expect(result).to_contain_text('尚未收到设备注册')
            checks['environment_switch_discards_old_response'] = True
            assert state['writes'] == 0 and not errors
            checks['mobile_no_overflow_no_writes_or_pageerrors'] = True
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    result = {'passed': True, 'checks': checks, 'scope': 'mocked browser only', 'production_deployed': False,
                  'fixture_server_stopped': not worker.is_alive()}
    (args.out_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
