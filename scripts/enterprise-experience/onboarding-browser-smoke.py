#!/usr/bin/env python3
"""Isolated real Control API, SQLite dev identity, native Edge and framework connector.

No production identity/provider or real user's device/configuration is accessed.
Enrollment/device secrets stay in process memory and temporary private state.
"""
import argparse
import hashlib
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


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edge', type=Path, required=True)
    parser.add_argument('--connector-dir', type=Path, required=True)
    parser.add_argument('--web', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--framework', choices=('hermes', 'openclaw'), default='hermes')
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=False)
    checks = {}
    with tempfile.TemporaryDirectory(prefix='siq-enterprise-onboarding-') as raw:
        root = Path(raw)
        home = root / 'home'
        profile = home / '.hermes/profiles/fixture'
        profile.mkdir(parents=True)
        (profile / 'config.yaml').write_text('model: synthetic-model\n')
        (profile / 'SOUL.md').write_text('Synthetic fixture role for enterprise onboarding.\n')
        openclaw = home / '.openclaw'
        openclaw.mkdir()
        (openclaw / 'openclaw.json').write_text(json.dumps({'agents': {'list': [{'id': 'fixture-openclaw', 'name': 'Fixture OpenClaw'}]}}))
        env = {k: v for k, v in os.environ.items() if k in ('PATH', 'LANG', 'LC_ALL', 'TZ')}
        env.update({'HOME': str(home), 'SIQ_AS_DEV': '1', 'SIQ_AS_ALLOW_SQLITE': '1',
            'SIQ_AS_DATABASE_URL': f'sqlite:///{root}/api.db', 'SIQ_AS_SIGNING_KEY_FILE': str(root / 'signing.seed'),
            'SIQ_AS_ENFORCEMENT_BACKEND': 'fake', 'SIQ_EDGE_STATE_DIR': str(root / 'edge-state'),
            'SIQ_CONNECTOR_BIN_DIR': str(args.connector_dir.resolve()), 'SIQ_AS_HEARTBEAT_STALE_SECONDS': '90'})
        listen = port()
        endpoint = f'http://127.0.0.1:{listen}'
        # Mount the already built DEV-only UI after real API routes. No API stubs.
        bootstrap = root / 'serve.py'
        bootstrap.write_text('import sys\nfrom pathlib import Path\n' +
            f'sys.path.insert(0, {str(ROOT / "apps/control-api")!r})\n' +
            'from app.main import app\nfrom fastapi.responses import FileResponse\nimport uvicorn\n' +
            f'WEB = Path({str(args.web.resolve())!r})\n' +
            '@app.get("/{path:path}")\ndef web(path: str):\n' +
            '    target=(WEB/path).resolve()\n' +
            '    if not target.is_relative_to(WEB) or not target.is_file(): target=WEB/"index.html"\n' +
            '    return FileResponse(target)\n' +
            f'uvicorn.run(app,host="127.0.0.1",port={listen},log_level="error",access_log=False)\n')
        headers = {'X-Dev-Tenant-Id': 'dev-tenant', 'X-Dev-User-Id': 'fixture-operator',
            'X-Dev-Roles': 'platform_operator,agent_owner', 'Content-Type': 'application/json'}
        def api(path, body=None, expected=200, custom=None):
            req = urllib.request.Request(endpoint + path, headers=custom or headers,
                data=json.dumps(body).encode() if body is not None else None)
            try:
                response = urllib.request.urlopen(req, timeout=5)
            except urllib.error.HTTPError as exc:
                response = exc
            with response:
                payload = json.loads(response.read())
                assert response.status == expected, f'HTTP status {response.status} expected {expected}'
                return payload
        def command(arguments, code=None, expected=0):
            run = subprocess.run([str(args.edge.resolve()), *arguments], env=env, input=code, check=False,
                capture_output=True, text=True, timeout=30)
            assert run.returncode == expected, f'Edge command {arguments[0]} exit {run.returncode}'
            if code:
                assert code.strip() not in run.stdout + run.stderr
            return run
        heartbeat = None
        with tempfile.TemporaryFile() as logs:
            service = subprocess.Popen([str(ROOT / 'apps/control-api/.venv/bin/python'), str(bootstrap)], env=env, stdout=logs, stderr=logs)
            try:
                for _ in range(100):
                    assert service.poll() is None, 'isolated API exited'
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
                    page.goto(endpoint + '/environments')
                    page.get_by_label('环境名称', exact=True).fill('验收 DGX Spark')
                    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/api/v1/environments')) as created:
                        page.get_by_role('button', name='创建环境并接入', exact=True).click()
                    assert created.value.status == 201
                    environment = created.value.json()
                    expect(page.get_by_role('region', name='环境接入引导')).to_be_visible()
                    assert any(e['id'] == environment['id'] and e['mode'] == 'discovery' for e in api('/api/v1/environments'))
                    checks['browser_create_environment_persisted_discovery'] = True
                    page.get_by_label('设备可访问的控制面根地址', exact=True).fill(endpoint)
                    page.get_by_label('我已确认目标设备可访问此地址，并已准备好 Edge 与所选 Connector', exact=True).check()
                    with page.expect_response(lambda r: r.url.endswith('/edge-enrollment')) as enrolled:
                        page.get_by_role('button', name='生成一次性注册码', exact=True).click()
                    enrollment = enrolled.value.json()['code']
                    expect(page.get_by_label('一次性注册码', exact=True)).to_have_value(enrollment)
                    assert enrollment not in '\n'.join(page.locator('pre').all_text_contents())
                    assert enrollment not in page.url
                    storage = page.evaluate('JSON.stringify([Object.entries(localStorage),Object.entries(sessionStorage)])')
                    assert enrollment not in storage
                    checks['code_only_in_memory_not_commands_url_storage'] = True
                    page.context.grant_permissions(['clipboard-read', 'clipboard-write'], origin=endpoint)
                    page.get_by_role('button', name='复制注册码', exact=True).click()
                    expect(page.get_by_text('注册码已复制，请在目标设备的提示中粘贴。', exact=True)).to_be_visible()
                    assert page.evaluate('navigator.clipboard.readText()') == enrollment
                    page.evaluate('navigator.clipboard.writeText("")')
                    checks['copy_button_writes_exact_code_to_clipboard'] = True
                    page.get_by_label('设备终端', exact=True).select_option('powershell')
                    expect(page.locator('pre').first).to_contain_text('edge-agent.exe register')
                    assert enrollment not in page.locator('pre').first.inner_text()
                    page.get_by_label('设备终端', exact=True).select_option('bash')
                    expect(page.locator('pre').first).to_contain_text('./edge-agent register')
                    checks['terminal_selector_switches_secret_free_commands'] = True
                    expect(page.get_by_role('button', name='提交发现任务', exact=True)).to_be_disabled()
                    command(['register', '--control-plane', endpoint, '--enrollment-code-stdin'], enrollment + '\n')
                    state_path = root / 'edge-state/state.json'
                    state_before = state_path.read_bytes()
                    command(['register', '--control-plane', endpoint, '--enrollment-code-stdin'], enrollment + '\n', expected=1)
                    assert state_path.read_bytes() == state_before
                    checks['native_stdin_registration_and_repeat_preserves_state'] = True
                    route = f'/api/v1/environments/{environment["id"]}/onboarding'
                    status = api(route)
                    assert status['device_count'] == 1 and status['devices'][0]['status'] == 'waiting'
                    page.get_by_role('button', name='刷新接入进度', exact=True).click()
                    expect(page.get_by_text('已注册，等待心跳', exact=True)).to_be_visible()
                    checks['registered_not_confused_with_heartbeat'] = True
                    heartbeat = subprocess.Popen([str(args.edge.resolve()), 'heartbeat'], env=env, stdout=logs, stderr=logs)
                    for _ in range(100):
                        assert heartbeat.poll() is None
                        if api(route)['devices'][0]['status'] == 'online':
                            break
                        time.sleep(.1)
                    else:
                        raise RuntimeError('heartbeat not observed')
                    page.get_by_role('button', name='刷新接入进度', exact=True).click()
                    expect(page.get_by_text('最近心跳正常', exact=True)).to_be_visible()
                    page.get_by_label('发现框架', exact=True).select_option(args.framework)
                    expect(page.get_by_role('button', name='提交发现任务', exact=True)).to_be_enabled()
                    checks['native_heartbeat_independent_readback'] = True
                    with page.expect_response(lambda r: r.url.endswith('/api/v1/scans')) as scan:
                        page.get_by_role('button', name='提交发现任务', exact=True).click()
                    task_id = scan.value.json()['task_id']
                    expect(page.get_by_text('等待设备领取', exact=True)).to_be_visible()
                    assert api(route)['scans'][0]['id'] == task_id
                    checks['browser_scan_pending_no_premature_success'] = True
                    task_result = command(['tasks'])
                    diagnostic = task_result.stderr.replace(str(root), '<fixture>')
                    for private in [enrollment, json.loads(state_path.read_text())['secret']]:
                        diagnostic = diagnostic.replace(private, '[redacted]')
                    (args.out_dir / 'task-log.sanitized.txt').write_text(diagnostic)
                    status = api(route)
                    assert status['scans'][0]['status'] == 'delivered', status['scans'][0]['status']
                    assert status['scans'][0]['candidate_count'] > 0 and status['evidence_count'] > 0
                    assert status['scans'][0]['device_identity'] == status['devices'][0]['device_identity']
                    page.get_by_role('button', name='刷新接入进度', exact=True).click()
                    expect(page.get_by_text('扫描已完成', exact=True)).to_be_visible()
                    checks['native_connector_signed_upload_receipt_readback'] = True
                    page.reload()
                    expect(page.get_by_text('扫描已完成', exact=True)).to_be_visible()
                    expect(page.get_by_label('一次性注册码', exact=True)).to_have_count(0)
                    assert environment['id'] in page.url
                    checks['refresh_restores_environment_progress_without_code'] = True
                    # Same-name replay is rejected, not a duplicate created after a lost response.
                    page.get_by_label('环境名称', exact=True).fill('验收 DGX Spark')
                    page.get_by_role('button', name='创建环境并接入', exact=True).click()
                    expect(page.get_by_text('同名环境已存在，请刷新列表并选择该环境继续。', exact=True)).to_be_visible()
                    assert len(api('/api/v1/environments')) == 1
                    checks['duplicate_name_clear_409_no_extra_environment'] = True
                    page.route('**/onboarding', lambda r: r.fulfill(status=503, json={'detail': 'fixture_unavailable'}))
                    page.get_by_role('button', name='刷新接入进度', exact=True).click()
                    expect(page.get_by_role('alert').filter(has_text='无法读取接入进度')).to_be_visible()
                    expect(page.get_by_text('扫描已完成', exact=True)).to_have_count(0)
                    expect(page.get_by_role('button', name='提交发现任务', exact=True)).to_be_disabled()
                    page.unroute('**/onboarding')
                    page.get_by_role('button', name='刷新接入进度', exact=True).click()
                    expect(page.get_by_text('扫描已完成', exact=True)).to_be_visible()
                    checks['failed_status_removes_old_success_and_recovers'] = True
                    page.get_by_role('link', name='查看组织资产清单', exact=True).click()
                    expect(page.get_by_role('heading', name='智能体资产', exact=True)).to_be_visible()
                    page.get_by_role('tab', name='发现候选', exact=False).click()
                    expect(page.locator('tbody tr').first).to_be_visible()
                    candidates = api('/api/v1/candidates')
                    assert len(candidates) == 1
                    expect(page.get_by_role('link', name=candidates[0]['name'], exact=True)).to_be_visible()
                    checks['actual_asset_list_link'] = True
                    page.goto(endpoint + '/environments?environment=' + environment['id'])
                    expect(page.get_by_text('扫描已完成', exact=True)).to_be_visible()
                    page.set_viewport_size({'width': 375, 'height': 900})
                    region = page.get_by_role('region', name='环境接入引导')
                    checks['setup_no_horizontal_overflow_375'] = region.evaluate('el => el.scrollWidth <= el.clientWidth')
                    page.screenshot(path=str(args.out_dir / 'onboarding-mobile.png'), full_page=True, animations='disabled')
                    page.get_by_role('link', name='查看组织资产清单', exact=True).scroll_into_view_if_needed()
                    page.screenshot(path=str(args.out_dir / 'onboarding-mobile-results.png'), animations='disabled')
                    page.set_viewport_size({'width':1440,'height':1000})
                    page.get_by_role('heading', name='环境与设备', exact=True).scroll_into_view_if_needed()
                    page.screenshot(path=str(args.out_dir / 'onboarding-desktop.png'), full_page=True, animations='disabled')
                    page.get_by_role('link', name='查看组织资产清单', exact=True).scroll_into_view_if_needed()
                    page.screenshot(path=str(args.out_dir / 'onboarding-desktop-results.png'), animations='disabled')
                    checks['no_browser_errors'] = not errors
                    assert all(checks.values()), [key for key, val in checks.items() if not val]
                    browser.close()
            finally:
                for proc in (heartbeat, service):
                    if proc is not None and proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait(timeout=10)
    payload = {'schema_version': 'siq.enterprise-onboarding-browser/v1', 'passed': all(checks.values()), 'checks': checks,
        'edge_sha256': hashlib.sha256(args.edge.read_bytes()).hexdigest(),
        'framework': args.framework,
        'connector_sha256': hashlib.sha256((args.connector_dir / (args.framework + '-connector')).read_bytes()).hexdigest(),
        'harness_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope': 'Real isolated SQLite/dev-auth API, DEV fixture UI, native Edge and selected framework connector; synthetic profile. No production IAM, native model or enforcement.',
        'write_credentials_in_evidence': False}
    (args.out_dir / 'result.sanitized.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': payload['passed'], 'checks': len(checks)}))


if __name__ == '__main__':
    main()
