"""Framework tree UI smoke: isolated fixtures only, never production acceptance.

ENT-018-FRAMEWORK-TREE-UI 浏览器冒烟：本地静态服务 + Playwright 拦截合成响应，
不连接真实控制面、IAM 或任何业务数据。需配合 VITE_DEV_MODE=true 的隔离构建
（仅模拟验收，不可发布）。
"""
import argparse
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

NOW = '2026-09-25T00:00:00Z'
INSTANCE_KEY = 'a' * 64
ALL_ACCESS = ['workspace', 'overview', 'agents', 'permissions', 'findings', 'policies',
              'changes', 'runtime_bindings', 'environments', 'audit', 'settings']
ALL_ACTIONS = ['confirm_assets', 'manage_environment', 'enroll_devices',
               'manage_policy', 'propose_change', 'approve_change']


def console_context(environments_access=True):
    # /agents 路由本身要求 agents 权限；这里控制 environments 权限，
    # 使页面可达但框架实例视图权限不足，验证「权限不足不发清单请求」。
    access = dict.fromkeys(ALL_ACCESS, True)
    access['environments'] = environments_access
    return {'schema_version': 'console-context/v1', 'evaluated_at': NOW,
            'tenant': {'id': 'fixture', 'name': 'Fixture'}, 'actor': {'id': 'fixture', 'type': 'user'},
            'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
            'access': access, 'actions': dict.fromkeys(ALL_ACTIONS, False)}


def source_view(asset_id, status='historical_reported_source', device_id='edge-one'):
    view = {'schema_version': 'enterprise-framework-source-view/v1', 'asset_id': asset_id,
            'status': status, 'runtime_status': 'unverified',
            'skill_relationship_status': 'unresolved', 'effective_permissions': None, 'source': None}
    if status == 'historical_reported_source':
        view['source'] = {'framework': 'openclaw', 'instance_key': INSTANCE_KEY,
                          'environment_id': 'env-one', 'device_id': device_id,
                          'device_revoked': device_id == 'edge-two',
                          'config_sha256': 'b' * 64, 'evidence_id': 'ev:one',
                          'observation_id': 'evo-one', 'observed_at': NOW}
    return view


def role(asset_id, name=None, **source_kwargs):
    return {'asset_id': asset_id, 'name': name or f'角色 {asset_id}',
            'reported_framework': 'openclaw', 'asset_status': 'confirmed',
            'framework_source': source_view(asset_id, **source_kwargs)}


def inventory_page(items, next_cursor):
    return {'schema_version': 'enterprise-framework-role-inventory/v1',
            'coverage': 'page_of_tenant_assets', 'items': items, 'next_cursor': next_cursor}


# 第一页：同实例两角色（含 XSS 文本名）+ 无来源记录；第二页：同实例第三角色（跨页合并）、
# 不同设备同 instance_key（不混并，且凭据已吊销）、来源暂不可确认。
def page_one():
    return inventory_page([
        role('agt_a', name='研究助手 <script>window.__xss=1</script>'),
        role('agt_b', name='研究助手 <script>window.__xss=1</script>'),
        role('agt_e', status='no_recorded_source'),
    ], 'agt_e')


