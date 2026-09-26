"""Isolated device credential UI; all API calls are synthetic and intercepted."""
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
    parser.add_argument('--web', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(exist_ok=False)

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path.startswith('/environments'):
                self.path = '/index.html'
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=args.web))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state = {'manage': True, 'revoked': False, 'read_error': False, 'posts': [], 'reads': 0}
    errors = []
    now = '2026-09-25T00:00:00Z'
    checks = {}

    def intercept(route):
        request = route.request
        url = urlparse(request.url)
        if url.hostname != '127.0.0.1' or url.port != server.server_port:
            route.abort()
            return
        if not url.path.startswith('/api/'):
            route.continue_()
            return
        path = url.path
        if request.method != 'GET':
            state['posts'].append({'path': path, 'body': request.post_data_json})
            assert path == '/api/v1/environments/env/devices/edge-one/revoke'
            assert request.post_data_json == {'schema_version': 'enterprise-device-revoke/v1', 'confirm_device_id': 'edge-one'}
            state['revoked'] = True
            route.abort('failed')  # committed, response lost
            return
        status, body = 200, {}
        if path.endswith('/console-context'):
            body = {'schema_version': 'console-context/v1', 'evaluated_at': now,
                    'tenant': {'id': 'fixture', 'name': 'Fixture'}, 'actor': {'id': 'fixture', 'type': 'user'},
                    'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
                    'access': dict.fromkeys(['workspace', 'overview', 'agents', 'permissions', 'findings',
                                            'policies', 'changes', 'runtime_bindings', 'environments', 'audit', 'settings'], True),
                    'actions': dict.fromkeys(['confirm_assets', 'manage_environment', 'enroll_devices',
                                             'manage_policy', 'propose_change', 'approve_change'], False)}
            body['actions']['enroll_devices'] = state['manage']
        elif path.endswith('/environments/access'):
            body = {'schema_version': 'environment-onboarding-access/v1', 'can_create': False,
                    'can_enroll': False, 'can_scan': False, 'can_view_assets': True}
        elif path.endswith('/environments'):
            body = [{'id': 'env', 'name': 'Fixture DGX', 'env_type': 'host', 'mode': 'discovery'}]
        elif path.endswith('/onboarding'):
            body = {'schema_version': 'environment-onboarding/v1', 'environment_id': 'env', 'evaluated_at': now,
                    'heartbeat_stale_seconds': 300, 'device_count': 1, 'devices_truncated': False,
                    'evidence_count': 0, 'last_evidence_at': None, 'scans': [], 'scans_truncated': False,
                    'devices': [{'id': 'edge-one', 'device_identity': 'Fixture Linux', 'version': '0.1',
                                 'registered_at': now, 'last_seen_at': now, 'status': 'online', 'connectors': []}]}
        elif path.endswith('/credential-status'):
            state['reads'] += 1
            body = {'schema_version': 'enterprise-device-credential-status/v1', 'environment_id': 'env',
                    'device_id': 'edge-one', 'status': 'revoked' if state['revoked'] else 'active',
                    'revoked_at': now if state['revoked'] else None, 'runtime_permissions_changed': False}
            if state['read_error']:
                status, body = 503, {'detail': 'synthetic failure'}
        else:
            status, body = 404, {'detail': 'fixture unavailable'}
        route.fulfill(status=status, json=body)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/*', intercept)
            page.goto(f'http://127.0.0.1:{server.server_port}/environments?environment=env')
            panel = page.get_by_role('region', name='设备凭据管理', exact=True)
            expect(panel).to_be_visible()
            assert state['reads'] == 0 and not state['posts']
            panel.get_by_role('button', name='管理设备凭据', exact=True).press('Enter')
            panel.get_by_label('选择管理设备').select_option('edge-one')
            action = panel.get_by_role('region', name='设备吊销确认')
            expect(action).to_contain_text('当前记录尚未吊销')
            submit = action.get_by_role('button', name='确认吊销设备凭据')
            expect(submit).to_be_disabled()
            action.get_by_label('输入设备 ID 确认吊销').fill('wrong')
            expect(submit).to_be_disabled()
            action.get_by_label('输入设备 ID 确认吊销').fill('edge-one')
            expect(submit).to_be_enabled()
            checks['explicit_identity_confirmation_no_initial_write'] = True
            for width in [375, 768, 1280]:
                page.set_viewport_size({'width': width, 'height': 900})
                action.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                assert page.locator('.content').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
                if width != 768:
                    page.screenshot(path=str(args.out / f'device-{width}.png'), animations='disabled')
            checks['responsive_no_overflow'] = True
            submit.press('Enter')
            expect(action.get_by_role('alert')).to_contain_text('吊销结果未确认')
            expect(submit).to_have_count(0)
            assert len(state['posts']) == 1
            state['read_error'] = True
            action.get_by_role('button', name='查询原设备状态').click()
            expect(action.get_by_role('alert')).to_contain_text('无法核对')
            expect(action).not_to_contain_text('设备凭据已吊销')
            state['read_error'] = False
            page.reload()
            expect(action).to_contain_text('设备凭据已吊销')
            expect(action).to_contain_text('不是业务权限撤销')
            assert len(state['posts']) == 1
            checks['unknown_result_readback_and_reload_never_replay'] = True
            reads = state['reads']
            state['manage'] = False
            page.reload()
            expect(page.get_by_role('heading', name='环境与设备', exact=True)).to_be_visible()
            expect(panel).to_have_count(0)
            assert state['reads'] == reads and len(state['posts']) == 1
            checks['permission_denial_hides_deep_link_management'] = True
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    report = {'passed': True, 'scope': 'mock browser only', 'checks': checks, 'mock_posts': state['posts'],
              'pageerrors': errors, 'server_stopped': not worker.is_alive(), 'production_deployed': False}
    (args.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
