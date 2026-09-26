#!/usr/bin/env python3
"""Browser-only source panel checks with explicit API fixtures, not live backend E2E."""
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
            if self.path.startswith('/agents/'):
                self.path = '/index.html'
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(args.web.resolve())))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    checks = {}
    mode = {'value': 'bound'}
    context = {
        'schema_version': 'console-context/v1', 'evaluated_at': '2026-09-25T00:00:00Z',
        'tenant': {'id': 'fixture', 'name': 'Fixture'}, 'actor': {'id': 'fixture', 'type': 'user'},
        'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
        'access': dict.fromkeys(('workspace overview agents permissions findings policies changes '
                                 'runtime_bindings environments audit settings').split(), True),
        'actions': dict.fromkeys(('confirm_assets manage_environment enroll_devices '
                                  'manage_policy propose_change approve_change').split(), False),
    }

    def route(request):
        path = urlparse(request.request.url).path
        status, body = 200, []
        if path.endswith('/console-context'):
            body = context
        elif path.endswith('/inventory/access'):
            body = {'schema_version': 'inventory-access/v1', 'can_confirm': False,
                    'can_discover': False, 'can_manage_policy': False}
        elif path.endswith('/discovery-origin'):
            asset = path.split('/')[-2]
            body = {'schema_version': 'enterprise-discovery-origin/v1', 'asset_id': asset,
                    'status': 'device_bound', 'environment': {'id': 'env', 'name': 'Fixture Environment'},
                    'device': {'id': 'edge', 'identity': 'fixture-device', 'revoked': True},
                    'reported_framework': 'hermes', 'assigned_role': None,
                    'observations': [], 'observations_truncated': False}
            if mode['value'] == 'denied':
                status, body = 403, {'detail': 'forbidden'}
            elif mode['value'] == 'mismatch':
                body['asset_id'] = 'different-asset'
            elif mode['value'] == 'legacy':
                body.update(status='legacy_unresolved', device=None, environment=None)
        elif path.endswith('/enforcement'):
            body = {'agent_id': 'asset', 'enforce_status': 'declared_only', 'policy_count': 0,
                    'effective_deployments': [], 'all_deployments': []}
        elif '/agents/' in path and len(path.split('/')) == 5:
            body = {'id': path.split('/')[-1], 'name': 'Fixture Asset', 'framework': 'hermes',
                    'status': 'candidate', 'role': None, 'updated_at': '2026-09-25T00:00:00Z'}
        assert request.request.method == 'GET', 'browser attempted a mutation'
        request.fulfill(status=status, json=body)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page.on('pageerror', lambda _: errors.append('pageerror'))
            page.route('**/api/v1/**', route)
            base = f'http://127.0.0.1:{server.server_port}'
            page.goto(base + '/agents/asset')
            panel = page.get_by_role('region', name='发现来源')
            expect(panel).to_contain_text('fixture-device')
            expect(panel).to_contain_text('已吊销，仅保留历史来源')
            expect(panel).to_contain_text('不代表运行时已绑定')
            panel.screenshot(path=str(args.out_dir / 'desktop.png'), animations='disabled')
            checks['bound_revoked_source_not_protection'] = True
            mode['value'] = 'denied'
            page.reload()
            expect(panel).to_contain_text('当前账号无权')
            mode['value'] = 'bound'
            panel.get_by_role('button', name='重试读取来源').click()
            expect(panel).to_contain_text('fixture-device')
            checks['permission_denied_and_retry'] = True
            mode['value'] = 'mismatch'
            page.reload()
            expect(panel).to_contain_text('读取失败')
            expect(panel).not_to_contain_text('fixture-device')
            checks['wrong_asset_response_rejected'] = True
            mode['value'] = 'legacy'
            page.set_viewport_size({'width': 390, 'height': 844})
            page.reload()
            expect(panel).to_contain_text('历史资产尚未确认设备归属')
            expect(panel).not_to_contain_text('fixture-device')
            panel.screenshot(path=str(args.out_dir / 'mobile.png'), animations='disabled')
            checks['mobile_legacy_no_guessed_source'] = True
            assert not errors, 'browser errors'
            checks['no_browser_errors'] = True
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    result = {'passed': True, 'scope': 'browser UI with mocked API; not backend E2E',
              'checks': checks, 'fixture_server_stopped': not worker.is_alive(), 'production_deployed': False}
    (args.out_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
