#!/usr/bin/env python3
"""Bulk candidate UI with isolated API fixtures; never approves real assets."""
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
    parser.add_argument('--action', choices=('confirm', 'dismiss'), default='confirm')
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=False)
    label = '确认' if args.action == 'confirm' else '驳回'
    terminal = 'confirmed' if args.action == 'confirm' else 'dismissed'
    submit_label = '确认所选候选' if args.action == 'confirm' else '驳回所选候选'

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
    state = {'mode': 'lost', 'posts': 0, 'confirmed': False, 'viewer': False}
    context = {
        'schema_version': 'console-context/v1', 'evaluated_at': '2026-09-25T00:00:00Z',
        'tenant': {'id': 'fixture', 'name': 'Fixture'}, 'actor': {'id': 'fixture', 'type': 'user'},
        'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
        'access': dict.fromkeys(('workspace overview agents permissions findings policies changes '
                                'runtime_bindings environments audit settings').split(), True),
        'actions': dict.fromkeys(('confirm_assets manage_environment enroll_devices '
                                 'manage_policy propose_change approve_change').split(), False),
    }

    def assets():
        return [{'id': 'asset_' + key, 'name': '候选 ' + key, 'framework': 'hermes', 'role': None,
                 'status': terminal if state['confirmed'] else 'candidate', 'system_id': None,
                 'owner_user_id': None, 'source_type': None, 'source_locator': None,
                 'updated_at': '2026-09-25T00:00:00Z'} for key in ('a', 'b')]

    def route(request):
        path = urlparse(request.request.url).path
        status, body = 200, []
        if path.endswith('/bulk-' + args.action):
            assert request.request.method == 'POST'
            body = request.request.post_data_json
            assert [item['asset_id'] for item in body['items']] == ['asset_a', 'asset_b']
            assert all(item['expected_updated_at'] == '2026-09-25T00:00:00Z' for item in body['items'])
            if args.action == 'dismiss':
                assert body['reason_code'] == 'out_of_scope'
            state['posts'] += 1
            if state['mode'] == 'lost':
                state['confirmed'] = True
                request.abort('failed')
                return
            status, body = 409, {'detail': 'candidate_changed'}
        else:
            assert request.request.method == 'GET'
            if path.endswith('/console-context'):
                body = context
            elif path.endswith('/inventory/access'):
                body = {'schema_version': 'inventory-access/v1', 'can_confirm': not state['viewer'],
                        'can_discover': False, 'can_manage_policy': False}
            elif path.endswith('/candidates'):
                body = [] if state['confirmed'] else assets()
            elif path.endswith('/agents'):
                body = assets() if state['confirmed'] and args.action == 'confirm' else []
            elif '/agents/asset_' in path:
                body = next(row for row in assets() if row['id'] == path.split('/')[-1])
        request.fulfill(status=status, json=body)

    checks = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000}, locale='zh-CN')
            errors = []
            page.on('pageerror', lambda _: errors.append('pageerror'))
            page.route('**/api/v1/**', route)
            page.goto(f'http://127.0.0.1:{server.server_port}/agents?view=candidates')
            page.get_by_role('button', name='选择已加载前 50 个').click()
            page.get_by_role('button', name='核对并批量' + label).click()
            dialog = page.get_by_role('dialog')
            expect(dialog.get_by_role('button', name=submit_label)).to_be_disabled()
            expect(dialog).to_contain_text('不批准工具权限' if args.action == 'confirm' else '不删除配置')
            if args.action == 'dismiss':
                dialog.get_by_role('checkbox').check()
                expect(dialog.get_by_role('button', name=submit_label)).to_be_disabled()
                dialog.get_by_label('批量驳回原因').select_option('out_of_scope')
                expect(dialog.get_by_role('checkbox')).not_to_be_checked()
            dialog.get_by_role('checkbox').check()
            dialog.get_by_role('button', name=submit_label).click()
            expect(dialog.get_by_role('alert')).to_contain_text('不能假定已全部成功')
            expect(dialog.get_by_role('button', name=submit_label)).to_have_count(0)
            dialog.get_by_role('button', name='核对批量处理结果').click()
            expect(dialog).to_have_count(0)
            expect(page.get_by_text('已读回 2 个资产为已' + label, exact=False)).to_be_visible()
            assert state['posts'] == 1
            checks['explicit_selection_ack_and_lost_response_read_only_recovery'] = True
            state.update(mode='conflict', confirmed=False)
            page.reload()
            page.get_by_role('button', name='选择已加载前 50 个').click()
            page.get_by_role('button', name='核对并批量' + label).click()
            if args.action == 'dismiss':
                dialog.get_by_label('批量驳回原因').select_option('out_of_scope')
            dialog.get_by_role('checkbox').check()
            dialog.get_by_role('button', name=submit_label).click()
            expect(dialog.get_by_role('alert')).to_contain_text('版本或状态发生变化')
            dialog.get_by_role('button', name='核对批量处理结果').click()
            expect(dialog.get_by_role('alert')).to_contain_text('全部仍待确认')
            expect(dialog.get_by_role('checkbox')).not_to_be_checked()
            expect(dialog.get_by_role('button', name=submit_label)).to_be_disabled()
            assert state['posts'] == 2
            checks['conflict_repreview_requires_new_ack_no_auto_retry'] = True
            page.set_viewport_size({'width': 375, 'height': 812})
            page.screenshot(path=str(args.out_dir / 'mobile.png'))
            dialog.get_by_role('button', name='关闭并刷新列表').click()
            state['viewer'] = True
            page.reload()
            expect(page.get_by_text('当前账号仅可查看候选', exact=False)).to_be_visible()
            expect(page.get_by_role('button', name='核对并批量' + label)).to_have_count(0)
            checks['viewer_has_no_batch_controls'] = True
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    result = {'passed': True, 'action': args.action, 'checks': checks, 'scope': 'mocked API browser only',
              'production_deployed': False, 'fixture_server_stopped': not worker.is_alive()}
    (args.out_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
