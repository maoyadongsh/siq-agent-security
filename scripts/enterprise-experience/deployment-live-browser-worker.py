#!/usr/bin/env python3
"""Click one real deployment; called only by the disposable live-check owner."""
import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('endpoint', 'change', 'environment', 'binding', 'target'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    assert args.endpoint.startswith('http://127.0.0.1:')
    args.out.mkdir(mode=0o700, exist_ok=False)
    headers = {'X-Dev-Tenant-Id': 'dev-tenant', 'X-Dev-User-Id': 'live-owner',
               'X-Dev-Roles': 'platform_operator,security_admin,agent_owner,auditor'}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 1000}, locale='zh-CN')
            page.set_default_timeout(45000)
            errors, posts = [], []
            page.on('pageerror', lambda _: errors.append('pageerror'))

            def identity(route):
                clean = {k: v for k, v in route.request.headers.items() if not k.lower().startswith('x-dev-')}
                if route.request.method == 'POST' and route.request.url.endswith('/deployment-submissions'):
                    posts.append(route.request.post_data_json)
                route.continue_(headers={**clean, **headers})

            page.route(args.endpoint + '/api/v1/**', identity)
            page.goto(args.endpoint + '/changes')
            expect(page.get_by_role('heading', name='变更中心', exact=True)).to_be_visible()
            page.get_by_label('部署环境', exact=True).select_option(args.environment)
            page.get_by_label('运行时绑定', exact=True).select_option(args.binding)
            page.locator('tr').filter(has_text=args.change).get_by_role('button', name='部署', exact=True).click()
            preview = page.get_by_role('dialog', name='确认部署目标')
            expect(preview.get_by_text(args.target, exact=True)).to_be_visible()
            expect(preview.get_by_text('OpenShell', exact=True)).to_be_visible()
            expect(preview.get_by_text('动态更新运行时策略', exact=True)).to_be_visible()
            expect(preview.get_by_role('button', name='确认并部署')).to_be_disabled()
            page.screenshot(path=str(args.out / 'preview-desktop.png'), full_page=True, animations='disabled')
            page.set_viewport_size({'width': 390, 'height': 844})
            assert preview.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
            button = preview.get_by_role('button', name='确认并部署').bounding_box()
            assert button and button['y'] >= 0 and button['y'] + button['height'] <= 844
            page.screenshot(path=str(args.out / 'preview-mobile.png'), full_page=True, animations='disabled')
            page.set_viewport_size({'width': 1440, 'height': 1000})
            preview.get_by_role('checkbox').check()
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/deployment-submissions'), timeout=90000) as pending:
                preview.get_by_role('button', name='确认并部署').click()
            response = pending.value
            assert response.status == 201, 'real deployment submission was not recorded'
            submission = response.json()
            dialog = page.get_by_role('dialog', name='部署与审计')
            expect(dialog.get_by_text('已从服务端独立读取本次部署记录', exact=False)).to_be_visible()
            expect(dialog.get_by_text('配置已读回，行为未验证', exact=True)).to_be_visible()
            expect(dialog.get_by_text('保存部署请求', exact=True)).to_be_visible()
            page.screenshot(path=str(args.out / 'result-desktop.png'), full_page=True, animations='disabled')
            page.set_viewport_size({'width': 390, 'height': 844})
            assert dialog.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
            page.screenshot(path=str(args.out / 'result-mobile.png'), full_page=True, animations='disabled')
            page.reload()
            expect(page.get_by_role('dialog', name='部署与审计').get_by_text('配置已读回，行为未验证', exact=True)).to_be_visible()
            assert len(posts) == 1 and not errors, 'duplicate submission or browser error'
            assert posts[0]['change_request_id'] == args.change
            (args.out / 'result.json').write_text(json.dumps({'passed': True, 'post_count': len(posts),
                'request': posts[0], 'submission': submission,
                'checks': {'real_preview': True, 'explicit_confirmation': True,
                    'one_real_submission': True, 'independent_history': True,
                    'mobile_no_horizontal_overflow': True, 'refresh_read_only': True}},
                ensure_ascii=False, indent=2) + '\n')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
