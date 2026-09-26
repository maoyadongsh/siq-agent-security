"""CL-06-AUDIT-CORRELATION-UI：审计关联检索浏览器冒烟（全 API 拦截合成响应，仅回环静态服务）。

- 所有 /api/v1/** 请求由 Playwright route 拦截并返回合成 JSON，不连接真实控制面；
- 仅验证：关联按钮旅程、表单同步、同条件重复不发请求、特殊字符原值、
  键盘可用、375/1280 无横向溢出、零业务写请求、零未捕获异常；
- 使用 VITE_DEV_MODE=true 独立构建目录（仅模拟，不可发布）；
- 输出两张关键截图 + 结构化 JSON 报告。
"""
import argparse
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import expect, sync_playwright

SPECIAL_REQ = '  Req-8F2A & + # "引号" 中文 '

ROWS = [
    {
        'id': 'aud-0001', 'actor_type': 'user', 'actor_id': 'u-0001', 'action': 'agent.confirm',
        'resource_type': 'agent_asset', 'resource_id': 'agt-01h2kd93nf', 'decision': 'allow',
        'request_id': SPECIAL_REQ, 'summary': {}, 'created_at': '2026-09-26T09:30:00Z',
    },
    {
        'id': 'aud-0002', 'actor_type': 'edge', 'actor_id': 'edge-node-01', 'action': 'evidence.batch.upload',
        'resource_type': 'environment', 'resource_id': 'env-dev-docker', 'decision': 'allow',
        'request_id': 'req-71bc', 'summary': {'candidates': 2}, 'created_at': '2026-09-26T09:52:00Z',
    },
    {
        'id': 'aud-0003', 'actor_type': 'user', 'actor_id': 'u-0002', 'action': 'finding.resolve',
        'resource_type': 'finding', 'resource_id': None, 'decision': 'deny',
        'request_id': None, 'summary': {}, 'created_at': '2026-09-26T06:20:00Z',
    },
]

