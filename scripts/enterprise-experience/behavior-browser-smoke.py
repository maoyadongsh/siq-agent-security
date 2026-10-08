#!/usr/bin/env python3
"""Production UI on loopback; explicit API fixtures, no real runtime or identity provider."""
from __future__ import annotations

import argparse
import functools
import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from browser_fixture_identity import install_fixture_session
from playwright.sync_api import expect, sync_playwright


def stamp(delta=0):
    return (datetime.now(UTC) + timedelta(seconds=delta)).isoformat().replace('+00:00', 'Z')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=False)
    web = args.web.resolve()
    assert (web / 'index.html').is_file()

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if not (web / urlsplit(self.path).path.lstrip('/')).is_file():
                self.path = '/index.html'
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(web)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f'http://127.0.0.1:{server.server_port}'
    scope = {'target': 'sandbox-browser', 'policy_revision': '2', 'policy_digest': 'a' * 64,
        'transport': 'http_connect', 'endpoint': '127.0.0.1:19090', 'allow_path': '/opt/probe/allow',
        'deny_path': '/opt/probe/deny', 'attempts': 3}
    record = {'schema_version': 'deployment-behavior-operation/v1', 'deployment_id': 'dep-browser',
        'verification_id': 'opv-' + 'a' * 32, 'profile_id': 'approved-browser', 'state': 'accepted',
        'reason_code': 'behavior_candidate_observations_accepted', 'issued_at': stamp(-20), 'expires_at': stamp(240),
        'observed_at': stamp(-10), 'time_window': 'within', 'current_enforcement_verified': False,
        'observation_count': 12, 'scope': scope}
    profile = {'profile_id': 'approved-browser', 'profile_sha256': 'b' * 64, 'issued_at': stamp(-30),
        'expires_at': record['expires_at'], 'timeout_ms': 1000, 'scope': scope}
    state = {'manage': True, 'assessment': 'verified', 'lifetime': 60, 'posts': [], 'records': [record]}
    checks, errors = {}, []

    def api(route):
        path = urlsplit(route.request.url).path
        method = route.request.method
        status, value = 200, []
        headers = {'X-SIQ-List-Limit': '20', 'X-SIQ-List-Returned': '0', 'X-SIQ-List-Truncated': '0'}
        if path.endswith('/console-context'):
            value = {'schema_version': 'console-context/v1', 'evaluated_at': stamp(),
                'tenant': {'id': 'browser-tenant', 'name': '浏览器测试组织'},
                'actor': {'id': 'browser-actor', 'type': 'user'}, 'authentication': 'verified_token',
                'roles': [], 'custom_role_count': 0,
                'access': {k: True for k in ['workspace', 'overview', 'agents', 'permissions', 'findings', 'policies',
                    'changes', 'runtime_bindings', 'environments', 'audit', 'settings']},
                'actions': {k: state['manage'] for k in ['confirm_assets', 'manage_environment', 'enroll_devices',
                    'manage_policy', 'propose_change', 'approve_change']}}
        elif path.endswith('/cr-browser/execution'):
            value = {'schema_version': 'change-execution/v1', 'change_id': 'cr-browser', 'change_status': 'effective',
                'evaluated_at': stamp(), 'deployments_truncated': False, 'expanded': False,
                'audit_access': 'denied', 'audit_events': [], 'audit_truncated': False, 'deployments': [{
                    'id': 'dep-browser', 'environment_id': 'env-browser', 'environment_name': 'DGX Spark 测评环境',
                    'binding_id': 'binding-browser', 'target': scope['target'], 'status': 'effective',
                    'created_at': stamp(-60), 'verification_level': 'config_readback',
                    'independent_result': 'not_checked', 'backend_mutated': None, 'error_digest': None}]}
        elif path.endswith('/deployment-submission'):
            status, value = 404, {'detail': 'not_found'}
        elif path.endswith('/behavior-profiles'):
            value = {'schema_version': 'deployment-behavior-profiles/v1', 'deployment_id': 'dep-browser',
                     'profiles': [profile]}
        elif path.endswith('/behavior-verifications'):
            if method == 'POST':
                body = route.request.post_data_json
                assert body['schema_version'] == 'deployment-behavior-start/v2'
                assert body['profile_sha256'] == profile['profile_sha256']
                assert set(body) == {'schema_version', 'profile_id', 'profile_sha256', 'verification_id'}
                state['posts'].append(body)
                state['records'].insert(0, {**record, 'verification_id': body['verification_id']})
                route.abort()  # Lost acknowledgment after fixture persistence; never automatically retry POST.
                return
            value = state['records']
            headers['X-SIQ-List-Returned'] = str(len(value))
        elif '/behavior-verifications/' in path:
            wanted = path.rsplit('/', 1)[-1]
            value = next(r for r in state['records'] if r['verification_id'] == wanted)
        elif path.endswith('/behavior-assessment'):
            if state['assessment'] == 'failure':
                status, value = 503, {'detail': 'fixture_unavailable'}
            else:
                verified = state['assessment'] == 'verified'
                value = {'schema_version': 'deployment-behavior-assessment/v1', 'deployment_id': 'dep-browser',
                    'verification_id': route.request.post_data_json['verification_id'], 'evaluated_at': stamp(),
                    'valid_until': stamp(state['lifetime']) if verified else None, 'state': state['assessment'],
                    'level': 'enforcement_verified' if verified else 'unverified',
                    'current_enforcement_verified': verified, 'reason_code': 'fixture', 'scope': scope}
        route.fulfill(status=status, content_type='application/json', headers=headers, body=json.dumps(value))

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            page = browser.new_page(viewport={'width': 1365, 'height': 1000})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/api/v1/**', api)
            install_fixture_session(page)
            page.goto(endpoint + '/changes?change=cr-browser&view=execution')
            dialog = page.get_by_role('dialog', name='部署与审计')
            dialog.get_by_role('button', name='查看行为测评').click()
            panel = dialog.get_by_role('region', name='OpenShell 行为测评')
            expect(panel.get_by_text('该次观测已采信', exact=True)).to_be_visible()
            expect(panel.get_by_role('button', name='开始受控测评')).to_be_disabled()
            assert state['posts'] == []
            checks['history_read_never_posts_probe'] = True
            panel.get_by_role('button', name='重新核验当前目标').click()
            expect(panel.get_by_text('核验时，该范围行为已验证', exact=True)).to_be_visible()
            page.screenshot(path=str(args.out_dir / 'desktop.png'), full_page=True)
            checks['current_snapshot_scope_and_time_displayed'] = True
            state['assessment'] = 'changed'
            panel.get_by_role('button', name='重新核验当前目标').click()
            expect(panel.get_by_text('目标或策略与观测不一致', exact=True)).to_be_visible()
            expect(panel.get_by_text('核验时，该范围行为已验证', exact=True)).to_have_count(0)
            checks['changed_scope_removes_positive_display'] = True
            state['assessment'] = 'failure'
            panel.get_by_role('button', name='重新核验当前目标').click()
            expect(panel.get_by_role('alert')).to_contain_text('旧核验结果已清除')
            checks['failed_refresh_clears_prior_snapshot'] = True
            state.update(assessment='verified', lifetime=2)
            panel.get_by_role('button', name='重新核验当前目标').click()
            expect(panel.get_by_text('核验时，该范围行为已验证', exact=True)).to_be_visible()
            expect(panel.get_by_text('核验证据已过期', exact=True)).to_be_visible(timeout=6000)
            checks['expiry_removes_positive_without_network_polling'] = True
            panel.get_by_role('checkbox').check()
            panel.get_by_role('button', name='开始受控测评').click()
            expect(panel.get_by_role('button', name='核对本次请求')).to_be_enabled()
            expect(panel.get_by_role('alert')).to_contain_text('不会自动重发探针')
            assert len(state['posts']) == 1
            panel.get_by_role('button', name='核对本次请求').click()
            expect(panel.get_by_role('button', name='核对本次请求')).to_have_count(0)
            assert len(state['posts']) == 1
            expect(panel.get_by_text('该次观测已采信', exact=True)).to_have_count(2)
            checks['lost_ack_recovers_same_id_without_post_retry'] = True
            page.set_viewport_size({'width': 390, 'height': 844})
            panel.get_by_role('checkbox').scroll_into_view_if_needed()
            assert dialog.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
            page.screenshot(path=str(args.out_dir / 'mobile.png'), full_page=True)
            checks['narrow_viewport_no_horizontal_overflow'] = True
            state['manage'] = False
            page.reload()
            dialog.get_by_role('button', name='查看行为测评').click()
            expect(panel.get_by_text('当前账号可查看记录并核验目标', exact=False)).to_be_visible()
            expect(panel.get_by_role('button', name='开始受控测评')).to_have_count(0)
            checks['readonly_account_has_no_probe_action'] = True
            assert not errors, errors
            checks['no_browser_runtime_errors'] = True
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    (args.out_dir / 'result.json').write_text(json.dumps({'passed': all(checks.values()), 'checks': checks,
        'scope': 'built UI with synthetic API responses; not live OpenShell or production IAM',
        'probe_posts': len(state['posts']), 'browser_errors': errors, 'owned_server_stopped': not thread.is_alive()},
        ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'checks': len(checks)}))


if __name__ == '__main__':
    main()
