#!/usr/bin/env python3
"""Real isolated dev/fake deployment task, exact history and audit UI; no OpenShell execution."""
import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=False)
    assert (args.web / 'index.html').is_file(), 'Build must finish before browser validation'
    checks = {}
    with tempfile.TemporaryDirectory(prefix='siq-execution-e147-') as raw:
        root = Path(raw)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        endpoint = f'http://127.0.0.1:{port}'
        env = {k: v for k, v in os.environ.items() if k in ('PATH', 'LANG', 'LC_ALL', 'TZ')}
        env.update({'HOME': raw, 'SIQ_AS_DEV': '1', 'SIQ_AS_ALLOW_SQLITE': '1',
                    'SIQ_AS_DATABASE_URL': f'sqlite:///{root}/api.db',
                    'SIQ_AS_SIGNING_KEY_FILE': str(root / 'signing.seed'),
                    'SIQ_AS_ENFORCEMENT_BACKEND': 'fake'})
        bootstrap = root / 'serve.py'
        bootstrap.write_text('import sys\nfrom pathlib import Path\n' +
            f'sys.path.insert(0, {str(ROOT / "apps/control-api")!r})\n' +
            'from app.main import app,settings\nfrom app.db import init_db,Base,get_engine,session_scope\n' +
            'from app.models import Tenant,Environment,AgentAsset,AgentInstance,DesiredPolicy,ChangeRequest,Deployment,AuditEvent\n' +
            'init_db(settings)\nBase.metadata.create_all(get_engine())\n' +
            'with session_scope() as s:\n' +
            '    s.add(Tenant(id="dev-tenant",name="验收组织"))\n    s.flush()\n' +
            '    s.add(Environment(id="env-execution",tenant_id="dev-tenant",name="研究验收环境",mode="enforce"))\n' +
            '    s.add(AgentAsset(id="agt-execution",tenant_id="dev-tenant",name="研究分析",status="confirmed"))\n    s.flush()\n' +
            '    s.add(AgentInstance(id="ins-execution",tenant_id="dev-tenant",asset_id="agt-execution",environment_id="env-execution",runtime="hermes"))\n    s.commit()\n' +
            'with session_scope() as s:\n' +
            '    s.add(DesiredPolicy(id="pol-history",tenant_id="dev-tenant",name="历史展示夹具",selector={"agent_ids":["agt-execution"]},status="validated"))\n    s.flush()\n' +
            '    s.add(ChangeRequest(id="cr-history",tenant_id="dev-tenant",policy_id="pol-history",proposer_user_id="fixture-history-owner",idempotency_key="fixture-history-key",status="failed"))\n    s.flush()\n' +
            '    for i in range(21):\n        s.add(Deployment(id=f"dep-history-{i:02}",tenant_id="dev-tenant",environment_id="env-execution",change_request_id="cr-history",target="fixture-history-target",to_revision="policy-1",status="failed",verification={"level":"readback_verified","backend_mutated":True}))\n    s.flush()\n' +
            '    for i in range(52):\n        s.add(AuditEvent(id=f"aud-history-{i:02}",tenant_id="dev-tenant",actor_type="user",actor_id="fixture-history-actor",action="deployment.fail",resource_type="deployment",resource_id="dep-history-00",decision="allow"))\n    s.commit()\n' +
            'from fastapi.responses import FileResponse\nimport uvicorn\n' +
            f'WEB=Path({str(args.web.resolve())!r})\n' +
            '@app.get("/{path:path}")\ndef web(path:str):\n    target=(WEB/path).resolve()\n' +
            '    if not target.is_relative_to(WEB) or not target.is_file(): target=WEB/"index.html"\n    return FileResponse(target)\n' +
            f'uvicorn.run(app,host="127.0.0.1",port={port},log_level="error",access_log=False)\n')
        headers = {'X-Dev-Tenant-Id': 'dev-tenant', 'X-Dev-User-Id': 'fixture-owner', 'X-Dev-Roles': 'security_admin,agent_owner,platform_operator,auditor'}
        current = dict(headers)

        def api(path, body=None, custom=None, expected=200):
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(endpoint + path, data=data, headers={**(custom or headers), 'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    status, result = response.status, response.read()
            except urllib.error.HTTPError as error:
                status, result = error.code, error.read()
            assert status == expected, (path, status)
            return json.loads(result)

        with (root / 'server.log').open('w') as log:
            proc = subprocess.Popen([str(ROOT / 'apps/control-api/.venv/bin/python'), str(bootstrap)], env=env, stdout=log, stderr=log)
            try:
                for _ in range(150):
                    if proc.poll() is not None:
                        raise RuntimeError('fixture API exited')
                    try:
                        api('/health')
                        break
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(.1)
                else:
                    raise RuntimeError('API readiness timeout')
                binding = api('/api/v1/runtime-bindings', {'agent_instance_id': 'ins-execution', 'environment_id': 'env-execution', 'backend': 'fake', 'backend_target_id': 'fixture-research-sandbox'}, expected=201)
                changes = {}
                for key in ('normal', 'lost', 'empty'):
                    policy = api('/api/v1/policies', {'name': '验收研究策略 · ' + key, 'selector': {'agent_ids': ['agt-execution']}, 'enforcement_mode': 'block'}, expected=201)
                    cr = api('/api/v1/change-requests', {'policy_id': policy['id'], 'idempotency_key': uuid.uuid4().hex}, expected=201)
                    changes[key] = api('/api/v1/change-requests/' + cr['id'] + '/approve', {}, {**headers, 'X-Dev-User-Id': 'fixture-approver'})
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, locale='zh-CN')
                    requests, errors = [], []
                    page.on('pageerror', lambda _: errors.append('pageerror'))
                    def identity(route):
                        clean = {k: v for k, v in route.request.headers.items() if not k.lower().startswith('x-dev-')}
                        requests.append((route.request.method, route.request.url.split(endpoint)[-1]))
                        route.continue_(headers={**clean, **current})
                    page.route('**/api/v1/**', identity)
                    page.goto(endpoint + '/changes')
                    expect(page.get_by_role('heading', name='变更中心', exact=True)).to_be_visible()
                    (args.out_dir / 'target-labels.json').write_text(json.dumps(page.locator('label').all_text_contents(), ensure_ascii=False))
                    page.screenshot(path=str(args.out_dir / 'targets.png'), full_page=True, animations='disabled')
                    page.get_by_label('部署环境', exact=True).select_option('env-execution')
                    page.get_by_label('运行时绑定', exact=True).select_option(binding['id'])
                    row = page.locator('tr').filter(has_text=changes['normal']['id'])
                    row.get_by_role('button', name='部署', exact=True).click()
                    preview_dialog = page.get_by_role('dialog', name='确认部署目标')
                    expect(preview_dialog.get_by_role('button', name='确认并部署')).to_be_disabled()
                    preview_dialog.get_by_role('checkbox').check()
                    preview_dialog.get_by_role('button', name='确认并部署').click()
                    dialog = page.get_by_role('dialog', name='部署与审计')
                    expect(dialog.get_by_text('已从服务端独立读取本次部署记录', exact=False)).to_be_visible()
                    expect(dialog.get_by_text('已创建下发任务', exact=False)).to_be_visible()
                    expect(dialog.get_by_text('尚无生效验证', exact=True)).to_be_visible()
                    expect(dialog.get_by_text('创建部署任务', exact=True)).to_be_visible()
                    result = api('/api/v1/change-requests/' + changes['normal']['id'] + '/execution')
                    assert len(result['deployments']) == 1 and result['deployments'][0]['status'] == 'sent'
                    assert any(e['resource_id'] == result['deployments'][0]['id'] and e['action'] == 'deployment.create' for e in result['audit_events'])
                    checks['real_deployment_task_independent_exact_readback_and_audit'] = True
                    checks['fake_task_never_claims_enforcement'] = True
                    assert not any(path.split('?')[0] == '/api/v1/deployments' and method == 'GET' for method, path in requests)
                    checks['no_global_first_page_dependency'] = True
                    page.screenshot(path=str(args.out_dir / 'execution-desktop.png'), full_page=True, animations='disabled')
                    page.reload()
                    expect(page.get_by_role('dialog').get_by_text('已创建下发任务', exact=False)).to_be_visible()
                    checks['reload_restores_exact_result'] = True

                    pattern = '**/change-requests/' + changes['normal']['id'] + '/execution*'
                    def fail_read(route):
                        route.fulfill(status=503, content_type='application/json', body='{"detail":"fixture_read_failure"}')
                    page.route(pattern, fail_read)
                    dialog.get_by_role('button', name='刷新记录').click()
                    expect(dialog.get_by_text('暂时无法读取部署与审计记录', exact=False)).to_be_visible()
                    expect(dialog.get_by_text('尚无生效验证', exact=True)).to_have_count(0)
                    page.unroute(pattern, fail_read)
                    dialog.get_by_role('button', name='重试读取').click()
                    expect(dialog.get_by_text('尚无生效验证', exact=True)).to_be_visible()
                    checks['read_failure_clears_old_result_and_retry_recovers'] = True

                    current['X-Dev-Roles'] = 'viewer'
                    page.reload()
                    expect(dialog.get_by_text('当前账号没有审计读取权限', exact=False)).to_be_visible()
                    expect(dialog.get_by_text('创建部署任务', exact=True)).to_have_count(0)
                    expect(dialog.get_by_text('环境名称未提供', exact=False)).to_be_visible()
                    checks['audit_and_environment_name_require_their_own_permissions'] = True
                    current.update(headers)

                    page.goto(endpoint + '/changes')
                    expect(page.get_by_role('heading', name='变更中心', exact=True)).to_be_visible()
                    (args.out_dir / 'target-labels.json').write_text(json.dumps(page.locator('label').all_text_contents(), ensure_ascii=False))
                    page.screenshot(path=str(args.out_dir / 'targets.png'), full_page=True, animations='disabled')
                    page.get_by_label('部署环境', exact=True).select_option('env-execution')
                    page.get_by_label('运行时绑定', exact=True).select_option(binding['id'])
                    writes = []
                    def lose_response(route):
                        clean = {k: v for k, v in route.request.headers.items() if not k.lower().startswith('x-dev-')}
                        response = route.fetch(headers={**clean, **headers})
                        assert response.status == 201
                        writes.append(1)
                        route.fulfill(status=503, content_type='application/json', body='{"detail":"fixture_response_lost"}')
                    page.route('**/api/v1/deployment-submissions', lose_response)
                    row = page.locator('tr').filter(has_text=changes['lost']['id'])
                    row.get_by_role('button', name='部署', exact=True).click()
                    preview_dialog = page.get_by_role('dialog', name='确认部署目标')
                    expect(preview_dialog.get_by_role('button', name='确认并部署')).to_be_disabled()
                    preview_dialog.get_by_role('checkbox').check()
                    preview_dialog.get_by_role('button', name='确认并部署').click()
                    expect(dialog.get_by_text('已找回本次部署请求。执行是否生效以下方验证为准。', exact=True)).to_be_visible()
                    expect(dialog.get_by_text('已创建下发任务', exact=False)).to_be_visible()
                    dialog.get_by_role('button', name='关闭', exact=True).click()
                    expect(row.get_by_role('button', name='部署', exact=True)).to_have_count(0)
                    row.get_by_role('button', name='部署与审计', exact=True).click()
                    expect(dialog.get_by_text('已找回本次部署请求。执行是否生效以下方验证为准。', exact=True)).to_be_visible()
                    assert len(writes) == 1
                    page.unroute('**/api/v1/deployment-submissions', lose_response)
                    checks['lost_response_opens_history_without_same_page_write_replay'] = True
                    page.reload()
                    expect(dialog.get_by_text('已找回本次部署请求。执行是否生效以下方验证为准。', exact=True)).to_be_visible()
                    assert 'unconfirmed=1' in page.url
                    assert len(writes) == 1
                    checks['lost_response_readback_restored_without_write_replay'] = True

                    page.goto(endpoint + '/changes?view=execution&change=' + changes['empty']['id'])
                    expect(dialog.get_by_text('尚未查询到关联部署记录', exact=False)).to_be_visible()
                    expect(dialog.get_by_text('批准变更', exact=True)).to_be_visible()
                    checks['approved_without_deployment_is_explicit'] = True
                    # Seeded history demonstrates bounded expansion; it is not execution evidence.
                    page.goto(endpoint + '/changes?view=execution&change=cr-history')
                    expect(dialog.get_by_text('仅显示最近 20 次', exact=False)).to_be_visible()
                    expect(dialog.get_by_text('仅显示最近 50 条', exact=False)).to_be_visible()
                    dialog.get_by_role('button', name='查看更多关联记录').click()
                    expect(dialog.get_by_text('本次查询返回 21 次关联部署。', exact=True)).to_be_visible()
                    expect(dialog.get_by_text('本次查询返回 52 条精确关联审计。', exact=True)).to_be_visible()
                    expect(dialog.get_by_text('配置已读回，行为未验证', exact=True)).to_have_count(0)
                    expect(dialog.get_by_text('部署失败，需核对执行端', exact=True)).to_have_count(21)
                    checks['real_expanded_history_read_and_failed_old_success_projection'] = True
                    page.goto(endpoint + '/changes?view=execution&change=' + changes['normal']['id'])
                    expect(dialog.get_by_text('创建部署任务', exact=True)).to_be_visible()
                    page.set_viewport_size({'width': 390, 'height': 844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert dialog.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
                    page.screenshot(path=str(args.out_dir / 'execution-mobile.png'), full_page=True, animations='disabled')
                    close_box = dialog.get_by_role('button', name='关闭', exact=True).bounding_box()
                    assert close_box and close_box['y'] >= 0 and close_box['y'] + close_box['height'] <= 844
                    checks['mobile_close_and_refresh_stay_in_viewport'] = True
                    page.keyboard.press('Escape')
                    expect(dialog).to_have_count(0)
                    expect(page.locator('.change-mobile-list').get_by_role('button', name='部署与审计').first).to_be_visible()
                    checks['mobile_results_and_list_entry_keyboard_close'] = True
                    assert not errors
                    checks['no_browser_runtime_errors'] = True
                    browser.close()
            finally:
                proc.terminate()
                proc.wait(timeout=10)
    (args.out_dir / 'result.json').write_text(json.dumps({'schema_version': 'enterprise-change-execution-smoke/v1',
        'checks': checks, 'passed': all(checks.values()), 'real_control_api': True, 'identity': 'isolated_dev_headers',
        'deployment_backend': 'fake_task_only', 'history_display_fixtures': True, 'faults': ['lost_post_response', 'read_503'],
        'openshell_execution_tested': False, 'production_eligible': False}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': all(checks.values()), 'checks': len(checks)}))


if __name__ == '__main__':
    main()
