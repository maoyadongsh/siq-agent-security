#!/usr/bin/env python3
"""Real isolated API context and role-aware UI. Dev identity and fixture JWT only."""
import argparse
import base64
import hashlib
import hmac
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=False)
    checks = {}
    with tempfile.TemporaryDirectory(prefix='siq-workspace-e145-') as raw:
        root = Path(raw)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        endpoint = f'http://127.0.0.1:{port}'
        fixture_key = 'isolated-console-workspace-fixture-key-' * 2
        env = {k: v for k, v in os.environ.items() if k in ('PATH', 'LANG', 'LC_ALL', 'TZ')}
        env.update({'HOME': raw, 'SIQ_AS_DEV': '1', 'SIQ_AS_ALLOW_SQLITE': '1',
                    'SIQ_AS_DATABASE_URL': f'sqlite:///{root}/api.db', 'SIQ_AS_SIGNING_KEY_FILE': str(root / 'signing.seed'),
                    'SIQ_AS_ENFORCEMENT_BACKEND': 'fake', 'SIQ_AS_DEV_JWT_SECRET': fixture_key})
        bootstrap = root / 'serve.py'
        bootstrap.write_text('import sys\nfrom pathlib import Path\n' +
            f'sys.path.insert(0, {str(ROOT / "apps/control-api")!r})\n' +
            'from app.main import app,settings\nfrom app.db import init_db,Base,get_engine,session_scope\n' +
            'from app.models import Tenant\ninit_db(settings)\nBase.metadata.create_all(get_engine())\n' +
            'with session_scope() as s:\n    s.add_all([Tenant(id="dev-tenant",name="验收组织甲"),Tenant(id="org-two",name="验收组织乙")])\n' +
            'from fastapi.responses import FileResponse\nimport uvicorn\n' +
            f'WEB=Path({str(args.web.resolve())!r})\n' +
            '@app.get("/{path:path}")\ndef web(path:str):\n    target=(WEB/path).resolve()\n' +
            '    if not target.is_relative_to(WEB) or not target.is_file(): target=WEB/"index.html"\n    return FileResponse(target)\n' +
            f'uvicorn.run(app,host="127.0.0.1",port={port},log_level="error",access_log=False)\n')
        base_headers = {'X-Dev-Tenant-Id': 'dev-tenant', 'X-Dev-User-Id': 'fixture-user', 'X-Dev-Roles': 'platform_operator,agent_owner'}
        current = dict(base_headers)
        seen = []

        def api(path, headers=None, expected=200):
            req = urllib.request.Request(endpoint + path, headers=headers or current)
            try:
                response = urllib.request.urlopen(req, timeout=5)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                assert response.status == expected, response.status
                return json.loads(response.read())

        def jwt_token():
            def encode(value):
                return base64.urlsafe_b64encode(json.dumps(value, separators=(',', ':')).encode()).decode().rstrip('=')
            now = int(time.time())
            body = encode({'alg': 'HS256', 'typ': 'JWT'}) + '.' + encode({'sub': 'jwt-fixture-user', 'tenant_id': 'org-two',
                'type': 'service', 'role_codes': ['custom-fixture-role'], 'permissions': ['env:read'],
                'aud': 'siq-agent-security', 'iat': now, 'exp': now + 300})
            sig = base64.urlsafe_b64encode(hmac.new(fixture_key.encode(), body.encode(), hashlib.sha256).digest()).decode().rstrip('=')
            return body + '.' + sig

        with tempfile.TemporaryFile() as logs:
            service = subprocess.Popen([str(ROOT/'apps/control-api/.venv/bin/python'), str(bootstrap)], env=env, stdout=logs, stderr=logs)
            try:
                for _ in range(100):
                    assert service.poll() is None, 'API exited'
                    try:
                        api('/health')
                        break
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(.1)
                else:
                    raise RuntimeError('API readiness timeout')
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000}, locale='zh-CN')
                    errors = []
                    page.on('pageerror', lambda _: errors.append('pageerror'))

                    def identity(route):
                        headers = {k: v for k, v in route.request.headers.items() if not k.lower().startswith('x-dev-') and k.lower() != 'authorization'}
                        headers.update(current)
                        seen.append(route.request.url.split(endpoint)[-1].split('?')[0])
                        route.continue_(headers=headers)
                    page.route('**/api/v1/**', identity)
                    page.goto(endpoint + '/')
                    expect(page.get_by_role('heading', name='工作台', exact=True)).to_be_visible()
                    expect(page.get_by_role('heading', name='验收组织甲', exact=True)).to_be_visible()
                    expect(page.get_by_text('平台运维人员', exact=True)).to_be_visible()
                    expect(page.get_by_text('智能体负责人', exact=True)).to_be_visible()
                    expect(page.get_by_text('当前为用户身份。 当前使用开发身份，仅用于联调，不能作为生产登录证明。', exact=True)).to_be_visible()
                    assert page.url.endswith('/workspace')
                    context = api('/api/v1/console-context')
                    assert context['tenant']['name'] == '验收组织甲' and context['access']['environments']
                    checks['default_workspace_verified_organization_and_dev_label'] = True
                    page.screenshot(path=str(args.out_dir/'workspace-default-desktop.png'), animations='disabled')
                    cases = [
                        ('viewer', {'工作台', '资产', '权限', '安全', '策略中心', '变更中心', '运行时绑定', '设置'}),
                        ('platform_operator', {'工作台', '环境与设备', '设置'}),
                        ('agent_owner', {'工作台', '资产', '权限', '安全', '设置'}),
                        ('auditor', {'工作台', '资产', '权限', '安全', '策略中心', '变更中心', '运行时绑定', '审计', '设置'}),
                        ('reviewer', {'工作台', '设置'}),
                        ('security_admin', {'工作台', '总览', '资产', '权限', '安全', '策略中心', '变更中心', '运行时绑定', '环境与设备', '设置'}),
                    ]
                    for role, labels in cases:
                        current = {**base_headers, 'X-Dev-Roles': role}
                        page.reload()
                        expect(page.get_by_role('heading', name='验收组织甲', exact=True)).to_be_visible()
                        links = set(page.get_by_role('navigation').get_by_role('link').all_text_contents())
                        assert {label.strip() for label in links} == labels, role
                        checks['actual_role_navigation_' + role] = True
                        if role == 'reviewer':
                            expect(page.get_by_text('你具有变更批准权限，但缺少查看变更清单所需的策略读取权限。请联系组织管理员补齐读取权限后再处理。', exact=True)).to_be_visible()
                            assert api('/api/v1/console-context')['actions']['approve_change']
                            api('/api/v1/change-requests', expected=403)
                            checks['reviewer_missing_read_access_explained_without_grant'] = True
                    current = {**base_headers, 'X-Dev-Roles': 'viewer'}
                    seen.clear()
                    page.goto(endpoint + '/environments')
                    expect(page.get_by_role('heading', name='当前账号无法访问此页面', exact=True)).to_be_visible()
                    assert '/api/v1/environments' not in seen
                    api('/api/v1/environments', expected=403)
                    checks['deep_link_refusal_without_domain_request_backend_403'] = True
                    page.get_by_role('link', name='查看我的组织与权限', exact=True).click()
                    expect(page.get_by_role('heading', name='验收组织甲', exact=True)).to_be_visible()
                    page.get_by_role('region', name='可用工作入口').get_by_role('link', name='智能体与候选', exact=False).click()
                    expect(page.get_by_role('heading', name='智能体资产', exact=True)).to_be_visible()
                    expect(page.get_by_role('tab', name='发现候选', exact=False)).to_have_attribute('aria-selected', 'true')
                    checks['workspace_action_reaches_real_candidates_route'] = True
                    page.get_by_role('link', name='组织与权限', exact=True).click()
                    page.route('**/console-context', lambda route: route.fulfill(status=503, json={'detail': 'fixture_unavailable'}))
                    page.get_by_role('button', name='刷新组织与权限', exact=True).click()
                    expect(page.get_by_role('alert')).to_contain_text('旧入口已撤下')
                    expect(page.get_by_role('heading', name='验收组织甲', exact=True)).to_have_count(0)
                    expect(page.get_by_role('navigation').get_by_role('link', name='资产', exact=True)).to_have_count(0)
                    page.unroute('**/console-context')
                    page.get_by_role('button', name='刷新组织与权限', exact=True).click()
                    expect(page.get_by_role('heading', name='验收组织甲', exact=True)).to_be_visible()
                    checks['context_failure_removes_old_identity_and_recovers'] = True
                    current = {'Authorization': 'Bearer ' + jwt_token()}
                    page.reload()
                    expect(page.get_by_role('heading', name='验收组织乙', exact=True)).to_be_visible()
                    expect(page.get_by_text('当前为服务身份。身份来自已验证的访问凭证。', exact=True)).to_be_visible()
                    expect(page.get_by_text('另有 1 个自定义角色，权限以本次核对结果为准。', exact=True)).to_be_visible()
                    expect(page.get_by_role('heading', name='验收组织甲', exact=True)).to_have_count(0)
                    assert {s.strip() for s in page.get_by_role('navigation').get_by_role('link').all_text_contents()} == {'工作台', '环境与设备', '设置'}
                    assert api('/api/v1/console-context')['authentication'] == 'verified_token'
                    storage = page.evaluate('JSON.stringify([Object.entries(localStorage),Object.entries(sessionStorage)])')
                    assert 'jwt-fixture-user' not in storage and current['Authorization'] not in storage and '验收组织' not in storage
                    checks['signed_fixture_jwt_custom_role_service_and_tenant_switch'] = True
                    checks['identity_and_tokens_not_in_browser_storage'] = True
                    page.get_by_role('link', name='查看连接设置', exact=True).click()
                    expect(page.get_by_text('当前组织：验收组织乙。身份与权限以服务端读回为准。', exact=True)).to_be_visible()
                    page.get_by_role('link', name='查看组织与角色', exact=True).click()
                    expect(page.get_by_role('heading', name='工作台', exact=True)).to_be_visible()
                    page.screenshot(path=str(args.out_dir/'workspace-desktop.png'), animations='disabled')
                    page.set_viewport_size({'width':375,'height':900})
                    expect(page.get_by_role('heading', name='验收组织乙', exact=True)).to_be_visible()
                    checks['workspace_no_horizontal_overflow_375'] = page.locator('.content-page').evaluate('el => el.scrollWidth <= el.clientWidth')
                    page.screenshot(path=str(args.out_dir/'workspace-mobile.png'), animations='disabled')
                    page.get_by_role('button', name='打开导航', exact=True).click()
                    expect(page.get_by_role('navigation').get_by_role('link', name='环境与设备', exact=True)).to_be_visible()
                    page.keyboard.press('Escape')
                    expect(page.get_by_role('button', name='关闭导航', exact=True)).to_have_count(0)
                    checks['mobile_role_navigation_opens_and_closes'] = True
                    checks['no_browser_errors'] = not errors
                    assert all(checks.values())
                    browser.close()
            finally:
                if service.poll() is None:
                    service.terminate()
                    try:
                        service.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        service.kill()
                        service.wait(timeout=10)
    payload = {'schema_version':'siq.enterprise-workspace-browser/v1','passed':all(checks.values()),'checks':checks,
               'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'scope':'Real isolated API/SQLite; dev header roles and a signed fixture HS256 JWT; not production IAM login/refresh or external IdP verification.'}
    (args.out_dir/'result.sanitized.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':payload['passed'],'checks':len(checks)}))


if __name__ == '__main__':
    main()