def page_two():
    changed_role = role('agt_f')
    changed_role['framework_source']['source'].update(
        config_sha256='c' * 64, evidence_id='ev:second', observation_id='evo-second',
        observed_at='2026-09-24T00:00:00Z')
    return inventory_page([
        changed_role,
        role('agt_g', device_id='edge-two'),
        role('agt_h', status='source_unavailable'),
    ], None)


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
            if self.path.split('?')[0] in ('/agents', '/agents/') or self.path.startswith('/agents/'):
                self.path = '/index.html'
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=args.web))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state = {'environments_access': True, 'page2_fail': False, 'hold_page2': False,
             'inventory_requests': [], 'fresh_after_refresh': False, 'hermes_page': False}
    delayed = []
    violations, errors, checks = [], [], []

    def intercept(route):
        request = route.request
        url = urlparse(request.url)
        if url.hostname != '127.0.0.1' or url.port != server.server_port or request.method != 'GET':
            violations.append(f'unexpected network or write: {request.method} {request.url}')
            route.abort()
            return
        if not url.path.startswith('/api/'):
            route.continue_()
            return
        path = url.path
        status, body = 200, {}
        if path == '/api/v1/console-context':
            body = console_context(state['environments_access'])
        elif path == '/api/v1/framework-role-inventory':
            cursor = parse_qs(url.query).get('cursor', [None])[0]
            state['inventory_requests'].append(cursor)
            if cursor is None:
                body = inventory_page([role('agt_z', name='刷新后角色')], None) \
                    if state['fresh_after_refresh'] else page_one()
            elif cursor == 'agt_e':
                if state['hold_page2']:
                    delayed.append(route)
                    return
                if state['page2_fail']:
                    status, body = 503, {'detail': 'fixture_unavailable'}
                else:
                    body = page_two()
                    if state['hermes_page']:
                        hermes = role('agt_i', name='Hermes 合成角色')
                        hermes['reported_framework'] = 'hermes'
                        hermes['framework_source']['schema_version'] = 'enterprise-framework-source-view/v2'
                        hermes['framework_source']['source']['framework'] = 'hermes'
                        body['items'].append(hermes)
                        body['schema_version'] = 'enterprise-framework-role-inventory/v2'
            else:
                status, body = 400, {'detail': 'bad_cursor'}
        elif path == '/api/v1/agents':
            # playwright 对 json=[] 不设置 Content-Type，需显式 body
            route.fulfill(status=200, content_type='application/json', body='[]')
            return
        elif path == '/api/v1/agents/agt_a':
            body = {'id': 'agt_a', 'name': '合成角色详情', 'framework': 'openclaw',
                    'status': 'confirmed', 'updated_at': NOW, 'attributes': {}, 'evidence_ids': []}
        elif path == '/api/v1/agents/agt_a/evidence':
            route.fulfill(status=200, content_type='application/json', body='[]')
            return
        elif path == '/api/v1/candidates':
            route.fulfill(status=200, content_type='application/json', body='[]')
            return
        elif path == '/api/v1/inventory/access':
            body = {'schema_version': 'inventory-access/v1', 'can_confirm': False,
                    'can_discover': False, 'can_manage_policy': False}
        else:
            status, body = 404, {'detail': 'fixture_unavailable'}
        route.fulfill(status=status, json=body)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 900}, service_workers='block')
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/*', intercept)
            page.goto(f'http://127.0.0.1:{server.server_port}/agents')

            # 默认资产列表行为保留：表格视图在，且未请求框架清单
            expect(page.get_by_role('tab', name='资产清单', exact=False)).to_be_visible()
            expect(page.get_by_text('暂无已确认资产', exact=False)).to_be_visible()
            assert state['inventory_requests'] == []
            checks.append('default_list_view_no_inventory_request')

            # 打开框架实例视图才请求新接口
            page.get_by_role('tab', name='框架实例', exact=True).click()
            tree = page.locator('.framework-tree')
            expect(tree.get_by_text('env-one', exact=True)).to_be_visible()
            expect(tree.get_by_text('已加载 3 条角色记录', exact=False)).to_be_visible()
            assert state['inventory_requests'] == [None]
            checks.append('view_switch_triggers_first_request')

            # 层级折叠 + 键盘展开/折叠 + 详情链接
            env_summary = tree.locator('.framework-tree-env > summary')
            env_summary.focus()
            env_summary.press('Enter')
            expect(tree.locator('.framework-tree-env')).to_have_attribute('open', '')
            device_summary = tree.locator('.framework-tree-device > summary')
            device_summary.press('Enter')
            expect(tree.locator('.framework-tree-device')).to_have_attribute('open', '')
            instance_summary = tree.locator('.framework-tree-instance > summary')
            instance_summary.press('Enter')
            instance = tree.locator('.framework-tree-instance')
            expect(instance).to_have_attribute('open', '')
            expect(instance.get_by_text('已加载 2 个角色（非完整清单）', exact=False)).to_be_visible()
            expect(instance.get_by_text('不代表进程正在运行', exact=False)).to_be_visible()
            link = instance.get_by_role('link', name='查看详情').first
            assert link.get_attribute('href') == '/agents/agt_a?view=framework'
            env_summary.press('Enter')
            expect(tree.locator('.framework-tree-env')).not_to_have_attribute('open', '')
            env_summary.press('Enter')
            checks.append('collapse_keyboard_and_detail_links')

            # XSS 文本不执行
            expect(tree.get_by_text('研究助手', exact=False).first).to_be_visible()
            assert page.evaluate('window.__xss === undefined')
            scripts = page.evaluate(
                'Array.from(document.querySelectorAll("script")).map(s => s.textContent).join("")')
            assert 'bad()' not in scripts and '__xss' not in scripts
            checks.append('xss_text_not_executed')

            # 加载更多：跨页同实例合并；不同设备同 instance_key 不混并；未知来源分两种状态
            tree.get_by_role('button', name='加载更多角色记录').click()
            expect(tree.get_by_text('已加载 6 条角色记录', exact=False)).to_be_visible()
            expect(instance.get_by_text('已加载 3 个角色（非完整清单）', exact=False)).to_be_visible()
            expect(tree.get_by_text('edge-two', exact=True)).to_be_visible()
            expect(tree.get_by_text('设备凭据已吊销，仅保留历史', exact=False)).to_be_visible()
            expect(tree.get_by_text('无来源记录', exact=True)).to_be_visible()
            expect(tree.get_by_text('来源暂不可确认', exact=True)).to_be_visible()
            expect(tree.get_by_text('后端表示没有更多记录', exact=False)).to_be_visible()
            assert state['inventory_requests'] == [None, 'agt_e']
            checks.append('load_more_merge_and_device_separation')

            first_role = tree.locator('.framework-tree-role').filter(has=page.locator('a[href^="/agents/agt_a?"]'))
            changed_role = tree.locator('.framework-tree-role').filter(has=page.locator('a[href^="/agents/agt_f?"]'))
            changed_role.locator('summary').click()
            expect(changed_role).to_contain_text('ev:second')
            expect(changed_role).to_contain_text('c' * 64)
            expect(changed_role).to_contain_text('2026-09-24T00:00:00Z')
            expect(first_role).not_to_contain_text('ev:second')
            checks.append('per_role_provenance_not_first_role_for_entire_instance')

            # 刷新：重新从首页加载，不混合旧页
            state['fresh_after_refresh'] = True
            tree.get_by_role('button', name='刷新框架实例视图').click()
            # 角色在折叠 details 内：断言存在于 DOM，不要求可见
            refreshed_role = tree.locator('.framework-tree-role-name', has_text='刷新后角色')
            expect(refreshed_role).to_have_count(1)
            expect(tree.get_by_text('已加载 1 条角色记录', exact=False)).to_be_visible()
            expect(tree.get_by_text('agt_a', exact=True)).to_have_count(0)
            checks.append('refresh_replaces_without_mixing')

            # 迟到响应：旧「加载更多」挂起 → 刷新成功 → 旧响应失败到达，不覆盖新结果
            state['fresh_after_refresh'] = False
            state['hold_page2'] = True
            tree.get_by_role('button', name='刷新框架实例视图').click()
            expect(tree.get_by_text('已加载 3 条角色记录', exact=False)).to_be_visible()
            tree.get_by_role('button', name='加载更多角色记录').click()
            expect(tree.get_by_role('button', name='正在加载…')).to_be_visible()
            state['fresh_after_refresh'] = True
            tree.get_by_role('button', name='刷新框架实例视图').click()
            # 角色在折叠 details 内：断言存在于 DOM，不要求可见
            refreshed_role = tree.locator('.framework-tree-role-name', has_text='刷新后角色')
            expect(refreshed_role).to_have_count(1)
            state['hold_page2'] = False
            assert len(delayed) == 1
            delayed.pop().fulfill(status=503, json={'detail': 'stale_fixture_failure'})
            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            expect(tree.get_by_role('alert')).to_have_count(0)
            # 角色在折叠 details 内：断言存在于 DOM，不要求可见
            refreshed_role = tree.locator('.framework-tree-role-name', has_text='刷新后角色')
            expect(refreshed_role).to_have_count(1)
            expect(tree.get_by_text('已加载 1 条角色记录', exact=False)).to_be_visible()
            checks.append('stale_response_cannot_override_refresh')

            # 分页失败：保留记录，按同一游标重试成功
            state['fresh_after_refresh'] = False
            state['page2_fail'] = True
            tree.get_by_role('button', name='刷新框架实例视图').click()
            expect(tree.get_by_text('已加载 3 条角色记录', exact=False)).to_be_visible()
            tree.get_by_role('button', name='加载更多角色记录').click()
            expect(tree.get_by_role('alert')).to_contain_text('已加载记录保留')
            expect(tree.get_by_text('已加载 3 条角色记录', exact=False)).to_be_visible()
            state['page2_fail'] = False
            tree.get_by_role('button', name='按同一位置重试').click()
            expect(tree.get_by_text('已加载 6 条角色记录', exact=False)).to_be_visible()
            cursors = state['inventory_requests']
            assert cursors[-3:] == [None, 'agt_e', 'agt_e'], cursors
            checks.append('load_more_failure_keeps_rows_and_retries_same_cursor')

            # 权限不足：不请求清单
            state['environments_access'] = False
            before = len(state['inventory_requests'])
            page.reload()
            expect(page.get_by_role('tab', name='资产清单', exact=False)).to_be_visible()
            page.get_by_role('tab', name='框架实例', exact=True).click()
            expect(page.get_by_text('缺少资产或环境读取权限', exact=False)).to_be_visible()
            assert len(state['inventory_requests']) == before
            checks.append('insufficient_permission_no_request')

            # 恢复权限后检查加载态与空态
            state['environments_access'] = True
            page.reload()
            page.get_by_role('tab', name='框架实例', exact=True).click()
            expect(tree.get_by_text('已加载 3 条角色记录', exact=False)).to_be_visible()
            checks.append('loading_and_loaded_states')

            # 375/768/1280 无横向溢出 + 截图
            for width in (375, 768, 1280):
                page.set_viewport_size({'width': width, 'height': 1000})
                tree.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), width
                assert page.locator('.content').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'), width
                if width != 768:
                    page.screenshot(path=str(args.out / f'framework-tree-{width}.png'), animations='disabled')
            checks.append('responsive_no_overflow_375_768_1280')

            tree.get_by_role('button', name='加载更多角色记录').click()
            expect(tree.get_by_text('已加载 6 条角色记录', exact=False)).to_be_visible()
            for width in (375, 768, 1280):
                page.set_viewport_size({'width': width, 'height': 1000})
                # 同时展开所有层级和逐角色证据，检查真实内容而非仅折叠标题。
                tree.locator('details').evaluate_all('(nodes) => nodes.forEach(node => { node.open = true; })')
                assert page.locator('.content').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'), width
                assert tree.locator('.framework-tree-evidence').evaluate_all(
                    '(nodes) => nodes.every(e => e.scrollWidth <= e.clientWidth + 1)'), width
                if width != 768:
                    page.screenshot(path=str(args.out / f'framework-tree-expanded-{width}.png'), full_page=True,
                                    animations='disabled')
                    role_evidence = tree.locator('.framework-tree-role').filter(
                        has=page.locator('a[href^="/agents/agt_f?"]')).locator('.framework-tree-evidence')
                    role_evidence.scroll_into_view_if_needed()
                    role_evidence.screenshot(path=str(args.out / f'framework-tree-role-evidence-{width}.png'),
                                             animations='disabled')
            checks.append('expanded_role_evidence_no_internal_overflow')

            # 返回与刷新通过既有路由的白名单查询参数恢复视图，不接受任意跳转地址。
            base = f'http://127.0.0.1:{server.server_port}'
            page.goto(base + '/agents?view=framework&environment_id=env-one&device_id=edge-one')
            expect(tree.get_by_text('已加载 3 条角色记录', exact=False)).to_be_visible()
            tree.locator('details').evaluate_all('(nodes) => nodes.forEach(node => { node.open = true; })')
            tree.get_by_role('link', name='查看详情').first.click()
            expect(page.get_by_role('heading', name='合成角色详情', exact=True)).to_be_visible()
            page.get_by_role('link', name='← 返回智能体资产列表').click()
            expect(page.get_by_role('tab', name='框架实例', exact=True)).to_have_attribute('aria-selected', 'true')
            assert parse_qs(urlparse(page.url).query) == {
                'view': ['framework'], 'environment_id': ['env-one'], 'device_id': ['edge-one']}
            page.reload()
            expect(page.get_by_role('tab', name='框架实例', exact=True)).to_have_attribute('aria-selected', 'true')
            page.go_back()
            expect(page.get_by_role('heading', name='合成角色详情', exact=True)).to_be_visible()
            page.go_forward()
            expect(page.get_by_role('tab', name='框架实例', exact=True)).to_have_attribute('aria-selected', 'true')
            checks.append('detail_return_refresh_back_forward_preserve_view_and_filters')

            # 首页仍为 v1；第二页为 v2 且混合两种来源，不能按首版拒绝或按同摘要混组。
            state['hermes_page'] = True
            page.goto(base + '/agents?view=framework')
            expect(tree.get_by_text('已加载 3 条角色记录', exact=False)).to_be_visible()
            tree.get_by_role('button', name='加载更多角色记录').click()
            expect(tree.get_by_text('已加载 7 条角色记录', exact=False)).to_be_visible()
            tree.locator('details').evaluate_all('(nodes) => nodes.forEach(node => { node.open = true; })')
            hermes_instance = tree.locator('.framework-tree-instance').filter(has_text='Hermes 合成角色')
            expect(hermes_instance).to_have_count(1)
            expect(hermes_instance.locator(':scope > summary')).to_contain_text('Hermes profile')
            expect(hermes_instance.locator(':scope > summary')).not_to_contain_text('OpenClaw')
            expect(hermes_instance).to_contain_text(INSTANCE_KEY)
            expect(hermes_instance).not_to_contain_text('研究助手')
            expect(tree.locator('.framework-tree-instance')).to_have_count(3)
            expect(hermes_instance).to_contain_text('不代表进程正在运行')
            for width in (375, 1280):
                page.set_viewport_size({'width': width, 'height': 1000})
                hermes_instance.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), width
                assert page.locator('.content').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'), width
                hermes_instance.screenshot(path=str(args.out / f'framework-tree-hermes-{width}.png'),
                                           animations='disabled')
            checks.append('v1_then_mixed_v2_pages_keep_hermes_separate_same_instance_key')

            assert not violations, violations
            assert not errors, errors
            checks.append('no_write_requests_or_uncaught_errors')
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    report = {'scope': 'isolated-mock-browser-not-production', 'checks': checks,
              'violations': violations, 'errors': errors,
              'inventory_request_cursors': state['inventory_requests']}
    (args.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
