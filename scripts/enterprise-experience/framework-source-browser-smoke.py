"""Framework source UI: isolated fixtures only, never production acceptance."""
import argparse
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


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
            if self.path.startswith('/agents/'):
                self.path = '/index.html'
            super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=args.web))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    state = {'allowed': True, 'status': 'historical_reported_source', 'error': False, 'reads': 0, 'hold': False}
    delayed = []
    violations, errors, checks = [], [], []
    now = '2026-09-25T00:00:00Z'

    def intercept(route):
        request = route.request
        url = urlparse(request.url)
        if url.hostname != '127.0.0.1' or url.port != server.server_port or request.method != 'GET':
            violations.append('unexpected network or write')
            route.abort()
            return
        if not url.path.startswith('/api/'):
            route.continue_()
            return
        path = url.path
        status, body = 200, {}
        if path.endswith('/console-context'):
            body = {'schema_version': 'console-context/v1', 'evaluated_at': now,
                    'tenant': {'id': 'fixture', 'name': 'Fixture'}, 'actor': {'id': 'fixture', 'type': 'user'},
                    'authentication': 'development_headers', 'roles': [], 'custom_role_count': 0,
                    'access': dict.fromkeys(['workspace', 'overview', 'agents', 'permissions', 'findings',
                                            'policies', 'changes', 'runtime_bindings', 'environments',
                                            'audit', 'settings'], True),
                    'actions': dict.fromkeys(['confirm_assets', 'manage_environment', 'enroll_devices',
                                             'manage_policy', 'propose_change', 'approve_change'], False)}
            body['access']['environments'] = state['allowed']
        elif path == '/api/v1/agents/agt-one':
            body = {'id': 'agt-one', 'name': 'Fixture OpenClaw role', 'framework': 'openclaw',
                    'status': 'candidate', 'updated_at': now, 'attributes': {}, 'evidence_ids': []}
        elif path.endswith('/evidence'):
            body = []
        elif path.endswith('/framework-source'):
            state['reads'] += 1
            if state['hold']:
                delayed.append(route)
                return
            body = {'schema_version': 'enterprise-framework-source-view/v1', 'asset_id': 'agt-one',
                    'status': state['status'], 'runtime_status': 'unverified',
                    'skill_relationship_status': 'unresolved', 'effective_permissions': None, 'source': None}
            if state['status'] == 'historical_reported_source':
                body['source'] = {'framework': 'openclaw', 'instance_key': 'a' * 64,
                                  'environment_id': 'env-one', 'device_id': 'edge-one', 'device_revoked': True,
                                  'config_sha256': 'b' * 64, 'evidence_id': '<script>bad()</script>',
                                  'observation_id': 'evo-one', 'observed_at': now}
            if state['error']:
                status, body = 503, {'detail': 'fixture unavailable'}
        elif path.endswith('/discovery-origin'):
            body = {'schema_version': 'enterprise-discovery-origin/v1', 'asset_id': 'agt-one',
                    'status': 'legacy_unresolved', 'environment': None, 'device': None,
                    'reported_framework': 'openclaw', 'assigned_role': None,
                    'observations': [], 'observations_truncated': False}
        elif path.endswith('/skill-selections'):
            body = {'schema_version': 'enterprise-role-skill-observations/v1', 'asset_id': 'agt-one',
                    'status': 'no_recorded_declaration', 'relationship_status': 'unresolved',
                    'effective_permissions': None, 'observations': [], 'observations_truncated': False}
        else:
            status, body = 404, {'detail': 'fixture unavailable'}
        route.fulfill(status=status, json=body)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/*', intercept)
            page.goto(f'http://127.0.0.1:{server.server_port}/agents/agt-one')
            panel = page.get_by_role('region', name='框架配置实例来源', exact=True)
            expect(panel).to_contain_text('历史来源')
            expect(panel).to_contain_text('已吊销，仅保留历史')
            expect(panel).to_contain_text('技能安装关系仍未确认')
            summary = panel.locator('summary')
            summary.focus()
            summary.press('Enter')
            expect(panel.locator('details')).to_have_attribute('open', '')
            expect(panel).to_contain_text('<script>bad()</script>')
            assert panel.locator('script').count() == 0
            assert summary.evaluate('(e) => e.matches(":focus-visible")')
            checks.append('historical_semantics_keyboard_and_text_only')
            for width in (375, 768, 1280):
                page.set_viewport_size({'width': width, 'height': 1000})
                panel.scroll_into_view_if_needed()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                assert page.locator('.content').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
                if width != 768:
                    page.screenshot(path=str(args.out / f'framework-source-{width}.png'), animations='disabled')
            checks.append('responsive_no_overflow')
            state['error'] = True
            panel.get_by_role('button', name='重新核对框架来源').click()
            expect(panel.get_by_role('alert')).to_contain_text('读取失败')
            expect(panel).not_to_contain_text('已吊销')
            state['error'] = False
            for status, label in [('no_recorded_source', '不代表未安装'), ('source_unavailable', '不能按名称')]:
                state['status'] = status
                panel.get_by_role('button', name='重新核对框架来源').click()
                expect(panel).to_contain_text(label)
            checks.append('retry_and_distinct_empty_states')
            state['hold'] = True
            panel.get_by_role('button', name='重新核对框架来源').click()
            expect(panel.get_by_role('status')).to_contain_text('正在核对')
            expect(panel).not_to_contain_text('不能按名称')
            assert len(delayed) == 1
            state['hold'] = False
            state['status'] = 'historical_reported_source'
            panel.get_by_role('button', name='重新核对框架来源').click()
            expect(panel).to_contain_text('历史来源')
            with page.expect_response(lambda response: response.url.endswith('/framework-source')
                                      and response.status == 503):
                delayed.pop().fulfill(status=503, json={'detail': 'stale fixture failure'})
            # Flush browser tasks after the rejected old promise settles.
            page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
            expect(panel.get_by_role('alert')).to_have_count(0)
            expect(panel).to_contain_text('历史来源')
            checks.append('loading_and_old_failure_cannot_override_new_result')
            state['allowed'] = False
            reads = state['reads']
            page.reload()
            expect(page.get_by_role('heading', name='Fixture OpenClaw role', exact=True)).to_be_visible()
            expect(panel).to_have_count(0)
            assert state['reads'] == reads
            checks.append('permission_filter_no_source_request')
            assert not violations and not errors
            checks.append('no_writes_external_requests_or_uncaught_errors')
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    report = {'scope': 'isolated-mock-browser-not-production', 'checks': checks,
              'violations': violations, 'errors': errors, 'source_reads': state['reads']}
    (args.out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