CONTEXT = {
    'schema_version': 'console-context/v1',
    'evaluated_at': '2026-09-26T00:00:00Z',
    'tenant': {'id': 'fixture', 'name': 'Fixture'},
    'actor': {'id': 'fixture', 'type': 'user'},
    'authentication': 'development_headers',
    'roles': [],
    'custom_role_count': 0,
    'access': {k: True for k in ['workspace', 'overview', 'agents', 'permissions', 'findings',
                                 'policies', 'changes', 'runtime_bindings', 'environments', 'audit', 'settings']},
    'actions': {k: False for k in ['confirm_assets', 'manage_environment', 'enroll_devices',
                                   'manage_policy', 'propose_change', 'approve_change']},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web', type=Path, required=True, help='dev 构建目录（VITE_DEV_MODE=true，仅模拟）')
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=False)

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path.startswith('/audit'):
                self.path = '/index.html'
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(args.web.resolve())))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    state = {'audit_calls': [], 'write_calls': [], 'context_calls': 0}

    def audit_response(query):
        # 精确匹配语义：request_id / resource_type+resource_id
        req = query.get('request_id', [None])[0]
        rid = query.get('resource_id', [None])[0]
        rtype = query.get('resource_type', [None])[0]
        items = ROWS
        if req is not None:
            items = [r for r in items if r['request_id'] == req]
        if rid is not None:
            items = [r for r in items if r['resource_id'] == rid]
        if rtype is not None:
            items = [r for r in items if r['resource_type'] == rtype]
        headers = {
            'content-type': 'application/json',
            'x-siq-list-limit': '50',
            'x-siq-list-returned': str(len(items)),
            'x-siq-list-truncated': '0',
            'x-siq-list-total': str(len(items)),
        }
        return 200, items, headers

    def route(request):
        parsed = urlparse(request.request.url)
        method = request.request.method
        if method != 'GET':
            state['write_calls'].append({'method': method, 'path': parsed.path})
        if parsed.path.endswith('/console-context'):
            state['context_calls'] += 1
            request.fulfill(status=200, headers={'content-type': 'application/json'}, json=CONTEXT)
            return
        if parsed.path.endswith('/audit-events'):
            query = parse_qs(parsed.query)
            state['audit_calls'].append({k: v[0] for k, v in query.items()})
            status, items, headers = audit_response(query)
            request.fulfill(status=status, headers=headers, json=items)
            return
        # 其余 API：空列表/空对象，避免页面其它请求挂起
        request.fulfill(status=200, headers={'content-type': 'application/json'}, json=[])

    checks = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 1000})
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
            page.route('**/api/v1/**', route)
            page.goto(f'http://127.0.0.1:{server.server_port}/audit')

            # 1. 真实结果加载，关联按钮出现
            expect(page.get_by_role('button', name=f'查询同请求：{SPECIAL_REQ}')).to_be_visible()
            expect(page.get_by_role('button', name='查询同对象：agent_asset:agt-01h2kd93nf')).to_be_visible()
            expect(page.get_by_role('button', name='查询同对象：environment:env-dev-docker')).to_be_visible()
            checks['correlation_buttons_visible'] = True

            # 缺失标识行（aud-0003）无关联动作
            row3 = page.locator('tbody tr', has_text='aud-0003')
            expect(row3).not_to_have_text('查询同请求')
            expect(row3).not_to_have_text('查询同对象')
            expect(row3).to_contain_text('未提供')
            checks['missing_identifier_no_action'] = True

            # 2. 查询同请求：特殊字符原值、清空其余条件、表单同步
            before = len(state['audit_calls'])
            page.get_by_role('button', name=f'查询同请求：{SPECIAL_REQ}').click()
            page.wait_for_timeout(150)
            assert len(state['audit_calls']) == before + 1, '关联操作应发起一次新查询'
            last = state['audit_calls'][-1]
            assert last.get('request_id') == SPECIAL_REQ, f'原值往返失败: {last!r}'
            for k in ('resource_id', 'resource_type', 'actor_id', 'actor_type', 'action', 'decision'):
                assert k not in last, f'其余条件未清空: {k}'
            # 表单草稿同步（原值逐字）
            expect(page.locator('#audit-search-request_id')).to_have_value(SPECIAL_REQ)
            expect(page.locator('#audit-search-resource_id')).to_have_value('')
            expect(page.get_by_text('当前已应用查询条件：请求编号 = ' + SPECIAL_REQ)).to_be_visible()
            checks['correlate_request_params_and_form_sync'] = True

            # 3. 同条件重复点击：不重复发请求，给出提示
            before = len(state['audit_calls'])
            page.get_by_role('button', name=f'查询同请求：{SPECIAL_REQ}').click()
            page.wait_for_timeout(150)
            assert len(state['audit_calls']) == before, '同条件重复点击不应发请求'
            expect(page.get_by_text('查询条件与当前已应用条件相同，未发起新请求')).to_be_visible()
            checks['same_condition_no_repeat_request'] = True

            # 4. 清空恢复一般查询（关联请求后结果已收窄，需先清空回到全量再测同对象）
            page.get_by_role('button', name='清空查询条件').last.click()
            page.wait_for_timeout(150)
            last = state['audit_calls'][-1]
            assert not any(k in last for k in ('request_id', 'resource_id', 'resource_type')), '清空后不应带过滤条件'
            expect(page.locator('#audit-search-request_id')).to_have_value('')
            checks['clear_restores_general_query'] = True

            # 5. 查询同对象：resource_type + resource_id 一起查询
            before = len(state['audit_calls'])
            page.get_by_role('button', name='查询同对象：environment:env-dev-docker').click()
            page.wait_for_timeout(150)
            assert len(state['audit_calls']) == before + 1
            last = state['audit_calls'][-1]
            assert last.get('resource_type') == 'environment' and last.get('resource_id') == 'env-dev-docker'
            assert 'request_id' not in last
            expect(page.locator('#audit-search-resource_type')).to_have_value('environment')
            expect(page.locator('#audit-search-resource_id')).to_have_value('env-dev-docker')
            checks['correlate_resource_type_and_id'] = True

            # 6. 键盘可用：清空后聚焦关联按钮，Enter 触发
            page.get_by_role('button', name='清空查询条件').last.click()
            page.wait_for_timeout(150)
            before = len(state['audit_calls'])
            btn = page.get_by_role('button', name='查询同对象：agent_asset:agt-01h2kd93nf')
            btn.focus()
            page.keyboard.press('Enter')
            page.wait_for_timeout(150)
            assert len(state['audit_calls']) == before + 1, '键盘 Enter 应触发关联查询'
            last = state['audit_calls'][-1]
            assert last.get('resource_type') == 'agent_asset' and last.get('resource_id') == 'agt-01h2kd93nf'
            checks['keyboard_enter_triggers_correlation'] = True

            # 7. 清空回到一般查询（全量三行 + 关联按钮），再截图，保证两张截图都展示关联操作列
            page.get_by_role('button', name='清空查询条件').last.click()
            page.wait_for_timeout(150)
            expect(page.get_by_role('button', name='查询同对象：environment:env-dev-docker')).to_be_visible()

            # 桌面截图（1280）
            page.screenshot(path=str(args.out_dir / 'desktop-1280.png'), full_page=True)

            # 8. 375px 无新增文档级横向溢出 + 移动端截图
            page.set_viewport_size({'width': 375, 'height': 844})
            page.wait_for_timeout(200)
            overflow = page.evaluate(
                '() => document.documentElement.scrollWidth - document.documentElement.clientWidth')
            assert overflow <= 1, f'375px 文档级横向溢出: {overflow}px'
            page.screenshot(path=str(args.out_dir / 'mobile-375.png'), full_page=True)
            checks['no_document_horizontal_overflow_375'] = True

            # 9. 零业务写请求、零未捕获异常
            assert not state['write_calls'], f'发现业务写请求: {state["write_calls"]}'
            assert not errors, f'未捕获异常/控制台错误: {errors}'
            checks['zero_write_requests_and_zero_uncaught_errors'] = True

            browser.close()
    finally:
        server.shutdown()

    report = {
        'schema_version': 'audit-correlation-browser-smoke/v1',
        'scope': 'control_plane_audit_correlation',
        'simulation_only': True,
        'note': 'VITE_DEV_MODE=true 独立构建目录，全 API 拦截合成响应，仅模拟不可发布',
        'checks': checks,
        'audit_calls': state['audit_calls'],
        'write_calls': state['write_calls'],
        'console_context_calls': state['context_calls'],
        'screenshots': ['desktop-1280.png', 'mobile-375.png'],
    }
    (args.out_dir / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks': checks, 'audit_calls': state['audit_calls'],
                      'write_calls': state['write_calls']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
