"""Read actual behavior evidence via production UI and a private live API.

Only the synthetic loopback session is intercepted; all Control API responses
come from the real service. A short-lived synthetic RS256 token arrives on stdin.
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from browser_fixture_identity import install_fixture_session
from playwright.sync_api import expect, sync_playwright


def main():
    settings = json.load(sys.stdin)
    endpoint, out = settings['endpoint'], Path(settings['out'])
    assert urlsplit(endpoint).hostname == '127.0.0.1'
    requests, errors = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1365, 'height': 1000})
        page.on('pageerror', lambda e: errors.append(str(e)))

        def identity(route):
            parsed = urlsplit(route.request.url)
            assert (parsed.scheme, parsed.netloc) == (urlsplit(endpoint).scheme, urlsplit(endpoint).netloc)
            path = parsed.path
            requests.append({'method': route.request.method, 'path': path})
            headers = {k: v for k, v in route.request.headers.items() if not k.lower().startswith('x-dev-')}
            route.continue_(headers={**headers, 'authorization': settings['authorization']})

        page.route('**/api/v1/**', identity)
        install_fixture_session(page)
        page.goto(endpoint + '/changes?change=c&view=execution')
        dialog = page.get_by_role('dialog', name='部署与审计')
        dialog.get_by_role('button', name='查看行为测评').click()
        panel = dialog.get_by_role('region', name='OpenShell 行为测评')
        expect(panel.get_by_text('该次观测已采信', exact=True)).to_be_visible()
        panel.get_by_role('button', name='重新核验当前目标').click()
        expect(panel.get_by_text('核验时，该范围行为已验证', exact=True)).to_be_visible()
        expect(panel.locator('.behavior-assessment').get_by_text(settings['target'], exact=True)).to_be_visible()
        expect(panel.get_by_role('button', name='开始受控测评')).to_have_count(0)
        page.screenshot(path=str(out / 'live-browser-desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        panel.get_by_text('核验时，该范围行为已验证', exact=True).scroll_into_view_if_needed()
        assert dialog.evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
        page.screenshot(path=str(out / 'live-browser-mobile.png'), full_page=True)
        assert not errors
        assert any(r['path'].endswith('/behavior-assessment') and r['method'] == 'POST' for r in requests)
        assert not any(r['path'].endswith('/behavior-verifications') and r['method'] == 'POST' for r in requests)
        browser.close()
    (out / 'live-browser.json').write_text(json.dumps({'passed': True, 'real_control_api_responses': True,
        'synthetic_rs256_viewer': True, 'no_active_probe_post': True, 'current_grade_displayed': True,
        'readonly_probe_action_hidden': True, 'narrow_viewport_no_overflow': True,
        'browser_errors': errors, 'requests': requests}, indent=2) + '\n')


if __name__ == '__main__':
    main()
