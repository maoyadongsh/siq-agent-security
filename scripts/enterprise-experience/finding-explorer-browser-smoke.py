"""ENT-018-FINDINGS-UI 风险中心浏览器冒烟：全部 API 均为合成 fixture，仅监听 127.0.0.1。

分两阶段：
A. 只读场景（筛选/详情/分页/视口）：断言业务写请求为 0；
B. 处置回归（确认/解决）：写请求只发往 Playwright 拦截的模拟响应，逐条记录路径与字段。
模拟验收专用：不连接真实控制面，不能证明后端授权或生产环境已验收。
用法：python finding-explorer-browser-smoke.py --web <构建目录> --out-dir <证据目录>
"""
import argparse
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

NOW = '2026-09-25T12:00:00Z'


def finding(**overrides):
    row = {
        'id': 'fnd-x', 'rule_id': 'R-TEST-001', 'rule_version': 1, 'severity': 'medium',
        'domain': 'tool', 'asset_id': 'agt-1', 'evidence_ids': ['ev-1'],
        'impact': '测试风险', 'remediation': '测试修复', 'status': 'open',
        'owner_user_id': None, 'due_at': None, 'risk_acceptance': None,
        'first_seen_at': '2026-09-01T00:00:00Z', 'last_seen_at': '2026-09-02T00:00:00Z',
    }
    row.update(overrides)
    return row


