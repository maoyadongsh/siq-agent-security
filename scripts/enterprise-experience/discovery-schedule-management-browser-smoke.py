#!/usr/bin/env python3
"""Isolated browser smoke for the discovery schedule management panel.

All APIs are intercepted with synthetic responses on 127.0.0.1 static serving.
This proves UI wiring only; it is not backend E2E, production IAM, or a real
device confirmation chain.
"""
import argparse
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

ENV = 'env-fixture'
SCHED_A = 'eds-' + 'a' * 32  # pending_confirmation, revision 0
SCHED_B = 'eds-' + 'b' * 32  # active, revision 3 (page 2)
SCHED_R = 'eds-' + 'c' * 32  # revoked already


def schedule(schedule_id, status, revision):
    return {'schedule_id': schedule_id, 'edge_agent_id': 'edge-fixture', 'status': status,
            'revision': revision, 'starts_at': '2026-09-26T00:00:00Z', 'expires_at': '2026-09-27T00:00:00Z',
            'interval_seconds': 900, 'max_runs': 4, 'reserved_runs': 1, 'last_reserved_slot': 0,
            'created_at': '2026-09-25T00:00:00Z'}


def page(items, next_cursor):
    return {'schema_version': 'enterprise-discovery-schedule-management/v1', 'environment_id': ENV,
            'evaluated_at': '2026-09-26T12:00:00Z', 'can_revoke': True, 'items': items, 'next_cursor': next_cursor}


