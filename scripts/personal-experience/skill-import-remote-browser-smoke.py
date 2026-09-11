#!/usr/bin/env python3
"""Verify remote import UI: real daemon for denied URL; explicit Go DTO fixtures for successful remote responses."""

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("daemon_fixture", REPO / "scripts/validate-intent-v2-hermes.py")
fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    args.binary = args.binary.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    checks = {}
    sample_path = REPO / "apps/agentshield/testdata/contracts/local-skill-import-result.v2.sample.json"
    sample = json.loads(sample_path.read_text())
    with tempfile.TemporaryDirectory(prefix="siq-remote-browser-") as temp:
        root = Path(temp)
        args.installer_managed_profile = True
        args.hermes_cli = root / "unavailable-hermes-cli"
        h = fixture.Harness(root, args)
        shutil.copy2(args.binary, h.binary)
        try:
            h.start()
            pairing = h.command([str(h.binary), "pair", "--port", h.endpoint.rsplit(":", 1)[1]])
            code = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing).group()
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                errors = []
                page.on("pageerror", lambda _: errors.append("pageerror"))
                page.goto(h.endpoint + "/skill-imports")
                page.get_by_label("配对码", exact=True).fill(code)
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                expect(page.get_by_label("来源类型", exact=True)).to_be_enabled()
                page.get_by_label("来源类型", exact=True).select_option("https_zip")
                expect(page.get_by_label("本机绝对路径", exact=True)).to_have_count(0)
                page.get_by_label("HTTPS ZIP 下载链接", exact=True).fill(
                    "https://127.0.0.1/private?token=private-query"
                )
                page.get_by_label("操作者", exact=True).fill("fixture-human")
                page.get_by_role("button", name="导入并检查", exact=True).click()
                expect(page.get_by_role("alert")).to_contain_text("下载链接不符合要求")
                fixture.require(not h.api("/v1/skill-imports")["items"], "denied URL published candidate")
                checks["real_daemon_blocks_loopback_url_without_publication"] = True
                page.get_by_role("button", name="开始新的导入", exact=True).click()
                expect(page.get_by_label("HTTPS ZIP 下载链接", exact=True)).to_be_editable()
                source = "https://download.example.com/repo.zip?token=private-query"
                page.get_by_label("HTTPS ZIP 下载链接", exact=True).fill(source)
                page.get_by_label("ZIP 内的 Skill 目录（可选）", exact=True).fill("repo/skills/report")
                page.get_by_label("预期 SHA256（可选）", exact=True).fill("bad")
                fixture.require(
                    not page.locator("form").evaluate("el => el.checkValidity()"), "invalid pin accepted by form"
                )
                page.get_by_label("预期 SHA256（可选）", exact=True).fill(sample["import"]["remote"]["archive_sha256"])
                checks["source_specific_fields_and_pin_validation"] = True
                page.screenshot(path=str(args.out_dir / "remote-form-desktop.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                expect(page.locator(".sidebar")).to_be_hidden()
                fixture.require(
                    page.locator("main.content").evaluate("el => el.scrollWidth <= el.clientWidth"), "form overflow"
                )
                page.screenshot(
                    path=str(args.out_dir / "remote-form-mobile.png"), full_page=True, animations="disabled"
                )
                checks["mobile_remote_form_no_horizontal_overflow"] = True
                page.set_viewport_size({"width": 1440, "height": 1000})
                bodies = []

                def remote_response(route):
                    body = route.request.post_data_json
                    bodies.append(body)
                    if len(bodies) == 1:
                        route.abort("connectionfailed")
                        return
                    result = json.loads(json.dumps(sample))
                    result["import"]["import_id"] = body["import_id"]
                    result["reused"] = True
                    route.fulfill(status=200, json=result)

                # This intentionally supplies a DTO, not a daemon-signed new record.
                # Core Go tests separately exercise TLS -> ZIP -> signed snapshot.
                page.route("**/v1/skill-imports/remote", remote_response)
                page.get_by_role("button", name="导入并检查", exact=True).click()
                expect(page.get_by_role("button", name="以原请求重试", exact=True)).to_be_enabled()
                import_id = parse_qs(urlparse(page.url).query)["import"][0]
                page.get_by_role("button", name="以原请求重试", exact=True).click()
                expect(page.get_by_role("heading", name="检查结果：import-fixture", exact=True)).to_be_visible()
                fixture.require(len(bodies) == 2 and bodies[0] == bodies[1], "remote retry changed original request")
                fixture.require(
                    bodies[0]
                    == {
                        "schema_version": "local-skill-import-remote-create/v1",
                        "import_id": import_id,
                        "url": source,
                        "archive_path": "repo/skills/report",
                        "expected_sha256": sample["import"]["remote"]["archive_sha256"],
                        "actor_id": "fixture-human",
                    },
                    "remote request mismatched form",
                )
                checks["explicit_response_loss_retry_preserves_exact_remote_request"] = True
                expect(page.locator(".import-result")).to_contain_text("预期 SHA256 已匹配")
                expect(page.locator(".import-result")).to_contain_text("尚未安装")
                page.get_by_text("查看文件清单与内容摘要", exact=True).click()
                expect(page.locator(".import-result")).to_contain_text(sample["import"]["remote"]["archive_sha256"])
                page.screenshot(path=str(args.out_dir / "remote-result-fixture.png"), full_page=True)
                checks["v2_download_metadata_display_without_installation_claim"] = True
                storage = page.evaluate("JSON.stringify({local: {...localStorage}, session: {...sessionStorage}})")
                fixture.require(
                    "private-query" not in storage and "private-query" not in page.url,
                    "download URL persisted in browser metadata",
                )
                checks["download_url_absent_from_location_and_storage"] = True
                fixture.require(not errors, "browser script error")
                for name in ["grants", "admissions"]:
                    fixture.require(not list((h.state / name).glob("*")), "UI changed authority")
                checks["no_browser_errors_or_authority_mutations"] = True
                browser.close()
        finally:
            h.stop()
    report = {
        "schema_version": "personal-remote-import-browser/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "candidate_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "fixture_sha256": hashlib.sha256(sample_path.read_bytes()).hexdigest(),
        "checks": checks,
        "passed": all(checks.values()),
        "method": "real_isolated_daemon_for_denial; explicit_Go_DTO_browser_responses_for_remote_success",
        "limitations": [
            "Successful browser response is an explicit DTO fixture, not a downloaded daemon record",
            "TLS download and signed persistence are verified separately by Go integration tests",
            "No public network, platform installation, or Windows/macOS acceptance",
        ],
    }
    (args.out_dir / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "checks": len(checks)}))


if __name__ == "__main__":
    main()
