"""Role scope history UI fixtures only: no live registration, upload or permissions."""
import argparse
import copy
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
    state = {'mode': 'history'}
    held = []
    checks = {}
    context = {
        'schema_version': 'console-context/v1', 'evaluated_at': '2026-09-25T00:00:00Z',
        'tenant': {'id': 'fixture', 'name': 'Fixture'}, 'actor': {'id': 'fixture', 'type': 'user'},
        'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
        'access': dict.fromkeys([
            'workspace', 'overview', 'agents', 'permissions', 'findings', 'policies', 'changes',
            'runtime_bindings', 'environments', 'audit', 'settings',
        ], True),
        'actions': dict.fromkeys([
            'confirm_assets', 'manage_environment', 'enroll_devices',
            'manage_policy', 'propose_change', 'approve_change',
        ], False),
    }
    observation = {
        'id': 'rso-new', 'device': {'id': 'edge-fixture', 'revoked': True}, 'task_id': 'task-new',
        'batch_digest': 'a' * 64, 'observed_at': '2026-09-25T01:00:00Z', 'received_at': '2026-09-25T01:00:01Z',
        'selection': {'schema_version': 'enterprise-openclaw-skill-selection/v1', 'source': 'agent',
                      'status': 'declared_list', 'names': ['docs', 'long-' + 'x' * 123]},
        'source_evidence': [{'evidence_id': 'ev-new', 'content_hash': 'b' * 64,
                             'observed_at': '2026-09-25T01:00:00Z'}],
    }

    def history(asset):
        old = copy.deepcopy(observation)
        old.update(id='rso-old', task_id='task-old', received_at='2026-09-25T00:00:01Z')
        old['selection'].update(source='defaults', names=['weather'])
        body = {'schema_version': 'enterprise-role-skill-observations/v1', 'asset_id': asset,
                'status': 'historical_declarations', 'relationship_status': 'unresolved',
                'effective_permissions': None, 'observations_truncated': False,
                'observations': [copy.deepcopy(observation), old]}
        mode = state['mode']
        if mode == 'empty':
            body.update(status='no_recorded_declaration', observations=[])
        elif mode == 'mismatch':
            body['asset_id'] = 'different-asset'
        elif mode in ('unconfigured', 'unsupported', 'explicit-empty'):
            body['observations'][0]['selection'].update(
                names=[], source='none' if mode == 'unconfigured' else 'agent',
                status='declared_list' if mode == 'explicit-empty' else mode,
            )
        elif mode == 'truncated':
            body['observations'] = [dict(copy.deepcopy(observation), id=f'rso-{i:03}', task_id=f'task-{i}')
                                    for i in range(100)]
            body['observations_truncated'] = True
        return body

    def route(request):
        path = urlparse(request.request.url).path
        status, body = 200, []
        assert request.request.method == 'GET', 'browser attempted a mutation'
        if path.endswith('/console-context'):
            body = context
        elif path.endswith('/inventory/access'):
            body = {'schema_version': 'inventory-access/v1', 'can_confirm': False,
                    'can_discover': False, 'can_manage_policy': False}
        elif path.endswith('/skill-selections'):
            if state['mode'] == 'held':
                held.append(request)
                return
            if state['mode'] == 'denied':
                status, body = 403, {'detail': 'forbidden'}
            else:
                body = history(path.split('/')[-2])
        elif path.endswith('/discovery-origin'):
            body = {'schema_version': 'enterprise-discovery-origin/v1', 'asset_id': 'asset',
                    'status': 'source_unavailable', 'environment': None, 'device': None,
                    'reported_framework': 'openclaw', 'assigned_role': None,
                    'observations': [], 'observations_truncated': False}
        elif path.endswith('/enforcement'):
            body = {'agent_id': 'asset', 'enforce_status': 'declared_only', 'policy_count': 0,
                    'effective_deployments': [], 'all_deployments': []}
        elif '/agents/' in path and len(path.split('/')) == 5:
            body = {'id': path.split('/')[-1], 'name': 'Fixture Role', 'framework': 'openclaw',
                    'status': 'candidate', 'role': None, 'updated_at': '2026-09-25T00:00:00Z'}
        request.fulfill(status=status, json=body)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1100})
            errors = []
            page.on('pageerror', lambda _: errors.append('pageerror'))
            page.route('**/api/v1/**', route)
            page.goto(f'http://127.0.0.1:{server.server_port}/agents/asset')
            panel = page.get_by_role('region', name='角色技能声明')
            expect(panel).to_contain_text('声明可见的技能名称（2）')
            expect(panel).to_contain_text('尚未解析，不能按同名认定归属')
            expect(panel).to_contain_text('凭据已吊销，仅保留历史')
            expect(panel.get_by_role('link')).to_have_attribute('href', '/agents/skills?device_id=edge-fixture')
            panel.get_by_role('combobox').select_option('rso-old')
            expect(panel).to_contain_text('继承框架默认范围')
            expect(panel).to_contain_text('weather')
            expect(panel).not_to_contain_text('long-')
            panel.get_by_role('combobox').select_option('rso-new')
            summary = panel.locator('summary')
            summary.focus()
            page.keyboard.press('Enter')
            expect(panel.locator('details')).to_have_attribute('open', '')
            panel.screenshot(path=str(args.out_dir / 'desktop.png'), animations='disabled')
            checks['history_selection_keyboard_trace_and_no_effective_claim'] = True

            page.set_viewport_size({'width': 375, 'height': 844})
            expect(panel).to_contain_text('ev-new')
            assert panel.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'), 'panel overflow'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'page overflow'
            panel.screenshot(path=str(args.out_dir / 'mobile.png'), animations='disabled')
            panel.locator('details').scroll_into_view_if_needed()
            page.screenshot(path=str(args.out_dir / 'mobile-trace-viewport.png'), animations='disabled')
            checks['mobile_long_identifiers_and_hashes_no_overflow'] = True

            for mode, message in [('empty', '这不代表此角色没有安装技能'), ('unconfigured', '未配置技能范围筛选'),
                                  ('unsupported', '不回退到默认范围'), ('explicit-empty', '不代表技能已卸载'),
                                  ('truncated', '不是完整历史'), ('denied', '当前账号无权'),
                                  ('mismatch', '技能声明读取失败')]:
                state['mode'] = mode
                panel.get_by_role('button', name='刷新技能声明').click()
                expect(panel).to_contain_text(message)
                if mode in ('denied', 'mismatch'):
                    expect(panel).not_to_contain_text('声明可见的技能名称')
                checks[mode] = True

            state['mode'] = 'held'
            panel.get_by_role('button', name='刷新技能声明').click()
            expect(panel).to_contain_text('正在读取技能声明')
            page.wait_for_function('true')
            assert held, 'no outstanding fixture request'
            state['mode'] = 'history'
            panel.get_by_role('button', name='刷新技能声明').click()
            expect(panel).to_contain_text('声明可见的技能名称（2）')
            stale = history('asset')
            stale['observations'][0]['selection']['names'] = ['stale-fixture']
            held.pop().fulfill(status=200, json=stale)
            page.wait_for_timeout(100)
            expect(panel).not_to_contain_text('stale-fixture')
            checks['late_previous_request_ignored'] = True
            assert not errors, 'browser errors'
            checks['no_browser_errors_and_no_writes'] = True
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