def revoked_state(schedule_id, revision):
    return {'schema_version': 'enterprise-discovery-schedule-state/v1', 'schedule_id': schedule_id,
            'status': 'revoked', 'revision': revision, 'intent_digest': 'a' * 64}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web', type=Path, required=True, help='isolated simulated web build; never deploy')
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
    checks = {}
    # read: plain list page 1 / paged: pagination flow / ok|conflict|denied|lost: revoke outcomes
    mode = {'value': 'read'}
    writes = {'list': []}
    sched_gets = {'n': 0}
    revoked_ids = set()
    pagination = {'failed': False, 'cursors': []}
    context = {
        'schema_version': 'console-context/v1', 'evaluated_at': '2026-09-26T00:00:00Z',
        'tenant': {'id': 'fixture', 'name': 'Fixture'}, 'actor': {'id': 'fixture', 'type': 'user'},
        'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
        'access': dict.fromkeys(['workspace', 'overview', 'agents', 'permissions', 'findings',
                                 'policies', 'changes', 'runtime_bindings', 'environments',
                                 'audit', 'settings'], True),
        'actions': dict.fromkeys(['confirm_assets', 'manage_environment', 'enroll_devices',
                                  'manage_policy', 'propose_change', 'approve_change'], False),
    }
    connection = {'schema_version': 'enterprise-openshell-connection/v1', 'environment_id': ENV,
                  'scope': 'control_plane_connection', 'status': 'not_configured',
                  'ready_for_deployment': False, 'version_compatibility': 'unverified',
                  'credential_scope': 'unverified', 'execution_evidence': 'none',
                  'endpoint_fingerprint': None, 'gateway_name_sha256': None,
                  'cli_version': '0.0.0', 'gateway_version': 'unknown', 'configuration_capabilities': {}}

    def routes(request):
        path = urlparse(request.request.url).path
        method = request.request.method
        if method not in ('GET', 'HEAD'):
            writes['list'].append({'path': path, 'body': request.request.post_data_json})
        if path.endswith('/console-context'):
            if mode['value'] == 'denied_context':
                denied = {**context, 'access': {**context['access'], 'environments': False}}
                request.fulfill(status=200, json=denied)
            else:
                request.fulfill(status=200, json=context)
        elif path == '/api/v1/environments':
            request.fulfill(status=200, json=[{
                'id': ENV, 'name': 'Fixture 环境', 'env_type': 'host', 'mode': 'discovery',
            }])
        elif path == '/api/v1/environments/access':
            request.fulfill(status=200, json={'schema_version': 'environment-onboarding-access/v1',
                                              'can_create': False, 'can_enroll': False, 'can_scan': False,
                                              'can_view_assets': False})
        elif path == f'/api/v1/environments/{ENV}/openshell-connection':
            request.fulfill(status=200, json=connection)
        elif path == f'/api/v1/environments/{ENV}/discovery-schedules' and method == 'GET':
            sched_gets['n'] += 1
            if mode['value'] in ('read', 'ok', 'conflict', 'denied', 'lost'):
                request.fulfill(status=200, json=page(
                    [schedule(SCHED_A, 'revoked' if mode['value'] == 'ok' and SCHED_A in revoked_ids
                              else 'pending_confirmation', 1 if SCHED_A in revoked_ids else 0),
                     schedule(SCHED_B, 'revoked' if mode['value'] == 'ok' and SCHED_B in revoked_ids
                              else 'active', 4 if SCHED_B in revoked_ids else 3),
                     schedule(SCHED_R, 'revoked', 5)], None))
            elif mode['value'] in ('paged', 'paged-fail'):
                cursor = parse_qs(urlparse(request.request.url).query).get('cursor', [None])[0]
                pagination['cursors'].append(cursor)
                if cursor == SCHED_A:
                    if mode['value'] == 'paged-fail' and not pagination['failed']:
                        pagination['failed'] = True
                        request.fulfill(status=503, json={'detail': 'synthetic_unavailable'})
                    else:
                        request.fulfill(status=200, json=page(
                            [schedule(SCHED_B, 'active', 3), schedule(SCHED_R, 'revoked', 5)], None))
                else:
                    request.fulfill(status=200, json=page(
                        [schedule(SCHED_A, 'pending_confirmation', 0)], SCHED_A))
            else:
                request.fulfill(status=500, json={'detail': 'server_error'})
        elif path in (f'/api/v1/environments/{ENV}/discovery-schedules/{SCHED_A}/revoke',
                      f'/api/v1/environments/{ENV}/discovery-schedules/{SCHED_B}/revoke') and method == 'POST':
            target = path.split('/')[-2]
            revision = 0 if target == SCHED_A else 3
            body = request.request.post_data_json
            if mode['value'] == 'conflict':
                request.fulfill(status=409, json={'detail': 'discovery_schedule_revision_conflict'})
            elif mode['value'] == 'denied':
                request.fulfill(status=403, json={'detail': 'forbidden'})
            elif mode['value'] == 'lost':
                request.abort('failed')
            elif body == {'expected_revision': revision}:
                revoked_ids.add(target)
                request.fulfill(status=200, json=revoked_state(target, revision + 1))
            else:
                request.fulfill(status=400, json={'detail': 'unexpected_payload'})
        else:
            request.fulfill(status=404, json={'detail': 'not_found'})

    def overflow_ok(browser_page):
        return browser_page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page_obj = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors = []
            page_obj.on('pageerror', lambda error: errors.append(str(error)))
            page_obj.route('**/api/v1/**', routes)
            base = f'http://127.0.0.1:{server.server_port}'

            # --- 只读阶段：零业务写 ---
            page_obj.goto(base + '/environments')
            page_obj.get_by_role('button', name='查看接入进度').first.click()
            panel = page_obj.get_by_role('region', name='周期发现计划')
            expect(panel).to_contain_text('不代表设备在线、采集成功或防护生效')
            writes['list'].clear()
            panel.get_by_role('button', name='查看周期发现计划').click()
            expect(panel).to_contain_text(SCHED_A)
            expect(panel).to_contain_text('待设备确认')
            expect(panel).to_contain_text('已确认的计划')
            expect(panel).to_contain_text('已撤销')
            expect(panel).to_contain_text('已预约轮次不是成功扫描次数')
            expect(panel).to_contain_text('仅显示已加载记录')
            assert writes['list'] == [], writes
            checks['read_phase_zero_writes_and_status_labels'] = True

            # 已撤销记录不展示撤销按钮；待确认记录展示
            item_a = panel.locator('li', has_text=SCHED_A)
            expect(item_a.get_by_role('button', name='撤销该计划')).to_have_count(1)
            item_r = panel.locator('li', has_text=SCHED_R)
            expect(item_r.get_by_role('button', name='撤销该计划')).to_have_count(0)
            checks['revoked_row_has_no_revoke_button'] = True

            # --- 撤销成功：逐字核对 POST 路径/方法/载荷 ---
            writes['list'].clear()
            mode['value'] = 'ok'
            item_a.get_by_role('button', name='撤销该计划').click()
            dialog = page_obj.get_by_role('dialog')
            expect(dialog).to_contain_text(SCHED_A)
            expect(dialog).to_contain_text('edge-fixture')
            expect(dialog).to_contain_text('不保证已派发任务被取消，不撤销智能体业务权限')
            # 取消是零写请求
            dialog.get_by_role('button', name='取消').click()
            assert not writes['list'], writes
            item_a.get_by_role('button', name='撤销该计划').click()
            dialog.get_by_role('button', name='确认撤销').click()
            sent = [item for item in writes['list'] if item['path'].endswith(f'/discovery-schedules/{SCHED_A}/revoke')]
            assert sent == [{'path': f'/api/v1/environments/{ENV}/discovery-schedules/{SCHED_A}/revoke',
                             'body': {'expected_revision': 0}}], writes
            expect(panel).to_contain_text('已撤销该计划')
            checks['revoke_success_exact_payload_and_refresh'] = True

            expect(panel.locator('li', has_text=SCHED_A).get_by_role('button', name='撤销该计划')).to_have_count(0)
            panel.locator('li', has_text=SCHED_B).get_by_role('button', name='撤销该计划').click()
            page_obj.get_by_role('dialog').get_by_role('button', name='确认撤销').click()
            expect(panel.locator('li', has_text=SCHED_B).get_by_role('button', name='撤销该计划')).to_have_count(0)
            assert writes['list'] == [
                {'path': f'/api/v1/environments/{ENV}/discovery-schedules/{SCHED_A}/revoke',
                 'body': {'expected_revision': 0}},
                {'path': f'/api/v1/environments/{ENV}/discovery-schedules/{SCHED_B}/revoke',
                 'body': {'expected_revision': 3}},
            ], writes
            checks['second_revoke_after_success_without_reload'] = True
            revoked_ids.clear()

            # --- 409：提示刷新核对，不自动重试 ---
            writes['list'].clear()
            mode['value'] = 'conflict'
            page_obj.reload()
            page_obj.get_by_role('button', name='查看接入进度').first.click()
            panel.get_by_role('button', name='查看周期发现计划').click()
            expect(panel).to_contain_text(SCHED_A)
            panel.locator('li', has_text=SCHED_A).get_by_role('button', name='撤销该计划').click()
            page_obj.get_by_role('dialog').get_by_role('button', name='确认撤销').click()
            expect(panel).to_contain_text('不会自动用新版本重试')
            assert len([item for item in writes['list'] if item['path'].endswith('/revoke')]) == 1, writes
            checks['revoke_409_prompt_refresh_no_auto_retry'] = True

            # --- 403：不伪装成功 ---
            writes['list'].clear()
            mode['value'] = 'denied'
            page_obj.reload()
            page_obj.get_by_role('button', name='查看接入进度').first.click()
            panel.get_by_role('button', name='查看周期发现计划').click()
            expect(panel).to_contain_text(SCHED_A)
            panel.locator('li', has_text=SCHED_A).get_by_role('button', name='撤销该计划').click()
            page_obj.get_by_role('dialog').get_by_role('button', name='确认撤销').click()
            expect(panel).to_contain_text('当前账号没有撤销周期计划的权限')
            checks['revoke_403_no_fake_success'] = True

            # --- 网络/5xx：结果未知，不自动重发 ---
            writes['list'].clear()
            mode['value'] = 'lost'
            page_obj.reload()
            page_obj.get_by_role('button', name='查看接入进度').first.click()
            panel.get_by_role('button', name='查看周期发现计划').click()
            expect(panel).to_contain_text(SCHED_A)
            panel.locator('li', has_text=SCHED_A).get_by_role('button', name='撤销该计划').click()
            page_obj.get_by_role('dialog').get_by_role('button', name='确认撤销').click()
            expect(panel).to_contain_text('撤销结果未知')
            assert len([item for item in writes['list'] if item['path'].endswith('/revoke')]) == 1, writes
            checks['revoke_unknown_result_no_auto_resend'] = True

            panel.evaluate("element => element.scrollIntoView({block: 'start'})")
            page_obj.screenshot(path=str(args.out_dir / 'desktop.png'), animations='disabled')
            checks['desktop_screenshot_saved'] = True

            # --- 权限不足：面板不渲染且零周期计划请求 ---
            mode['value'] = 'denied_context'
            writes['list'].clear()
            sched_gets['n'] = 0
            page_obj.goto(base + '/environments?environment=' + ENV)
            page_obj.wait_for_timeout(1500)
            expect(page_obj.get_by_role('region', name='周期发现计划')).to_have_count(0)
            assert sched_gets['n'] == 0, 'panel fetched without env read permission'
            checks['no_env_read_permission_renders_nothing'] = True

            # --- 分页：加载更多 + 失败保留同游标重试 ---
            mode['value'] = 'paged-fail'
            pagination['cursors'].clear()
            page_obj.reload()
            page_obj.get_by_role('button', name='查看接入进度').first.click()
            panel.get_by_role('button', name='查看周期发现计划').click()
            expect(panel).to_contain_text('不代表全部计划')
            expect(panel).not_to_contain_text(SCHED_B)
            panel.get_by_role('button', name='加载更多').click()
            expect(panel).to_contain_text('加载更多失败')
            expect(panel).to_contain_text(SCHED_A)
            expect(panel.get_by_role('button', name='撤销该计划')).to_have_count(0)
            panel.get_by_role('button', name='用同一游标重试加载更多').click()
            expect(panel).to_contain_text(SCHED_B)
            expect(panel).not_to_contain_text('加载更多失败')
            assert pagination['cursors'] == [None, SCHED_A, SCHED_A], pagination
            expect(panel).to_contain_text('（已确认的计划不代表设备在线、采集成功或防护生效）')
            checks['pagination_load_more'] = True
            checks['pagination_failure_readonly_and_same_cursor_retry'] = True

            # --- 键盘：聚焦加载更多按钮，回车触发同一游标请求 ---
            mode['value'] = 'read'
            page_obj.reload()
            page_obj.get_by_role('button', name='查看接入进度').first.click()
            panel.get_by_role('button', name='查看周期发现计划').click()
            expect(panel).to_contain_text(SCHED_A)
            panel.get_by_role('button', name='只读刷新（从第一页替换）').focus()
            page_obj.keyboard.press('Enter')
            expect(panel).to_contain_text(SCHED_A)
            checks['keyboard_operation'] = True

            # --- 375px 无横向溢出 + 移动截图 ---
            mode['value'] = 'read'
            page_obj.set_viewport_size({'width': 375, 'height': 812})
            page_obj.reload()
            page_obj.get_by_role('button', name='查看接入进度').first.click()
            panel.get_by_role('button', name='查看周期发现计划').click()
            expect(panel).to_contain_text(SCHED_A)
            assert overflow_ok(page_obj), 'horizontal overflow at 375px'
            panel.evaluate("element => element.scrollIntoView({block: 'start'})")
            assert panel.locator('.dsm-label').first.evaluate(
                'element => element.getBoundingClientRect().height < 40'
            ), 'mobile column layout must not retain the desktop 6em label basis'
            page_obj.screenshot(path=str(args.out_dir / 'mobile.png'), animations='disabled')
            checks['mobile_375_no_overflow'] = True

            # 桌面溢出复核
            page_obj.set_viewport_size({'width': 1440, 'height': 1000})
            assert overflow_ok(page_obj), 'horizontal overflow at desktop'
            checks['desktop_no_overflow'] = True

            assert not errors, f'browser errors: {errors}'
            checks['no_uncaught_page_errors'] = True
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    result = {'passed': True, 'scope': 'browser UI with mocked API; not backend E2E, not production IAM',
              'checks': checks, 'fixture_server_stopped': not worker.is_alive(),
              'build_mode': 'VITE_DEV_MODE=true simulated build for smoke only; 不可发布', 'production_deployed': False}
    (args.out_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
