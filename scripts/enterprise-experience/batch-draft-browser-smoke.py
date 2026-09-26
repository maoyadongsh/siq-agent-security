"""Synthetic batch selection/preview/readback only; never contacts real business services."""
import argparse
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--web', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    from pathlib import Path
    out = Path(args.out)
    out.mkdir(exist_ok=False)

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if self.path.startswith(('/changes', '/permissions')):
                self.path = '/index.html'
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=args.web))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    draft = {'schema_version': 'enterprise-batch-draft/v1', 'id': 'draft1', 'state': 'previewed',
             'submission_supported': False, 'created_at': '2026-09-25T00:00:00Z',
             'expires_at': '2026-09-25T00:05:00Z', 'preview': {
                 'schema_version': 'enterprise-deployment-batch-preview/v1', 'preview_digest': 'a' * 64,
                 'batch_submission_supported': False, 'items': []}}
    writes, errors, impact_reads = [], [], []
    saved = {'result': None, 'review_mode': 'ok', 'impact_mode': 'ok', 'proposal_calls': 0, 'can_propose': True, 'recovery_state': 'proposed', 'policy_reads': 0, 'policy_list_ok': False}

    def route(r):
        path = urlparse(r.request.url).path
        if path == '/api/v1/deployment-preview/impact' and r.request.method == 'POST':
            body = r.request.post_data_json
            impact_reads.append(body)
            assert set(body) == {'schema_version', 'change_request_id', 'environment_id', 'binding_id', 'preview_digest'}
            item = next(value for value in draft['preview']['items'] if value['change_id'] == body['change_request_id'])
            assert body['preview_digest'] == item['preview_digest']
            if saved['impact_mode'] == 'denied':
                return r.fulfill(status=403, json={'detail': 'forbidden'})
            return r.fulfill(json={'schema_version': 'enterprise-deployment-impact/v1', 'preview': item,
                'registered_subject': {'binding_id': item['binding_id'], 'environment_id': item['environment_id'],
                                       'asset_id': 'asset-fixture', 'agent_instance_id': 'instance-fixture'},
                'coverage': 'registered_binding_only', 'shared_runtime_occupants': 'unknown',
                'skill_isolation': 'not_established', 'execution_confirmation_supported': False,
                'impact_digest': 'c' * 64})
        if r.request.method != 'GET':
            writes.append({'path': path, 'body': r.request.post_data_json})
            if path == '/api/v1/network-revoke-batches':
                body = r.request.post_data_json
                assert set(body) == {'schema_version', 'request_key', 'items'}
                if 'batch_body' not in saved:
                    saved['batch_body'] = body
                    return r.abort('failed')
                assert saved['batch_body'] == body
                return r.fulfill(status=201, json={'schema_version': 'enterprise-network-revoke-batch-result/v1',
                    'requires_independent_approval': True, 'executed': False,
                    'items': [{'schema_version': 'enterprise-network-revoke-proposal-result/v1',
                        'source_policy_id': item['policy_id'], 'policy_id': 'batch-new-' + item['policy_id'],
                        'change_request_id': 'batch-cr-' + item['policy_id'],
                        'requires_independent_approval': True, 'executed': False} for item in body['items']]})
            if path == '/api/v1/policies/p1/network-revoke-proposals':
                saved['proposal_calls'] += 1
                if saved['proposal_calls'] == 1:
                    return r.abort('failed')  # Synthetic lost response; never reaches a real backend.
                return r.fulfill(status=201, json={'schema_version': 'enterprise-network-revoke-proposal-result/v1',
                    'source_policy_id': 'p1', 'policy_id': 'p2', 'change_request_id': 'c-new',
                    'requires_independent_approval': True, 'executed': False})
            if path == '/api/v1/deployment-batch-drafts':
                body = r.request.post_data_json
                draft['preview']['items'] = [{
                    'schema_version': 'deployment-preview/v1', 'change_id': item['change_request_id'],
                    'environment_id': item['environment_id'], 'binding_id': item['binding_id'],
                    'policy_id': 'p1', 'policy_name': 'Fixture policy', 'policy_version': 1,
                    'enforcement_mode': 'block', 'environment_name': 'Fixture', 'target': item['binding_id'],
                    'backend': 'fake', 'action': 'development_task', 'base_revision': None,
                    'preview_digest': str(index + 1) * 64,
                } for index, item in enumerate(body['items'])]
                return r.fulfill(status=201, json=draft)
            return r.fulfill(status=403, json={'detail': 'fixture denies execution'})
        if path.endswith('/console-context'):
            return r.fulfill(json={'schema_version': 'console-context/v1', 'evaluated_at': '2026-09-25T00:00:00Z',
                'tenant': {'id': 'fixture', 'name': 'Fixture'}, 'actor': {'id': 'fixture', 'type': 'user'},
                'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
                'access': dict.fromkeys(['workspace', 'overview', 'agents', 'permissions', 'findings', 'policies',
                                        'changes', 'runtime_bindings', 'environments', 'audit', 'settings'], True),
                'actions': {**dict.fromkeys(['confirm_assets', 'manage_environment', 'enroll_devices',
                                         'manage_policy', 'propose_change', 'approve_change'], True),
                            'propose_change': saved['can_propose']}})
        if path.endswith('/change-requests'):
            return r.fulfill(json=[{'id': f'c{n}', 'policy_id': 'p1', 'status': 'approved',
                'proposer_user_id': 'proposer', 'approver_user_id': 'independent-reviewer',
                'created_at': '2026-09-25T00:00:00Z'} for n in [1, 2]])
        if path == '/api/v1/permissions':
            return r.fulfill(json=[], headers={'Content-Type': 'application/json'})
        if path.startswith('/api/v1/network-revoke-batches/'):
            if 'batch_body' not in saved:
                return r.fulfill(status=404, json={'detail': 'not_found'})
            return r.fulfill(json={'schema_version': 'enterprise-network-revoke-batch-recovery/v1',
                'lookup_executed': False, 'items': [{'source_policy_id': item['policy_id'],
                    'policy_id': 'batch-new-' + item['policy_id'], 'change_request_id': 'batch-cr-' + item['policy_id'],
                    'change_status': 'approved' if index == 0 else 'proposed'}
                    for index, item in enumerate(saved['batch_body']['items'])]})
        if path == '/api/v1/policies/p-other/network-revoke-options':
            if not saved.get('batch_options_ok'):
                return r.fulfill(status=503, json={'detail': 'fixture unavailable'})
            return r.fulfill(json={'schema_version': 'enterprise-network-revoke-options/v1', 'policy_id': 'p-other',
                'policy_version': 3, 'baseline_digest': 'e' * 64, 'coverage': 'complete_policy_network',
                'selections': [{'endpoint': 'other.example:443', 'binary_path': '/bin/a'}]})
        if path == '/api/v1/policies':
            saved['policy_reads'] += 1
            if not saved['policy_list_ok']:
                return r.fulfill(status=503, json={'detail': 'fixture list unavailable'})
            return r.fulfill(json=[{'id': 'p1', 'name': 'Fixture policy', 'version': 1},
                                  {'id': 'p-other', 'name': 'Other policy', 'version': 3},
                                  {'id': 'p-duplicate', 'name': 'Ambiguous old', 'version': 1},
                                  {'id': 'p-duplicate', 'name': 'Ambiguous new', 'version': 2}])
        if path == '/api/v1/policies/p1/network-revoke-options':
            return r.fulfill(json={'schema_version': 'enterprise-network-revoke-options/v1', 'policy_id': 'p1',
                'policy_version': 1, 'baseline_digest': 'd' * 64, 'coverage': 'complete_policy_network',
                'selections': [{'endpoint': 'a.example:443', 'binary_path': '/bin/a'},
                               {'endpoint': 'b.example:443', 'binary_path': '/bin/b'}]})
        if path.startswith('/api/v1/policies/p1/network-revoke-proposals/'):
            if not saved['proposal_calls']:
                return r.fulfill(status=404, json={'detail': 'not_found'})
            return r.fulfill(json={'schema_version': 'enterprise-network-revoke-recovery/v1',
                'source_policy_id': 'p1', 'policy_id': 'p2', 'change_request_id': 'c-new',
                'change_status': saved['recovery_state'], 'lookup_executed': False})
        if path.startswith('/api/v1/change-requests/') and path.endswith('/review'):
            if saved['review_mode'] == 'denied':
                return r.fulfill(status=403, json={'detail': 'forbidden'})
            keys = ['selector', 'filesystem', 'network', 'process', 'model_routing', 'tools',
                    'tool_policies', 'data_scope_refs', 'secrets', 'resources', 'audit', 'exceptions',
                    'impact', 'validation', 'previous']
            return r.fulfill(json={'schema_version': 'change-review/v1', 'change_id': path.split('/')[-2],
                'status': 'approved', 'policy_name': 'Fixture policy',
                'policy_version': 2 if saved['review_mode'] == 'changed' else 1,
                'enforcement_mode': 'block', 'approval_policy': 'standard',
                'proposer_id': 'proposer', 'approver_id': 'independent-reviewer', 'review_digest': 'b' * 64,
                'can_approve': False, 'can_reject': False,
                'approve_blockers': ['not_proposed'], 'reject_blockers': ['not_proposed'],
                'sections': [{'key': key, 'label': key, 'content': '<script>window.__batchXss=1</script>' + 'x' * 300,
                              'redacted': saved['review_mode'] == 'redacted', 'truncated': False} for key in keys]})
        if path.endswith('/environments'):
            return r.fulfill(json=[{'id': 'e1', 'name': 'Fixture', 'mode': 'enforce'}])
        if path.endswith('/runtime-bindings'):
            return r.fulfill(json=[{'id': f'b{n}', 'environment_id': 'e1', 'backend': 'fake',
                                   'backend_target_id': f'target{n}', 'status': 'active'} for n in [1, 2]])
        if path.endswith('/reservation'):
            return r.fulfill(status=200 if saved['result'] else 404,
                             json=saved['result'] or {'detail': 'batch_reservation_not_found'})
        if path.endswith('/deployment-batch-drafts/draft1'):
            return r.fulfill(json=draft)
        r.fulfill(status=404, json={'detail': 'fixture missing'})

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={'width': 1280, 'height': 1000})
            page.add_init_script("Object.defineProperty(crypto, 'randomUUID', { value: undefined });")
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.route('**/api/v1/**', route)
            page.goto(f'http://127.0.0.1:{server.server_port}/changes')
            panel = page.get_by_role('region', name='批次预览与结果')
            expect(panel.get_by_role('button', name='加入批次')).to_be_disabled()
            page.get_by_label('部署环境', exact=True).select_option('e1')
            for n in [1, 2]:
                page.get_by_label('运行时绑定', exact=True).select_option(f'b{n}')
                page.get_by_label('批次中的变更', exact=True).select_option(f'c{n}')
                panel.get_by_role('button', name='加入批次').click()
            expect(panel).to_contain_text('已选择 2 项')
            assert not writes
            panel.get_by_role('button', name='生成批次预览（不部署）').click()
            expect(panel).to_contain_text('尚未查询到执行预留')
            assert 'batch=draft1' in page.url and len(writes) == 1
            assert [item['binding_id'] for item in writes[0]['body']['items']] == ['b1', 'b2']
            page.reload()
            expect(panel).to_contain_text('尚未查询到执行预留')
            assert len(writes) == 1
            assert not impact_reads, 'reload must not automatically probe runtime impact'
            saved['result'] = {'schema_version': 'enterprise-batch-reservation/v1', 'id': 'r1', 'draft_id': 'draft1',
                'state': 'unconfirmed', 'execution_supported': False, 'items': [{
                    'schema_version': 'deployment-submission/v1', 'id': f's{index}', 'change_id': item['change_id'],
                    'deployment_id': f'd{index}', 'state': 'unconfirmed', 'deployment_status': 'pending',
                    'preview_digest': item['preview_digest'], 'created_at': '2026-09-25T00:01:00Z',
                } for index, item in enumerate(draft['preview']['items'])]}
            panel.get_by_role('button', name='刷新批次与结果').click()
            expect(panel).to_contain_text('部分结果尚未确认，禁止盲目重试')
            assert len(writes) == 1
            inspect = panel.get_by_role('button', name='查看权限与影响说明').first
            for mode in ['changed', 'redacted', 'denied']:
                saved['review_mode'] = mode
                inspect.click()
                expect(panel.get_by_role('alert')).to_contain_text('无法完整核对权限内容')
                expect(panel.locator('.batch-item-review pre')).to_have_count(0)
            saved['review_mode'] = 'ok'
            saved['impact_mode'] = 'denied'
            inspect.click()
            expect(panel.get_by_role('alert')).to_contain_text('无法完整核对权限内容')
            expect(panel.locator('.batch-item-review pre')).to_have_count(0)
            saved['impact_mode'] = 'ok'
            inspect.click()
            expect(panel).to_contain_text('不代表完整共享影响已确认')
            expect(panel).to_contain_text('asset-fixture')
            expect(panel).to_contain_text('instance-fixture')
            expect(panel).to_contain_text('尚未建立证明，不能确认执行')
            saved['impact_mode'] = 'denied'
            panel.get_by_role('button', name='重新读取权限与影响说明').click()
            expect(panel.get_by_role('alert')).to_contain_text('无法完整核对权限内容')
            expect(panel.locator('.batch-item-review dl')).to_have_count(0)
            expect(panel.locator('.batch-item-review pre')).to_have_count(0)
            saved['impact_mode'] = 'ok'
            inspect.click()
            expect(panel).to_contain_text('asset-fixture')
            panel.locator('.batch-item-review summary').first.click()
            expect(panel.locator('.batch-item-review pre').first).to_contain_text('<script>')
            assert page.evaluate('window.__batchXss === undefined')
            assert len(writes) == 1
            for width in [375, 768, 1024, 1280, 1440]:
                page.set_viewport_size({'width': width, 'height': 900})
                page.wait_for_timeout(350)  # Wait for the existing sidebar breakpoint transition.
                panel.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), width
                assert page.locator('.content').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'), width
                if width in [375, 1280]:
                    page.screenshot(path=str(out / f'batch-{width}.png'), animations='disabled')
                    panel.locator('.batch-item-review dl').first.scroll_into_view_if_needed()
                    page.screenshot(path=str(out / f'impact-{width}.png'), animations='disabled')
                    panel.locator('.batch-item-review pre').first.scroll_into_view_if_needed()
                    page.screenshot(path=str(out / f'review-{width}.png'), animations='disabled')
            revoke = panel.get_by_role('region', name='网络权限撤除申请')
            revoke.get_by_role('button', name='读取可撤除项').click()
            expect(revoke).to_contain_text('共 2 项')
            expect(revoke.get_by_role('button', name='创建撤除申请（不执行）')).to_be_disabled()
            revoke.get_by_role('button', name='选择筛选结果').click()
            revoke.get_by_label('筛选网络允许项').fill('a.example')
            expect(revoke).to_contain_text('筛选外已选 1 项')
            confirm = revoke.get_by_role('checkbox', name='我确认对全部已选项', exact=False)
            confirm.focus()
            confirm.press('Space')
            expect(confirm).to_be_checked()
            for width in [375, 768, 1024, 1280, 1440]:
                page.set_viewport_size({'width': width, 'height': 900})
                page.wait_for_timeout(350)
                revoke.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                assert page.locator('.content').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
                if width in [375, 1280]:
                    page.screenshot(path=str(out / f'revoke-selection-{width}.png'), animations='disabled')
            revoke.get_by_role('button', name='创建撤除申请（不执行）').press('Enter')
            expect(revoke.get_by_role('alert')).to_contain_text('申请结果未确认')
            expect(revoke.get_by_role('button', name='清空选择')).to_be_disabled()
            revoke.get_by_role('button', name='重试同一申请').click()
            expect(revoke).to_contain_text('撤除申请记录已返回，本次未执行')
            proposals = [entry['body'] for entry in writes if entry['path'].endswith('/network-revoke-proposals')]
            assert len(proposals) == 2 and proposals[0] == proposals[1]
            assert len(proposals[0]['selections']) == 2
            assert len(writes) == 3
            for width in [375, 1280]:
                page.set_viewport_size({'width': width, 'height': 900})
                page.wait_for_timeout(350)
                revoke.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.screenshot(path=str(out / f'revoke-{width}.png'), animations='disabled')
            assert 'revoke_request=' in page.url and 'revoke_policy=p1' in page.url
            saved['recovery_state'] = 'failed'
            page.reload()
            recovery = page.get_by_role('region', name='恢复撤除申请')
            expect(recovery).to_contain_text('当前记录状态：failed')
            recovery.get_by_role('button', name='重新查询原申请').click()
            expect(recovery).to_contain_text('当前记录状态：failed')
            assert len(writes) == 3, 'recovery may never replay POST'
            panel.get_by_role('button', name='查看权限与影响说明').first.click()
            expect(panel.get_by_role('button', name='读取可撤除项')).to_be_disabled()
            for width in [375, 1280]:
                page.set_viewport_size({'width': width, 'height': 900})
                page.wait_for_timeout(350)
                recovery.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.screenshot(path=str(out / f'revoke-recovery-{width}.png'), animations='disabled')
            saved['can_propose'] = False
            page.reload()
            expect(panel).to_contain_text('部分结果尚未确认')
            panel.get_by_role('button', name='查看权限与影响说明').first.click()
            expect(panel).to_contain_text('asset-fixture')
            expect(panel.get_by_role('region', name='网络权限撤除申请')).to_have_count(0)
            assert len(writes) == 3
            page.goto(f'http://127.0.0.1:{server.server_port}/permissions')
            expect(page.get_by_role('heading', name='权限视图', exact=True)).to_be_visible()
            expect(page.get_by_role('region', name='期望网络权限管理')).to_have_count(0)
            assert saved['policy_reads'] == 0
            saved['can_propose'] = True
            saved['recovery_state'] = 'proposed'
            page.reload()
            manager = page.get_by_role('region', name='期望网络权限管理')
            expect(manager).to_be_visible()
            expect(page.get_by_text('协议错误：HTTP 200 缺少 Content-Type', exact=False)).to_have_count(0)
            assert saved['policy_reads'] == 0, 'do not load policies before explicit expansion'
            manager.get_by_role('button', name='选择策略并申请撤除').press('Enter')
            expect(manager.get_by_role('alert')).to_contain_text('无法读取策略列表')
            saved['policy_list_ok'] = True
            manager.get_by_role('button', name='重试策略列表').click()
            expect(manager.get_by_label('选择期望策略')).to_have_value('')
            expect(manager.get_by_role('alert')).to_contain_text('2 条异常或重复记录不可选择')
            expect(manager.locator('option[value="p-duplicate"]')).to_have_count(0)
            expect(manager.get_by_role('region', name='网络权限撤除申请')).to_have_count(0)
            manager.get_by_label('选择期望策略').select_option('p1')
            manager.get_by_label('查找期望策略').fill('Other')
            expect(manager.get_by_label('选择期望策略')).to_have_value('p1')
            expect(manager.get_by_label('选择期望策略')).to_contain_text('筛选外已选')
            direct = manager.get_by_role('region', name='网络权限撤除申请')
            direct.get_by_role('button', name='读取可撤除项').click()
            direct.get_by_role('button', name='选择筛选结果').click()
            direct.get_by_role('checkbox', name='我确认对全部已选项', exact=False).check()
            for width in [375, 768, 1024, 1280, 1440]:
                page.set_viewport_size({'width': width, 'height': 900})
                page.wait_for_timeout(350)
                direct.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                assert page.locator('.content').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
                if width in [375, 1280]:
                    page.screenshot(path=str(out / f'permissions-governance-{width}.png'), animations='disabled')
            assert len(writes) == 3
            direct.get_by_role('button', name='创建撤除申请（不执行）').click()
            expect(direct).to_contain_text('撤除申请记录已返回，本次未执行')
            assert len(writes) == 4
            page.reload()
            expect(manager.get_by_role('region', name='恢复撤除申请')).to_contain_text('当前记录状态：proposed')
            assert len(writes) == 4
            page.goto(f'http://127.0.0.1:{server.server_port}/permissions')
            manager.get_by_role('button', name='选择策略并申请撤除').click()
            manager.get_by_role('button', name='切换跨策略批量申请').press('Enter')
            batch = manager.get_by_role('region', name='跨策略批量撤除')
            batch.get_by_role('checkbox', name='Fixture policy', exact=False).check()
            batch.get_by_role('checkbox', name='Other policy', exact=False).check()
            batch.get_by_label('筛选批量策略').fill('Other')
            expect(batch).to_contain_text('筛选外已选 1 份')
            batch.get_by_role('button', name='读取全部可撤除项').click()
            expect(batch.get_by_role('alert')).to_contain_text('未能读取全部完整选项')
            expect(batch.locator('fieldset')).to_have_count(0)
            saved['batch_options_ok'] = True
            batch.get_by_role('button', name='读取全部可撤除项').click()
            expect(batch.locator('fieldset')).to_have_count(2)
            for button in batch.get_by_role('button', name='选择此策略全部项').all():
                button.click()
            expect(batch).to_contain_text('批量已选 3 个网络允许项')
            expect(batch.get_by_role('button', name='提交批量撤除申请（不执行）')).to_be_disabled()
            batch.get_by_role('checkbox', name='我确认全部策略', exact=False).check()
            batch.get_by_role('button', name='清空全部策略选择（含筛选外）').press('Enter')
            expect(batch).to_contain_text('已选 0 份策略，筛选外已选 0 份')
            expect(batch.locator('fieldset')).to_have_count(0)
            expect(batch.get_by_role('button', name='读取全部可撤除项')).to_be_disabled()
            expect(batch.get_by_role('button', name='清空全部策略选择（含筛选外）')).to_be_disabled()
            batch.get_by_label('筛选批量策略').fill('')
            batch.get_by_role('checkbox', name='Fixture policy', exact=False).check()
            batch.get_by_role('checkbox', name='Other policy', exact=False).check()
            batch.get_by_role('button', name='读取全部可撤除项').click()
            expect(batch.locator('fieldset')).to_have_count(2)
            for button in batch.get_by_role('button', name='选择此策略全部项').all():
                button.click()
            expect(batch.get_by_role('checkbox', name='我确认全部策略', exact=False)).not_to_be_checked()
            expect(batch.get_by_role('button', name='提交批量撤除申请（不执行）')).to_be_disabled()
            batch.get_by_role('checkbox', name='我确认全部策略', exact=False).check()
            for width in [375, 768, 1024, 1280, 1440]:
                page.set_viewport_size({'width': width, 'height': 900})
                batch.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                assert page.locator('.content').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
                if width in [375, 1280]:
                    page.screenshot(path=str(out / f'network-batch-{width}.png'), animations='disabled')
            assert len(writes) == 4
            batch.get_by_role('button', name='提交批量撤除申请（不执行）').click()
            expect(batch.get_by_role('alert')).to_contain_text('全部选择已锁定')
            expect(batch.get_by_role('button', name='清空全部策略选择（含筛选外）')).to_be_disabled()
            expect(batch.locator('fieldset').first.get_by_role('checkbox').first).to_be_disabled()
            batch.get_by_role('button', name='重试原批次申请').click()
            expect(batch).to_contain_text('整批申请记录已返回')
            expect(batch.get_by_role('button', name='清空全部策略选择（含筛选外）')).to_be_disabled()
            assert len(writes) == 6
            assert writes[-1]['body'] == writes[-2]['body']
            page.reload()
            recovered = manager.get_by_role('region', name='恢复批量撤除申请')
            expect(recovered).to_contain_text('当前状态 approved')
            expect(recovered).to_contain_text('当前状态 proposed')
            recovered.get_by_role('button', name='重新查询批次').click()
            expect(recovered).to_contain_text('当前状态 proposed')
            manager.get_by_role('button', name='选择策略并申请撤除').click()
            expect(manager.get_by_role('button', name='切换跨策略批量申请')).to_be_disabled()
            assert len(writes) == 6
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    report = {'passed': True, 'scope': 'synthetic only', 'writes': writes,
              'read_only_impact_posts': impact_reads,
              'execution_requests': 0, 'pageerrors': errors, 'server_stopped': not worker.is_alive()}
    (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