PAGE1 = [
    finding(id='fnd-1', rule_id='R-A', rule_version=3, severity='high', domain='tool',
            asset_id='agt-alpha', impact='未纳管智能体持有凭据类工具权限', remediation='确认并纳管资产，收敛工具权限'),
    finding(id='fnd-2', rule_id='R-B', severity='medium', domain='network', status='acknowledged',
            owner_user_id='u-admin', impact='出网代理配置漂移'),
    finding(id='fnd-3', rule_id='R-C', severity='low', domain='process', impact='进程白名单缺口'),
    finding(id='fnd-4', rule_id='R-D', severity='critical', domain='credential', status='resolved',
            impact='凭据引用未加密', remediation='改用引用存储', owner_user_id='u-sec'),
]
PAGE2 = [
    finding(id='fnd-5', rule_id='R-E', severity='info', domain='data_scope', status='risk_accepted',
            impact='临时数据范围例外'),
    finding(id='fnd-6', rule_id='R-F', severity='high', domain='credential', asset_id=None,
            impact='<img src=x onerror=alert(1)>', remediation='<script>window.__xss=1</script>',
            due_at='2026-10-01T00:00:00Z', evidence_ids=['ev-9001', 'ev-9002']),
]
PAGE3 = [
    finding(id='fnd-7', rule_id='R-G', severity='medium', domain='business', impact='审批链超时'),
]
EDGE_CASES = [finding(
    id='edge-case', severity='__proto__', status='constructor',
    rule_id='R-' + 'x' * 200, asset_id='asset-' + 'x' * 200,
    owner_user_id='user-' + 'x' * 200, domain='domain-' + 'x' * 200,
    evidence_ids=['evidence-' + 'x' * 200],
)]


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
            if self.path.startswith('/findings'):
                self.path = '/index.html'
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(args.web.resolve())))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    state = {'mode': 'paged', 'ack_fail': False, 'page3_ok': False, 'access': 'ready'}
    writes = []
    list_gets = []
    held = []

    def fulfill_list(request, items, truncated, cursor=None):
        headers = {
            'Content-Type': 'application/json',
            'X-SIQ-List-Limit': '4',
            'X-SIQ-List-Returned': str(len(items)),
            'X-SIQ-List-Truncated': '1' if truncated else '0',
        }
        if cursor:
            headers['X-SIQ-Next-Cursor'] = cursor
        request.fulfill(status=200, json=items, headers=headers)

    def route(request):
        method = request.request.method
        url = request.request.url
        path = urlparse(url).path
        if method != 'GET':
            body = None
            try:
                body = request.request.post_data_json
            except Exception:
                body = request.request.post_data
            writes.append({'method': method, 'path': path, 'body': body})
            if path.endswith('/acknowledge') and state['ack_fail']:
                request.fulfill(status=500, json={'detail': 'fixture ack failure'})
                return
            if path.endswith('/acknowledge'):
                request.fulfill(status=200, json=finding(id='fnd-1', rule_id='R-A', status='acknowledged',
                                                         owner_user_id='u-admin'))
                return
            if path.endswith('/resolve'):
                request.fulfill(status=200, json=finding(id='fnd-1', rule_id='R-A', status='resolved'))
                return
            request.fulfill(status=403, json={'detail': 'fixture denies mutations'})
            return
        if path.endswith('/console-context'):
            if state['access'] == 'error':
                request.fulfill(status=503, json={'detail': 'fixture identity unavailable'})
                return
            request.fulfill(status=200, json={
                'schema_version': 'console-context/v1', 'evaluated_at': NOW,
                'tenant': {'id': 'fixture', 'name': 'Fixture'},
                'actor': {'id': 'fixture', 'type': 'user'},
                'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
                'access': {**dict.fromkeys(['workspace', 'overview', 'agents', 'permissions', 'findings',
                                         'policies', 'changes', 'runtime_bindings', 'environments',
                                         'audit', 'settings'], state['access'] != 'denied'),
                           'workspace': True, 'settings': True},
                'actions': dict.fromkeys(['confirm_assets', 'manage_environment', 'enroll_devices',
                                          'manage_policy', 'propose_change', 'approve_change'], False)})
            return
        if path.endswith('/findings'):
            list_gets.append(urlparse(url).query)
            if state['mode'] == 'hold':
                held.append(request)
                return
            if state['mode'] == 'down':
                request.fulfill(status=502, json={'detail': 'fixture backend down'})
                return
            if state['mode'] == 'empty':
                fulfill_list(request, [], False)
                return
            if state['mode'] == 'edge-cases':
                fulfill_list(request, EDGE_CASES, False)
                return
            cursor = parse_qs(urlparse(url).query).get('cursor', [None])[0]
            if cursor is None:
                fulfill_list(request, PAGE1, True, cursor='c2')
            elif cursor == 'c2':
                fulfill_list(request, PAGE2, True, cursor='c3')
            elif cursor == 'c3' and not state['page3_ok']:
                request.fulfill(status=500, json={'detail': 'fixture load-more failure'})
            else:
                fulfill_list(request, PAGE3, False)
            return
        request.fulfill(status=200, json=[])

    checks = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 1000})
            errors = []
            page.on('pageerror', lambda err: errors.append(str(err)))
            page.route('**/api/v1/**', route)
            base = f'http://127.0.0.1:{server.server_port}/findings'

            # ---------- 阶段 A：只读（零业务写请求） ----------
            # A1. 加载中不冒充零风险、不出示例
            state['mode'] = 'hold'
            page.goto(base)
            expect(page.get_by_text('正在加载风险记录')).to_be_visible()
            expect(page.get_by_role('button', name='确认', exact=True)).to_have_count(0)
            assert 'fnd-' not in page.text_content('body')
            checks['a_loading_no_fake_zero_or_actions'] = True

            # A2. 放行第一页：计数、匹配行、分页说明
            state['mode'] = 'paged'
            held.pop().fulfill(status=200, json=PAGE1, headers={
                'Content-Type': 'application/json', 'X-SIQ-List-Limit': '4',
                'X-SIQ-List-Returned': '4', 'X-SIQ-List-Truncated': '1', 'X-SIQ-Next-Cursor': 'c2'})
            expect(page.get_by_text('匹配 4 条 / 已加载 4 条；筛选仅覆盖已加载记录，不代表组织全量。')).to_be_visible()
            expect(page.get_by_text('存在更多分页未加载')).to_be_visible()
            checks['a_match_line_and_coverage'] = True

            # A3. 键盘展开详情：规则版本、证据、负责人/缺失字段
            row4 = page.locator('.finding-explorer-row', has_text='R-D')
            row4.locator('.finding-explorer-summary').focus()
            page.keyboard.press('Enter')
            expect(row4).to_contain_text('R-D / v1')
            expect(row4).to_contain_text('u-sec')
            expect(row4).to_contain_text('已终态')
            # 终态记录无处置按钮
            expect(row4.get_by_role('button', name='确认', exact=True)).to_have_count(0)
            expect(row4.get_by_role('button', name='解决', exact=True)).to_have_count(0)
            checks['a_keyboard_detail_and_terminal_no_actions'] = True

            # A4. 分页：第二页（含 XSS fixture）、第三页失败保留数据、重试恢复
            page.get_by_role('button', name='加载更多').click()
            expect(page.get_by_text('匹配 6 条 / 已加载 6 条', exact=False).first).to_be_visible()
            assert page.evaluate('window.__xss === undefined')
            expect(page.locator('img[src=x]')).to_have_count(0)
            expect(page.get_by_text('<img src=x onerror=alert(1)>').first).to_be_visible()
            page.get_by_role('button', name='加载更多').click()
            expect(page.get_by_role('alert')).to_contain_text('请求失败（HTTP 500）')
            expect(page.get_by_role('alert')).to_contain_text('已保留此前成功加载的数据')
            expect(page.get_by_text('匹配 6 条 / 已加载 6 条', exact=False).first).to_be_visible()
            state['page3_ok'] = True
            page.get_by_role('button', name='加载更多').click()
            expect(page.get_by_text('匹配 7 条 / 已加载 7 条', exact=False).first).to_be_visible()
            expect(page.get_by_role('button', name='加载更多')).to_have_count(0)
            expect(page.get_by_role('alert')).to_have_count(0)
            assert len(page.locator('.finding-explorer-row').all()) == 7  # 不重复追加
            checks['a_pagination_failure_retry_no_duplicates_xss_text'] = True

            # A5. 组合筛选、无匹配、清除
            page.get_by_role('combobox', name='风险级别', exact=True).select_option('critical')
            expect(page.get_by_text('匹配 1 条 / 已加载 7 条', exact=False).first).to_be_visible()
            page.get_by_role('combobox', name='处置状态', exact=True).select_option('resolved')
            expect(page.get_by_text('匹配 1 条 / 已加载 7 条', exact=False).first).to_be_visible()
            page.get_by_role('searchbox', name='搜索（风险 / 规则 / 资产 / 描述 / 建议）').fill('不存在')
            expect(page.get_by_text('当前筛选条件下无匹配项')).to_be_visible()
            page.get_by_role('button', name='清除筛选').first.click()
            expect(page.get_by_text('匹配 7 条 / 已加载 7 条', exact=False).first).to_be_visible()
            checks['a_filters_no_match_clear'] = True

            # A6. 截图：桌面（含已展开详情）与处置回归前的列表
            row4.locator('.finding-explorer-summary').focus()
            page.keyboard.press('Enter')
            page.screenshot(path=str(args.out_dir / 'desktop-1280.png'), full_page=True, animations='disabled')

            # A7. 五个视口：文档与 .content 均无横向溢出
            overflow = []
            for width in [375, 768, 1024, 1280, 1440]:
                page.set_viewport_size({'width': width, 'height': 900})
                page.wait_for_timeout(150)
                doc_ok = page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                content_ok = page.evaluate(
                    "(() => { const c = document.querySelector('.content');"
                    ' return c && c.scrollWidth <= c.clientWidth + 1; })()')
                if not (doc_ok and content_ok):
                    overflow.append(width)
            assert not overflow, f'横向溢出视口: {overflow}'
            checks['a_no_overflow_five_viewports'] = True
            page.set_viewport_size({'width': 375, 'height': 844})
            page.wait_for_timeout(150)
            page.screenshot(path=str(args.out_dir / 'mobile-375.png'), full_page=True, animations='disabled')
            page.set_viewport_size({'width': 768, 'height': 900})
            page.wait_for_timeout(150)
            page.screenshot(path=str(args.out_dir / 'mid-768.png'), full_page=True, animations='disabled')
            page.set_viewport_size({'width': 1280, 'height': 1000})

            # A8. 空清单与断连区分
            state['mode'] = 'empty'
            page.goto(base)
            expect(page.get_by_text('后端成功返回空列表')).to_be_visible()
            expect(page.get_by_text('零条风险不等于当前系统安全')).to_be_visible()
            state['mode'] = 'down'
            page.goto(base)
            expect(page.get_by_text('未连接 — 控制面暂不可达')).to_be_visible()
            expect(page.get_by_text('后端成功返回空列表')).to_have_count(0)
            expect(page.get_by_role('button', name='确认', exact=True)).to_have_count(0)
            expect(page.get_by_role('button', name='解决', exact=True)).to_have_count(0)
            checks['a_empty_vs_disconnected_no_actions'] = True

            state['mode'] = 'edge-cases'
            page.goto(base)
            expect(page.locator('.finding-explorer-row')).to_have_count(1)
            page.locator('.finding-explorer-summary').click()
            for width in [375, 768, 1024, 1280, 1440]:
                page.set_viewport_size({'width': width, 'height': 900})
                page.wait_for_timeout(100)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), width
                assert page.evaluate("(() => { const c = document.querySelector('.content'); return c.scrollWidth <= c.clientWidth + 1; })()"), width
            checks['a_unknown_enums_long_ids_expanded_no_overflow'] = True
            page.set_viewport_size({'width': 1280, 'height': 1000})

            before_gets = len(list_gets)
            state['access'] = 'denied'
            page.goto(base)
            expect(page.get_by_text('当前账号无法访问此页面', exact=True)).to_be_visible()
            expect(page.locator('a[href="/findings"]')).to_have_count(0)
            expect(page.locator('.finding-explorer-list')).to_have_count(0)
            assert len(list_gets) == before_gets
            state['access'] = 'error'
            page.goto(base)
            expect(page.get_by_text('暂时无法核对访问权限', exact=True)).to_be_visible()
            assert len(list_gets) == before_gets
            state['access'] = 'ready'
            page.get_by_role('button', name='重新核对权限').click()
            expect(page.locator('.finding-explorer-row')).to_have_count(1)
            checks['a_access_denied_identity_error_retry'] = True

            assert not writes, f'只读阶段产生业务写请求: {writes}'
            checks['a_readonly_zero_writes'] = True

            # ---------- 阶段 B：处置回归（写请求仅到模拟拦截） ----------
            state['mode'] = 'paged'
            state['page3_ok'] = False
            page.goto(base)
            row1 = page.locator('.finding-explorer-row', has_text='R-A')

            # B1. 未填写证据不能提交解决；取消弹窗不发写请求
            row1.get_by_role('button', name='解决', exact=True).click()
            expect(page.get_by_text('解决风险「R-A」')).to_be_visible()
            page.get_by_role('button', name='确认解决').click()
            expect(page.get_by_role('alert')).to_contain_text('请填写「修复证据或工单引用」')
            assert not writes
            page.get_by_role('button', name='取消').click()
            assert not writes
            checks['b_resolve_requires_evidence_cancel_no_write'] = True

            # B2. 重新打开并截图弹窗，再以原接口原字段提交
            row1.get_by_role('button', name='解决', exact=True).click()
            page.get_by_label('修复证据或工单引用').fill('repair-ticket:SEC-123')
            page.screenshot(path=str(args.out_dir / 'resolve-dialog.png'), animations='disabled')
            page.get_by_role('button', name='确认解决').click()
            expect(page.get_by_text('解决风险「R-A」')).to_have_count(0)  # 成功后弹窗关闭
            resolve_writes = [w for w in writes if w['path'].endswith('/resolve')]
            assert len(resolve_writes) == 1
            assert resolve_writes[0]['method'] == 'POST'
            assert resolve_writes[0]['path'] == '/api/v1/findings/fnd-1/resolve'
            assert resolve_writes[0]['body'] == {'evidence_ref': 'repair-ticket:SEC-123'}
            assert any('cursor' not in q for q in list_gets[-1:])  # 成功后刷新
            checks['b_resolve_original_api_and_refresh'] = True

            # B3. 合成“确认”成功：原接口 + 刷新
            before = len(writes)
            row1.get_by_role('button', name='确认', exact=True).click()
            page.wait_for_timeout(300)
            ack_writes = [w for w in writes if w['path'].endswith('/acknowledge')]
            assert len(writes) == before + 1 and len(ack_writes) == 1
            assert ack_writes[0]['method'] == 'POST' and ack_writes[0]['path'] == '/api/v1/findings/fnd-1/acknowledge'
            checks['b_acknowledge_original_api_refresh'] = True

            # B4. 合成失败保持错误提示，记录不被标成成功
            state['ack_fail'] = True
            row3 = page.locator('.finding-explorer-row', has_text='R-C')
            row3.get_by_role('button', name='确认', exact=True).click()
            expect(page.get_by_role('alert')).to_contain_text('操作失败')
            expect(row3).to_contain_text('open')  # 状态未被冒充为已确认
            state['ack_fail'] = False
            checks['b_failure_keeps_error_no_fake_success'] = True

            # B5. 终态限制仍成立
            row4b = page.locator('.finding-explorer-row', has_text='R-D')
            expect(row4b.get_by_role('button', name='确认', exact=True)).to_have_count(0)
            expect(row4b.get_by_role('button', name='解决', exact=True)).to_have_count(0)
            expect(row4b.get_by_text('已终态', exact=True)).to_be_visible()
            checks['b_terminal_state_locked'] = True

            assert not errors, f'存在未捕获异常: {errors}'
            checks['no_pageerrors'] = True
            browser.close()
    finally:
        for pending in held:
            try:
                pending.fulfill(status=200, json=[])
            except Exception:
                pass
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    result = {
        'passed': True,
        'checks': checks,
        'mock_writes': writes,
        'mock_writes_note': '阶段 A 只读零写；阶段 B 写请求仅被 Playwright 拦截的模拟响应接收，真实业务写请求始终为零',
        'scope': 'mocked browser only',
        'production_deployed': False,
        'fixture_server_stopped': not worker.is_alive(),
    }
    (args.out_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
