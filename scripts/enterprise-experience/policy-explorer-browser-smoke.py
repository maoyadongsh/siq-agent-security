"""ENT-018-POLICIES-UI 策略中心浏览器冒烟：全部 API 均为合成 fixture，仅监听 127.0.0.1。

分两阶段：
A. 只读场景（筛选/详情/分页/视口/权限直达）：断言业务写请求为 0；
B. 创建回归（新建策略表单）：POST 仅被 Playwright mock 拦截，逐条断言方法、路径与完整载荷。
模拟验收专用：不连接真实控制面，不构成真实策略创建或生产验收。
用法：python policy-explorer-browser-smoke.py --web <构建目录> --out-dir <证据目录>
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


def policy(**overrides):
    row = {
        'id': 'pol-x', 'name': '测试策略', 'selector': {'agent_ids': ['agt-1']},
        'enforcement_mode': 'warn', 'version': 1, 'status': 'draft',
        'unsupported_by_backend': [], 'updated_at': NOW,
    }
    row.update(overrides)
    return row


PAGE1 = [
    policy(id='pol-1', name='财务智能体网络策略', enforcement_mode='block', status='approved',
           selector={'agent_ids': ['agt-finance-01']}, version=3),
    policy(id='pol-2', name='研发审计策略', enforcement_mode='audit_only', status='draft',
           selector={'agent_ids': ['agt-dev-01', 'agt-dev-02', 'agt-dev-01']}),
    policy(id='pol-3', name='告警策略', enforcement_mode='warn', status='deploying',
           selector={'agent_ids': ['agt-ops-01']}, unsupported_by_backend=['process.seccomp_profile']),
    policy(id='pol-4', name='旧版阻断策略', enforcement_mode='block', status='superseded',
           selector={'agent_ids': []}, unsupported_by_backend=['tool_policies', 'data_scope_refs']),
]
PAGE2 = [
    policy(id='pol-5', name='<script>window.__xss=1</script>', enforcement_mode='mystery_mode',
           status='pending_review_custom', selector={'agent_ids': 'not-an-array'}),
    policy(id='pol-6', name='超长策略名称' + '很长' * 30, enforcement_mode='warn',
           status='active', selector={},
           unsupported_by_backend=['a' * 80]),
]
PAGE3 = [
    policy(id='pol-7', name='业务范围策略', enforcement_mode='audit_only', status='active',
           selector={'agent_ids': [], 'labels': {'team': 'secret-team'}, 'system_ref': 'secret-sys'}),
]


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
            if self.path.startswith('/policies'):
                self.path = '/index.html'
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(args.web.resolve())))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    state = {'mode': 'paged', 'page3_ok': False, 'create_fail': False, 'access': True}
    writes = []
    console_errors = []
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
        path = urlparse(request.request.url).path
        if method != 'GET':
            try:
                body = request.request.post_data_json
            except Exception:
                body = request.request.post_data
            writes.append({'method': method, 'path': path, 'body': body})
            if path.endswith('/policies') and method == 'POST':
                if state['create_fail']:
                    request.fulfill(status=500, json={'detail': 'fixture create failure'})
                else:
                    request.fulfill(status=200, json=policy(id='pol-created',
                                                          name=(body or {}).get('name', 'fixture')))
                return
            request.fulfill(status=403, json={'detail': 'fixture denies mutations'})
            return
        if path.endswith('/console-context'):
            access = dict.fromkeys(['workspace', 'overview', 'agents', 'permissions', 'findings',
                                    'policies', 'changes', 'runtime_bindings', 'environments',
                                    'audit', 'settings'], True)
            if not state['access']:
                access['policies'] = False
            request.fulfill(status=200, json={
                'schema_version': 'console-context/v1', 'evaluated_at': NOW,
                'tenant': {'id': 'fixture', 'name': 'Fixture'},
                'actor': {'id': 'fixture', 'type': 'user'},
                'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
                'access': access,
                'actions': dict.fromkeys(['confirm_assets', 'manage_environment', 'enroll_devices',
                                          'manage_policy', 'propose_change', 'approve_change'], False)})
            return
        if path.endswith('/policies'):
            if state['mode'] == 'hold':
                held.append(request)
                return
            if state['mode'] == 'down':
                request.fulfill(status=502, json={'detail': 'fixture backend down'})
                return
            if state['mode'] == 'empty':
                fulfill_list(request, [], False)
                return
            cursor = parse_qs(urlparse(request.request.url).query).get('cursor', [None])[0]
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
            page.on('console', lambda msg: console_errors.append(msg.text)
                    if msg.type == 'error' and 'same key' in msg.text else None)
            page.route('**/api/v1/**', route)
            base = f'http://127.0.0.1:{server.server_port}/policies'

            # ---------- 阶段 A：只读（零业务写请求） ----------
            state['mode'] = 'hold'
            page.goto(base)
            expect(page.get_by_text('正在加载策略')).to_be_visible()
            expect(page.get_by_text('匹配 0 条', exact=False)).to_have_count(0)
            expect(page.locator('.policy-explorer-item')).to_have_count(0)
            checks['a_loading_no_fake_zero'] = True

            state['mode'] = 'paged'
            held.pop().fulfill(status=200, json=PAGE1, headers={
                'Content-Type': 'application/json', 'X-SIQ-List-Limit': '4',
                'X-SIQ-List-Returned': '4', 'X-SIQ-List-Truncated': '1', 'X-SIQ-Next-Cursor': 'c2'})
            expect(page.get_by_text('匹配 4 条 / 已加载 4 条；筛选仅覆盖已加载记录，不代表组织全量。')).to_be_visible()
            # block 档位显示「期望：阻断」，无 effective 样式
            expect(page.get_by_text('期望：阻断').first).to_be_visible()
            assert page.locator('.state-tag.effective').count() == 0
            checks['a_block_not_effective'] = True

            # 键盘 Tab 焦点可见 + Enter 展开详情
            for _ in range(40):
                page.keyboard.press('Tab')
                if page.evaluate("document.activeElement && document.activeElement.classList.contains('policy-explorer-summary')"):
                    break
            assert page.evaluate("document.activeElement.classList.contains('policy-explorer-summary')")
            outline = page.evaluate("getComputedStyle(document.activeElement).outlineStyle")
            assert outline != 'none', '焦点无可见 outline'
            page.keyboard.press('Enter')
            row1 = page.locator('.policy-explorer-row', has_text='财务智能体网络策略')
            expect(row1).to_contain_text('pol-1')
            expect(row1).to_contain_text('agt-finance-01')
            expect(row1).to_contain_text('期望：阻断（block）')
            expect(row1).to_contain_text('实际生效情况需结合审批、部署及独立后端读回核对')
            checks['a_keyboard_focus_detail'] = True
            page.screenshot(path=str(args.out_dir / 'desktop-1280-detail.png'), full_page=True,
                            animations='disabled')

            # 分页失败保留记录，重试成功且错误清除
            page.get_by_role('button', name='加载更多').click()
            expect(page.get_by_text('匹配 6 条 / 已加载 6 条', exact=False).first).to_be_visible()
            page.get_by_role('button', name='加载更多').click()
            expect(page.get_by_role('alert')).to_contain_text('请求失败（HTTP 500）')
            expect(page.get_by_role('alert')).to_contain_text('已保留此前成功加载的数据')
            expect(page.get_by_text('匹配 6 条 / 已加载 6 条', exact=False).first).to_be_visible()
            state['page3_ok'] = True
            page.get_by_role('button', name='加载更多').click()
            expect(page.get_by_text('匹配 7 条 / 已加载 7 条', exact=False).first).to_be_visible()
            expect(page.get_by_role('alert')).to_have_count(0)  # 重试成功清除错误
            expect(page.get_by_role('button', name='加载更多')).to_have_count(0)
            checks['a_pagination_failure_retry_clears_error'] = True

            # 未知枚举、selector 异常、XSS 文本、空 agent_ids、labels 不展示
            assert page.evaluate('window.__xss === undefined')
            expect(page.locator('img[src=x]')).to_have_count(0)
            row5 = page.locator('.policy-explorer-row', has_text='pol-5'.replace('pol-5', 'pending_review_custom'))
            expect(row5).to_contain_text('pending_review_custom')
            expect(row5).to_contain_text('期望：mystery_mode')
            row5.locator('.policy-explorer-summary').focus()
            page.keyboard.press('Enter')
            expect(row5).to_contain_text('格式异常')
            row7 = page.locator('.policy-explorer-row', has_text='业务范围策略')
            row7.locator('.policy-explorer-summary').focus()
            page.keyboard.press('Enter')
            expect(row7).to_contain_text('空列表（不代表全部资产）')
            body_text = page.text_content('body')
            assert 'secret-team' not in body_text and 'secret-sys' not in body_text
            assert not console_errors, f'React key 警告: {console_errors}'
            checks['a_unknown_enum_selector_anomaly_xss'] = True

            # 组合筛选 / 无匹配 / 清除
            page.get_by_role('combobox', name='期望执行档位', exact=True).select_option('block')
            expect(page.get_by_text('匹配 2 条 / 已加载 7 条', exact=False).first).to_be_visible()
            page.get_by_role('combobox', name='策略状态', exact=True).select_option('superseded')
            expect(page.get_by_text('匹配 1 条 / 已加载 7 条', exact=False).first).to_be_visible()
            page.get_by_role('combobox', name='后端未覆盖项', exact=True).select_option('empty')
            expect(page.get_by_text('匹配 0 条 / 已加载 7 条', exact=False).first).to_be_visible()
            expect(page.get_by_text('当前筛选条件下无匹配项')).to_be_visible()
            page.get_by_role('button', name='清除筛选').first.click()
            expect(page.get_by_text('匹配 7 条 / 已加载 7 条', exact=False).first).to_be_visible()
            page.get_by_role('searchbox', name='搜索（名称 / 策略 ID / 目标资产 ID）').fill('agt-finance-01')
            expect(page.get_by_text('匹配 1 条 / 已加载 7 条', exact=False).first).to_be_visible()
            page.get_by_role('button', name='清除筛选').first.click()
            checks['a_filters_search_clear'] = True

            # 空列表与失败区分
            state['mode'] = 'empty'
            page.goto(base)
            expect(page.get_by_text('后端成功返回空列表')).to_be_visible()
            state['mode'] = 'down'
            page.goto(base)
            expect(page.get_by_text('未连接 — 控制面暂不可达')).to_be_visible()
            expect(page.get_by_text('后端成功返回空列表')).to_have_count(0)
            checks['a_empty_vs_down'] = True

            # 无页面权限：导航链接消失、直达被拒
            state['access'] = False
            state['mode'] = 'paged'
            page.goto(base)
            expect(page.get_by_text('当前账号无法访问此页面')).to_be_visible()
            expect(page.locator('nav').get_by_text('策略中心')).to_have_count(0)
            expect(page.locator('.policy-explorer-item')).to_have_count(0)
            checks['a_no_access_no_link_direct_denied'] = True
            state['access'] = True

            # 五视口无横向溢出（文档 + .content）
            page.goto(base)
            expect(page.get_by_text('匹配 4 条 / 已加载 4 条', exact=False).first).to_be_visible()
            row1b = page.locator('.policy-explorer-row', has_text='旧版阻断策略')
            row1b.locator('.policy-explorer-summary').focus()
            page.keyboard.press('Enter')
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
            page.set_viewport_size({'width': 1280, 'height': 1000})

            assert not writes, f'只读阶段产生业务写请求: {writes}'
            checks['a_readonly_zero_writes'] = True

            # ---------- 阶段 B：创建回归（POST 仅到 mock） ----------
            page.goto(base)
            expect(page.get_by_text('匹配 4 条 / 已加载 4 条', exact=False).first).to_be_visible()

            # B1. 原有字段/默认值/必填：名称空时按钮禁用
            state['page3_ok'] = False
            page.get_by_role('button', name='加载更多').click()
            expect(page.get_by_text('匹配 6 条 / 已加载 6 条', exact=False).first).to_be_visible()
            page.get_by_role('button', name='加载更多').click()
            expect(page.get_by_role('alert')).to_contain_text('请求失败（HTTP 500）')
            page.get_by_role('button', name='新建策略').click()
            create_btn = page.get_by_role('button', name='创建', exact=True)
            expect(create_btn).to_be_disabled()
            page.get_by_label('名称', exact=True).fill('财务智能体网络策略 v2')
            page.get_by_label('目标资产', exact=True).fill('agt-finance-02')
            page.get_by_label('网络端点（host:port，留空=无网络规则）').fill('api.example.com:443')
            # 默认档位保持 block（原语义）
            create_btn.click()
            expect(page.get_by_role('button', name='新建策略')).to_be_visible()
            assert len(writes) == 1
            w = writes[0]
            assert w['method'] == 'POST' and w['path'] == '/api/v1/policies'
            assert w['body'] == {
                'name': '财务智能体网络策略 v2',
                'selector': {'agent_ids': ['agt-finance-02']},
                'network': [{'endpoint': 'api.example.com:443', 'effect': 'allow',
                             'binary_paths': ['/usr/bin/curl'], 'purpose': 'web-created'}],
                'enforcement_mode': 'block',
            }, f"载荷偏离原语义: {w['body']}"
            checks['b_create_success_original_payload'] = True
            expect(page.get_by_text('匹配 4 条 / 已加载 4 条', exact=False).first).to_be_visible()
            expect(page.get_by_role('alert')).to_have_count(0)
            checks['b_success_refresh_clears_previous_pagination_error'] = True

            # B2. 端点留空：network 键不出现在载荷
            page.get_by_role('button', name='新建策略').click()
            page.get_by_label('名称', exact=True).fill('无端点策略')
            page.get_by_label('目标资产', exact=True).fill('agt-x')
            page.get_by_role('button', name='创建', exact=True).click()
            expect(page.get_by_role('button', name='新建策略')).to_be_visible()
            assert len(writes) == 2
            assert 'network' not in writes[1]['body'], f"空端点不应带 network: {writes[1]['body']}"
            assert writes[1]['body']['enforcement_mode'] == 'block'
            checks['b_create_empty_endpoint_no_network_key'] = True

            # B3. 创建失败：错误提示，表单不关闭
            state['create_fail'] = True
            page.get_by_role('button', name='新建策略').click()
            page.get_by_label('名称', exact=True).fill('失败策略')
            page.get_by_label('目标资产', exact=True).fill('agt-y')
            page.get_by_role('button', name='创建', exact=True).click()
            expect(page.get_by_text('请求失败（HTTP 500）')).to_be_visible()
            expect(page.get_by_label('名称', exact=True)).to_be_visible()  # 表单仍开着
            state['create_fail'] = False
            assert len(writes) == 3
            checks['b_create_failure_keeps_form_and_error'] = True

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
        'mock_writes_note': '阶段 A 只读零写；阶段 B 的 POST 全部被 Playwright mock 拦截，没有真实策略创建',
        'scope': 'mocked browser only',
        'production_deployed': False,
        'fixture_server_stopped': not worker.is_alive(),
    }
    (args.out_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
