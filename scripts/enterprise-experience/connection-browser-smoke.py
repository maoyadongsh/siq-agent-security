"""Mocked enterprise connection UI; no OpenShell process or real backend invoked."""
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
            if self.path.startswith('/environments'):
                self.path = '/index.html'
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(args.web.resolve())))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state = {'mode': 'hold', 'calls': 0}
    held = []
    checks = {}
    fixture = {'schema_version': 'enterprise-openshell-connection/v1', 'environment_id': 'env',
                   'scope': 'control_plane_connection', 'status': 'handshake_verified', 'ready_for_deployment': False,
                   'version_compatibility': 'unverified', 'credential_scope': 'unverified', 'execution_evidence': 'none',
                   'endpoint_fingerprint': 'a' * 64, 'gateway_name_sha256': 'b' * 64, 'cli_version': '0.0.104',
                   'gateway_version': '0.0.104', 'configuration_capabilities': {
                       'network.dynamic_update': True, 'enforcement_mode.block': True}}

    def route(request):
        path = urlparse(request.request.url).path
        assert request.request.method == 'GET', 'unexpected mutation'
        body, status = [], 200
        if path.endswith('/console-context'):
            body = {'schema_version': 'console-context/v1', 'evaluated_at': '2026-09-25T00:00:00Z',
                        'tenant': {'id': 'fixture', 'name': 'Fixture'}, 'actor': {'id': 'fixture', 'type': 'user'},
                        'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
                        'access': dict.fromkeys(['workspace', 'overview', 'agents', 'permissions', 'findings',
                                              'policies', 'changes', 'runtime_bindings', 'environments', 'audit', 'settings'], True),
                        'actions': dict.fromkeys(['confirm_assets', 'manage_environment', 'enroll_devices',
                                               'manage_policy', 'propose_change', 'approve_change'], False)}
        elif path.endswith('/environments'):
            body = [{'id': 'env', 'name': 'Fixture DGX', 'env_type': 'host', 'mode': 'discovery'}]
        elif path.endswith('/environments/access'):
            body = {'schema_version': 'environment-onboarding-access/v1', 'can_create': False, 'can_enroll': False,
                        'can_scan': False, 'can_view_assets': True}
        elif path.endswith('/onboarding'):
            body = {'schema_version': 'environment-onboarding/v1', 'environment_id': 'env',
                        'evaluated_at': '2026-09-25T00:00:00Z', 'heartbeat_stale_seconds': 300, 'device_count': 0,
                        'devices': [], 'devices_truncated': False, 'evidence_count': 0, 'last_evidence_at': None,
                        'scans': [], 'scans_truncated': False}
        elif path.endswith('/openshell-connection'):
            state['calls'] += 1
            if state['mode'] == 'hold':
                held.append(request)
                return
            if state['mode'] == 'denied':
                status, body = 403, {'detail': 'forbidden'}
            elif state['mode'] == 'mismatch':
                body = {**fixture, 'environment_id': 'foreign'}
            else:
                body = fixture
        request.fulfill(status=status, json=body)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 1000})
            errors = []
            page.on('pageerror', lambda _: errors.append('pageerror'))
            page.route('**/api/v1/**', route)
            page.goto(f'http://127.0.0.1:{server.server_port}/environments?environment=env')
            summary = page.get_by_text('高级诊断：OpenShell 控制面连接', exact=True)
            expect(summary).to_be_visible()
            panel = summary.locator('..')
            assert state['calls'] == 0
            summary.focus()
            page.keyboard.press('Enter')
            button = panel.get_by_role('button', name='检查 OpenShell 连接', exact=True)
            expect(button).to_be_visible()
            assert state['calls'] == 0
            button.click()
            expect(panel.get_by_role('button')).to_be_disabled()
            page.wait_for_timeout(100)
            assert state['calls'] == 1 and len(held) == 1
            held.pop().fulfill(status=200, json=fixture)
            expect(panel).to_contain_text('本次握手已确认')
            expect(panel).to_contain_text('不能据此开始部署')
            checks['manual_only_single_request_and_honest_result'] = True
            panel.get_by_text('查看连接证据摘要', exact=True).click()
            panel.screenshot(path=str(args.out_dir / 'desktop.png'), animations='disabled')
            page.set_viewport_size({'width': 375, 'height': 844})
            panel.scroll_into_view_if_needed()
            assert panel.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
            page.screenshot(path=str(args.out_dir / 'mobile.png'), animations='disabled')
            checks['keyboard_and_mobile_evidence'] = True
            for mode, text in [('denied', '缺少环境管理或策略读取权限'), ('mismatch', '未获得可核验')]:
                state['mode'] = mode
                panel.get_by_role('button').click()
                expect(panel).to_contain_text(text)
                expect(panel).not_to_contain_text('本次握手已确认')
                checks[mode] = True
            state['mode'] = 'ok'
            panel.get_by_role('button').click()
            expect(panel).to_contain_text('本次握手已确认')
            assert not errors
            checks['manual_recovery_no_pageerrors_or_writes'] = True
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    result = {'passed': True, 'checks': checks, 'fixture_server_stopped': not worker.is_alive(),
                  'scope': 'mocked API browser checks only', 'production_deployed': False}
    (args.out_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
