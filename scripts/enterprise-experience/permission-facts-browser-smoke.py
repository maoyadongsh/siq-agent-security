"""ENT-014-UI 权限事实可视化浏览器冒烟：全部 API 均为合成 fixture，仅监听 127.0.0.1。

模拟验收专用：不连接真实控制面，不能证明后端授权或生产环境已验收。
用法：python permission-facts-browser-smoke.py --web <构建目录> --out-dir <证据目录>
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


def fact(**overrides):
    row = {
        'id': 'pf-x', 'environment_id': 'env-1', 'subject_type': 'agent_instance',
        'subject_id': 'subject-a', 'delegated_user': None, 'domain': 'filesystem',
        'action': 'fs.read', 'resource_type': 'path', 'resource_value': '/data/a',
        'effect': 'allow', 'conditions': {}, 'state': 'declared', 'authority': 'siq-iam',
        'authority_revision': 'r1', 'evidence_ids': ['ev-1'],
        'valid_from': None, 'valid_until': None,
    }
    row.update(overrides)
    return row


PAGE1 = [
    fact(id='pf-declared', state='declared', authority='openshell', domain='filesystem',
         action='fs.write', resource_value='/var/lib/app/data',
         valid_from='2026-09-01T00:00:00Z', valid_until='2026-12-31T00:00:00Z'),
    fact(id='pf-inferred', state='inferred', authority='siq-iam', domain='network',
         action='http.request', resource_value='internal-api:8080'),
    fact(id='pf-observed', state='observed', authority='os', domain='process',
         action='process.exec', resource_value='/usr/bin/curl',
         valid_from='2026-12-01T00:00:00Z'),  # 未来生效
    fact(id='pf-effective-expired', state='effective', authority='openshell', domain='model',
         action='model.generate', resource_value='gpt-fixture-model',
         authority_revision='rev-42', evidence_ids=['ev-0001', 'ev-0002'],
         valid_from='2026-01-01T00:00:00Z', valid_until='2026-06-01T00:00:00Z'),  # 已过期
]
PAGE2 = [
    fact(id='pf-unknown', state='unknown', authority='container', domain='credential',
         action='credential.read', resource_value='cred-ref-1',
         valid_from='not-a-date'),
    fact(id='pf-malicious', state='declared', authority='siq-iam', domain='tool',
         action='tool.invoke', subject_id='<script>window.__xss=1</script>',
         resource_value='<img src=x onerror=alert(1)>',
         environment_id=None, authority_revision=None, evidence_ids=[],
         resource_type='tool_name_very_long_' + 'x' * 60),
]
PAGE3 = [
    fact(id='pf-final', state='effective', authority='siq-gateway', domain='data_scope',
         action='data.read', resource_value='tenant/fixture-scope',
         valid_from='2026-09-01T00:00:00Z', valid_until='2026-10-01T00:00:00Z'),
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
            if self.path.startswith('/permissions'):
                self.path = '/index.html'
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(args.web.resolve())))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()

    state = {'mode': 'paged', 'writes': 0, 'page3_ok': False}
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
        if request.request.method != 'GET':
            state['writes'] += 1
            request.fulfill(status=403, json={'detail': 'fixture denies mutations'})
            return
        path = urlparse(request.request.url).path
        query = parse_qs(urlparse(request.request.url).query)
        if path.endswith('/console-context'):
            request.fulfill(status=200, json={
                'schema_version': 'console-context/v1', 'evaluated_at': NOW,
                'tenant': {'id': 'fixture', 'name': 'Fixture'},
                'actor': {'id': 'fixture', 'type': 'user'},
                'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
                'access': dict.fromkeys(['workspace', 'overview', 'agents', 'permissions', 'findings',
                                         'policies', 'changes', 'runtime_bindings', 'environments',
                                         'audit', 'settings'], True),
                'actions': dict.fromkeys(['confirm_assets', 'manage_environment', 'enroll_devices',
                                          'manage_policy', 'propose_change', 'approve_change'], False)})
            return
        if path.endswith('/environments'):
            request.fulfill(status=200, json=[
                {'id': 'env-1', 'name': 'Fixture Linux', 'env_type': 'host', 'mode': 'observe'}])
            return
        if path.endswith('/permissions'):
            if state['mode'] == 'hold':
                held.append(request)
                return
            if state['mode'] == 'down':
                request.fulfill(status=502, json={'detail': 'fixture backend down'})
                return
            if state['mode'] == 'empty':
                fulfill_list(request, [], False)
                return
            if state['mode'] == 'unknown-enums':
                fulfill_list(request, [fact(id=f'unknown-{index}', state=value, domain=value,
                                           subject_type=value, effect=value)
                                       for index, value in enumerate(['__proto__', 'constructor', 'toString'])], False)
                return
            cursor = query.get('cursor', [None])[0]
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
            page.clock.install()

            # 1. 加载中不得展示成功零值
            state['mode'] = 'hold'
            page.goto(f'http://127.0.0.1:{server.server_port}/permissions')
            expect(page.get_by_text('正在加载权限事实')).to_be_visible()
            expect(page.get_by_label('权限事实状态概览（仅统计已加载记录）')).to_have_count(0)
            checks['loading_shows_no_zero_success'] = True

            # 2. 连接后：五态、计数、过期 effective 文案
            state['mode'] = 'paged'
            held.pop().fulfill(status=200, json=PAGE1, headers={
                'Content-Type': 'application/json',
                'X-SIQ-List-Limit': '4', 'X-SIQ-List-Returned': '4',
                'X-SIQ-List-Truncated': '1', 'X-SIQ-Next-Cursor': 'c2'})
            overview = page.get_by_label('权限事实状态概览（仅统计已加载记录）')
            expect(overview).to_contain_text('已加载 4 条记录')
            for label in ['声明', '推断', '观测', '生效', '未知']:
                expect(overview).to_contain_text(label)
            expect(page.get_by_text('不代表组织全量')).to_be_visible()
            expect(page.get_by_text('匹配 4 条 / 已加载 4 条。')).to_be_visible()
            expect(page.get_by_text('存在更多分页未加载')).to_be_visible()
            expect(page.get_by_text('已过期', exact=False).first).to_be_visible()
            expect(page.get_by_text('尚未到生效时间').first).to_be_visible()
            body = page.text_content('body')
            assert '全面保护' not in body and '阻断已验证' not in body
            checks['five_states_and_expired_effective_wording'] = True

            # 3. 键盘展开详情：revision、证据 ID、未来生效提示
            summary = page.locator('.pf-item-summary', has_text='model.generate')
            summary.focus()
            page.keyboard.press('Enter')
            detail = page.locator('.pf-item', has_text='model.generate')
            expect(detail).to_contain_text('rev-42')
            expect(detail).to_contain_text('ev-0001')
            expect(detail).to_contain_text('已过期')
            expect(detail).to_contain_text('生效状态不等于已通过行为阻断验证')
            checks['keyboard_detail_revision_evidence'] = True

            # 4. 加载更多第二页：恶意字符串仅作文本；缺失字段提示
            page.get_by_role('button', name='加载更多').click()
            expect(page.get_by_text('匹配 6 条 / 已加载 6 条。')).to_be_visible()
            assert page.evaluate('window.__xss === undefined')
            expect(page.locator('img[src=x]')).to_have_count(0)
            bad = page.locator('.pf-item', has_text='tool.invoke')
            bad.locator('.pf-item-summary').focus()
            page.keyboard.press('Enter')
            expect(bad).to_contain_text('<script>window.__xss=1</script>')
            expect(bad).to_contain_text('未提供')
            unknown = page.locator('.pf-item', has_text='credential.read')
            unknown.locator('.pf-item-summary').focus()
            page.keyboard.press('Enter')
            expect(unknown).to_contain_text('有效期信息异常：日期格式无效')
            checks['xss_text_only_and_missing_fields'] = True

            # 5. 加载更多失败：保留已有数据并显示错误
            page.get_by_role('button', name='加载更多').click()
            expect(page.get_by_role('alert')).to_contain_text('请求失败（HTTP 500）')
            expect(page.get_by_role('alert')).to_contain_text('已保留此前成功加载的数据')
            expect(page.get_by_text('匹配 6 条 / 已加载 6 条。')).to_be_visible()
            checks['load_more_failure_keeps_data_with_error'] = True

            # 6. 重试成功
            state['page3_ok'] = True
            page.get_by_role('button', name='加载更多').click()
            expect(page.get_by_text('匹配 7 条 / 已加载 7 条。')).to_be_visible()
            expect(page.get_by_role('button', name='加载更多')).to_have_count(0)
            expect(page.get_by_role('alert')).to_have_count(0)
            checks['retry_success_clears_previous_error'] = True
            checks['load_more_retry_success'] = True

            # 7. 组合筛选与清除
            page.get_by_role('combobox', name='事实状态', exact=True).select_option('effective')
            expect(page.get_by_text('匹配 2 条 / 已加载 7 条。')).to_be_visible()
            page.get_by_role('combobox', name='权限域', exact=True).select_option('model')
            expect(page.get_by_text('匹配 1 条 / 已加载 7 条。')).to_be_visible()
            page.get_by_role('searchbox', name='搜索（主体 / 动作 / 资源 / 来源）').fill('不存在')
            expect(page.get_by_text('当前筛选条件下无匹配项')).to_be_visible()
            page.get_by_role('button', name='清除筛选').first.click()
            expect(page.get_by_text('匹配 7 条 / 已加载 7 条。')).to_be_visible()
            checks['combined_filters_and_clear'] = True

            # Check the scroll container too: document width can hide internal overflow.
            for width in (375, 768, 1024, 1280, 1440):
                page.set_viewport_size({'width': width, 'height': 1000})
                page.clock.run_for(100)
                sizes = page.evaluate('''() => {
                    const content = document.querySelector('.content');
                    return {viewport: innerWidth, document: document.documentElement.scrollWidth,
                            available: content.clientWidth, actual: content.scrollWidth};
                }''')
                assert sizes['document'] <= sizes['viewport'] + 1, sizes
                assert sizes['actual'] <= sizes['available'] + 1, sizes
                checks[f'content_{width}_no_overflow'] = True
                if width in (375, 768, 1024):
                    page.locator('.pf-item-summary').first.scroll_into_view_if_needed()
                    page.screenshot(path=str(args.out_dir / f'medium-{width}.png'), animations='disabled')
                    page.locator('.content').evaluate('(element) => { element.scrollTop = 0; }')
            page.set_viewport_size({'width': 1280, 'height': 1000})

            page.screenshot(path=str(args.out_dir / 'desktop.png'), full_page=True, animations='disabled')

            # 8. 375px：无横向溢出，卡片可读
            page.set_viewport_size({'width': 375, 'height': 844})
            page.clock.run_for(100)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            page.screenshot(path=str(args.out_dir / 'mobile.png'), full_page=True, animations='disabled')
            checks['mobile_375_no_overflow'] = True
            page.set_viewport_size({'width': 1280, 'height': 1000})

            # 9. 后端成功返回空列表（区别于断连与无匹配）
            state['mode'] = 'empty'
            page.goto(f'http://127.0.0.1:{server.server_port}/permissions')
            expect(page.get_by_text('后端成功返回空列表')).to_be_visible()
            checks['empty_list_distinct'] = True

            # 10. 断连：明确失败，不冒充空清单
            state['mode'] = 'down'
            page.goto(f'http://127.0.0.1:{server.server_port}/permissions')
            expect(page.get_by_text('未连接 — 控制面暂不可达')).to_be_visible()
            expect(page.get_by_text('后端成功返回空列表')).to_have_count(0)
            checks['disconnect_not_empty_list'] = True

            state['mode'] = 'unknown-enums'
            page.goto(f'http://127.0.0.1:{server.server_port}/permissions')
            expect(page.get_by_label('未知 3 条', exact=True)).to_be_visible()
            expect(page.locator('.pf-item')).to_have_count(3)
            page.locator('.pf-item-summary').first.click()
            expect(page.get_by_text('未识别的事实状态，不得视为已生效', exact=False).first).to_be_visible()
            checks['unknown_prototype_names_counted_and_rendered'] = True

            assert state['writes'] == 0, f"只读流程产生写请求: {state['writes']}"
            assert not errors, f'存在未捕获异常: {errors}'
            checks['no_writes_no_pageerrors'] = True
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
    result = {'passed': True, 'checks': checks, 'scope': 'mocked browser only',
              'production_deployed': False, 'fixture_server_stopped': not worker.is_alive()}
    (args.out_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
