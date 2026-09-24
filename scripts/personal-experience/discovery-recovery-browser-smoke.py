#!/usr/bin/env python3
"""Real filesystem discovery failures and recovery through a user service."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import traceback
from pathlib import Path
from types import SimpleNamespace

from playwright.sync_api import expect, sync_playwright
from background_setup_harness import BackgroundSetupMixin, fixture_directory

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('fixture', ROOT / 'scripts/validate-intent-v2-hermes.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class Harness(BackgroundSetupMixin, fixture.Harness):
    pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args()
    args.background_service = True
    if os.geteuid() == 0:
        parser.error('permission fault needs an unprivileged user')
    args.out_dir.mkdir(parents=True, exist_ok=False)
    cleanup = {'safe': False}
    checks, service_checks, failure = {}, {}, None
    with fixture_directory(args, cleanup) as directory:
        root = Path(directory)
        h = Harness(root, SimpleNamespace(installer_managed_profile=True, hermes_cli=root/'unused-cli'))
        shutil.copy2(args.binary, h.binary)
        home = Path(h.env['HOME'])
        skills = home/'.agents/skills'
        good, denied = skills/'readable-fixture', skills/'blocked-fixture'
        for skill in (good, denied):
            skill.mkdir(parents=True)
            (skill/'SKILL.md').write_text(f'---\nname: {skill.name}\ndescription: Synthetic discovery fixture.\n---\nRead synthetic notes.\n')
        denied.chmod(0)
        try:
            h.start()
            pairing = h.command([str(h.binary), 'pair', '--port', str(h.service_port)])
            code = re.search(r'\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b', pairing).group()
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                page = browser.new_page(viewport={'width': 1440, 'height': 1000}, locale='zh-CN')
                errors, scans, mutations = [], [], []
                page.on('pageerror', lambda _: errors.append('pageerror'))
                def observe(request):
                    if request.method == 'POST' and request.url.endswith('/v1/discovery/scan'):
                        scans.append(request.post_data_json)
                    if request.method in {'POST','PUT','DELETE'} and '/v1/adapter/' in request.url:
                        mutations.append('adapter-mutation')
                page.on('request', observe)
                page.goto(h.endpoint+'/overview')
                page.get_by_label('配对码', exact=True).fill(code)
                page.get_by_role('button', name='建立管理会话', exact=True).click()
                expect(page.locator('[data-scan-state="partial"]')).to_be_visible(timeout=30000)
                status = h.api('/v1/discovery')
                assert status['run']['state'] == 'partial' and status['run']['skill_count'] == 1
                assert any('blocked-fixture' in issue and issue.startswith('unreadable:') for issue in status['run']['issues'])
                checks['partial_keeps_readable_skill_and_reports_unreadable_directory'] = True
                assert scans == [{}]
                checks['initial_discovery_single_scan'] = True
                page.get_by_text(re.compile(r'^查看未完成的扫描项')).click()
                expect(page.get_by_text(re.compile(r'^无法读取：.*blocked-fixture'))).to_be_visible()
                checks['read_failure_visible_in_chinese'] = True
                before_id = status['run']['run_id']
                page.reload()
                expect(page.locator('[data-scan-state="partial"]')).to_have_attribute('data-scan-id', before_id)
                assert scans == [{}]
                checks['reload_retains_result_without_repeat_scan'] = True
                page.get_by_text('高级选项：补充目录与扫描范围', exact=True).click()
                page.get_by_label('添加目录类型', exact=True).select_option('skill_dir')
                path = page.get_by_label('额外目录（可选）', exact=True)
                link = root/'linked-skills'
                link.symlink_to(good, target_is_directory=True)
                for name, value in [('missing',root/'missing'), ('symlink',link), ('unreadable',denied)]:
                    path.fill(str(value))
                    with page.expect_response(lambda res: res.url.endswith('/v1/discovery/preview')) as response:
                        page.get_by_role('button', name='预览扫描范围', exact=True).click()
                    assert response.value.status == 400, f'{name} directory accepted'
                    expect(page.get_by_role('alert')).to_be_visible()
                    expect(path).to_have_value(str(value))
                    expect(page.get_by_role('button', name='添加目录并扫描', exact=True)).to_be_disabled()
                    assert h.api('/v1/discovery')['run']['run_id'] == before_id and scans == [{}]
                    checks[f'{name}_preview_refused_keeps_input_without_scan'] = True
                denied.chmod(0o700)
                page.get_by_role('button', name='重新发现', exact=True).click()
                expect(page.locator('[data-scan-state="succeeded"]')).to_be_visible(timeout=30000)
                recovered = h.api('/v1/discovery')
                assert recovered['run']['skill_count'] == 2 and recovered['run']['issue_count'] == 0
                assert recovered['run']['run_id'] != before_id and scans == [{},{}]
                checks['permission_restored_rescan_recovers_both_skills'] = True
                assert not mutations and not errors
                checks['no_adapter_changes_or_browser_errors'] = True
                page.screenshot(path=str(args.out_dir/'recovered.png'), full_page=True)
                browser.close()
        except Exception as exc:
            frames = [frame for frame in traceback.extract_tb(exc.__traceback__) if Path(frame.filename).resolve() == Path(__file__).resolve()]
            failure = {'category': type(exc).__name__, 'line': frames[-1].lineno if frames else None}
        finally:
            denied.chmod(0o700)
            h.close(verify_reentry=False)
            service_checks = h.service_checks
            cleanup['safe'] = True
    report = {'schema_version':'discovery-recovery-browser/v1','passed':failure is None and all(checks.values()),
              'binary_sha256':hashlib.sha256(args.binary.read_bytes()).hexdigest(), 'checks':checks,
              'service_checks':service_checks,'failure':failure,'production_eligible':False,
              'scope':'real filesystem permission failures, browser and isolated systemd service; no HTTP mock or model'}
    (args.out_dir/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
