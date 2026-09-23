#!/usr/bin/env python3
"""Isolated real API approval UI; dev identities and labelled transport faults only."""
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
    checks = {}
    with tempfile.TemporaryDirectory(prefix='siq-review-e146-') as raw:
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
            'from app.main import app\nfrom fastapi.responses import FileResponse\nimport uvicorn\n' +
            f'WEB=Path({str(args.web.resolve())!r})\n' +
            '@app.get("/{path:path}")\ndef web(path:str):\n    target=(WEB/path).resolve()\n' +
            '    if not target.is_relative_to(WEB) or not target.is_file(): target=WEB/"index.html"\n    return FileResponse(target)\n' +
            f'uvicorn.run(app,host="127.0.0.1",port={port},log_level="error",access_log=False)\n')
        proposer = {'X-Dev-Tenant-Id': 'dev-tenant', 'X-Dev-User-Id': 'fixture-proposer', 'X-Dev-Roles': 'security_admin,agent_owner'}
        reviewer = {**proposer, 'X-Dev-User-Id': 'fixture-reviewer', 'X-Dev-Roles': 'reviewer,viewer'}
        current = dict(reviewer)

        def api(path, body=None, headers=None, expected=200):
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(endpoint + path, data=data, headers={**(headers or reviewer), 'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    status, result = response.status, response.read()
            except urllib.error.HTTPError as error:
                status, result = error.code, error.read()
            assert status == expected, (path, status)
            return json.loads(result)

        def create_change(name):
            p = api('/api/v1/policies', {'name': name, 'selector': {'agent_ids': ['fixture-hermes-analysis']},
                'network': [{'endpoint': 'research.example:443', 'effect': 'allow', 'binary_paths': ['/usr/bin/curl']}],
                'enforcement_mode': 'block'}, proposer, 201)
            return api('/api/v1/change-requests', {'policy_id': p['id'], 'idempotency_key': uuid.uuid4().hex,
                'impact': {'purpose': '研究分析仅访问批准的数据服务'}}, proposer, 201)

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
                changes = {key: create_change('验收研究策略 · ' + key) for key in ('approve', 'reject', 'lost', 'stale', 'cancel')}
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width': 1440, 'height': 1100}, locale='zh-CN')
                    page_errors, requests = [], []
                    page.on('pageerror', lambda _: page_errors.append('pageerror'))

                    def identity(route):
                        headers = {k: v for k, v in route.request.headers.items() if not k.lower().startswith('x-dev-')}
                        headers.update(current)
                        requests.append((route.request.method, route.request.url.split(endpoint)[-1]))
                        route.continue_(headers=headers)
                    page.route('**/api/v1/**', identity)

                    def open_review(key):
                        cr = changes[key]
                        page.goto(endpoint + '/changes?change=' + cr['id'])
                        dialog = page.get_by_role('dialog', name='审查变更')
                        try:
                            expect(dialog.get_by_role('heading', name='验收研究策略 · ' + key + ' · 第 1 版')).to_be_visible()
                        except AssertionError:
                            (args.out_dir / 'failure.txt').write_text(page.locator('body').inner_text())
                            page.screenshot(path=str(args.out_dir / 'failure.png'), full_page=True)
                            raise
                        return dialog

                    def choose(dialog, decision):
                        dialog.get_by_role('radio', name=decision + '变更', exact=True).check()
                        dialog.get_by_role('checkbox').check()

                    dialog = open_review('cancel')
                    expect(dialog.get_by_text('研究分析仅访问批准的数据服务', exact=False)).to_be_visible()
                    expect(dialog.get_by_text('fixture-hermes-analysis', exact=False)).to_be_visible()
                    dialog.get_by_role('button', name='关闭', exact=True).click()
                    assert api('/api/v1/change-requests/' + changes['cancel']['id'] + '/review')['status'] == 'proposed'
                    assert not any(method == 'POST' for method, _ in requests)
                    checks['cancel_has_no_write_and_exact_contents_visible'] = True

                    current.update(proposer)
                    dialog = open_review('cancel')
                    expect(dialog.get_by_role('radio', name='批准变更', exact=True)).to_be_disabled()
                    expect(dialog.get_by_text('提出者不能批准自己的变更', exact=False)).to_be_visible()
                    checks['own_approval_disabled'] = True

                    current.update(reviewer)
                    current['X-Dev-Roles'] = 'viewer'
                    requests.clear()
                    dialog = open_review('cancel')
                    expect(dialog.get_by_role('radio')).to_have_count(0)
                    expect(dialog.get_by_text('当前账号没有审批权限', exact=False)).to_be_visible()
                    assert not any(path.split('?')[0] == '/api/v1/environments' for _, path in requests)
                    checks['readonly_review_no_privileged_environment_fetch'] = True

                    current.update(reviewer)
                    dialog = open_review('approve')
                    dialog.get_by_role('radio', name='批准变更', exact=True).check()
                    expect(dialog.get_by_role('button', name='确认批准')).to_be_disabled()
                    dialog.get_by_role('checkbox').check()
                    page.screenshot(path=str(args.out_dir / 'review-desktop.png'), full_page=True)
                    dialog.get_by_role('button', name='确认批准').click()
                    expect(dialog.get_by_text('已批准，并已从服务端核对', exact=False)).to_be_visible()
                    approved = api('/api/v1/change-requests/' + changes['approve']['id'] + '/review')
                    assert approved['status'] == 'approved' and approved['approver_id'] == 'fixture-reviewer'
                    checks['explicit_approval_and_independent_readback'] = True
                    page.reload()
                    expect(page.get_by_role('dialog').get_by_text('已批准，待部署', exact=True)).to_be_visible()
                    checks['refresh_preserves_exact_change_and_result'] = True

                    dialog = open_review('reject')
                    choose(dialog, '驳回')
                    dialog.get_by_role('button', name='确认驳回').click()
                    expect(dialog.get_by_text('已驳回，并已从服务端核对', exact=False)).to_be_visible()
                    assert api('/api/v1/change-requests/' + changes['reject']['id'] + '/review')['status'] == 'rejected'
                    checks['reject_and_independent_readback'] = True

                    dialog = open_review('lost')
                    lost_writes = []
                    def lose_response(route):
                        headers = {k: v for k, v in route.request.headers.items() if not k.lower().startswith('x-dev-')}
                        response = route.fetch(headers={**headers, **reviewer})
                        assert response.status == 200
                        lost_writes.append(1)
                        route.fulfill(status=503, content_type='application/json', body='{"detail":"fixture_response_lost"}')
                    pattern = '**/change-requests/' + changes['lost']['id'] + '/review-decision'
                    page.route(pattern, lose_response)
                    choose(dialog, '批准')
                    dialog.get_by_role('button', name='确认批准').click()
                    expect(dialog.get_by_role('button', name='核对处理结果')).to_be_enabled()
                    expect(dialog.get_by_role('button', name='确认批准')).to_have_count(0)
                    dialog.get_by_role('button', name='核对处理结果').click()
                    expect(dialog.get_by_text('已核对当前状态：已批准，待部署。', exact=False)).to_be_visible()
                    assert len(lost_writes) == 1
                    page.unroute(pattern, lose_response)
                    checks['lost_post_response_readback_without_replay'] = True

                    dialog = open_review('stale')
                    choose(dialog, '批准')
                    other = {**reviewer, 'X-Dev-User-Id': 'fixture-other-reviewer'}
                    api('/api/v1/change-requests/' + changes['stale']['id'] + '/reject', {}, other)
                    dialog.get_by_role('button', name='确认批准').click()
                    expect(dialog.get_by_text('变更内容或状态已变化', exact=False)).to_be_visible()
                    dialog.get_by_role('button', name='核对处理结果').click()
                    expect(dialog.get_by_text('已核对当前状态：已驳回。', exact=False)).to_be_visible()
                    expect(dialog.get_by_text('fixture-other-reviewer', exact=True)).to_be_visible()
                    checks['concurrent_processing_requires_reconciliation'] = True

                    pattern = '**/change-requests/' + changes['cancel']['id'] + '/review'
                    def read_failure(route):
                        route.fulfill(status=503, content_type='application/json', body='{"detail":"fixture_read_failure"}')
                    page.route(pattern, read_failure)
                    page.goto(endpoint + '/changes?change=' + changes['cancel']['id'])
                    dialog = page.get_by_role('dialog')
                    expect(dialog.get_by_text('暂时无法读取这份变更', exact=False)).to_be_visible()
                    expect(dialog.get_by_role('radio')).to_have_count(0)
                    page.unroute(pattern, read_failure)
                    dialog.get_by_role('button', name='重新读取').click()
                    expect(dialog.get_by_role('heading', name='验收研究策略 · cancel · 第 1 版')).to_be_visible()
                    checks['failed_read_hides_actions_and_retry_recovers'] = True

                    page.set_viewport_size({'width': 390, 'height': 844})
                    expect(dialog.get_by_role('heading', name='验收研究策略 · cancel · 第 1 版')).to_be_visible()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert dialog.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
                    page.screenshot(path=str(args.out_dir / 'review-mobile.png'), full_page=True)
                    checks['mobile_review_no_horizontal_overflow'] = True
                    page.keyboard.press('Escape')
                    expect(dialog).to_have_count(0)
                    expect(page.locator('.change-mobile-list')).to_be_visible()
                    page.screenshot(path=str(args.out_dir / 'changes-mobile.png'), full_page=True)
                    checks['escape_and_mobile_list_actions'] = True
                    assert not page_errors
                    checks['no_browser_runtime_errors'] = True
                    browser.close()
            finally:
                proc.terminate()
                proc.wait(timeout=10)
    (args.out_dir / 'result.json').write_text(json.dumps({'schema_version': 'enterprise-change-review-smoke/v1',
        'checks': checks, 'passed': all(checks.values()), 'real_control_api': True, 'identity': 'isolated_dev_headers',
        'faults': ['lost_post_response', 'read_503'], 'openshell_execution_tested': False, 'production_eligible': False}, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': all(checks.values()), 'checks': len(checks)}))


if __name__ == '__main__':
    main()
