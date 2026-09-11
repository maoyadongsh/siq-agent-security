#!/usr/bin/env python3
"""Exercise installed Skill history, content drift and visible-page polling in temporary synthetic profiles."""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location(
    "daemon_fixture", REPO / "scripts/validate-intent-v2-hermes.py"
)
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
    with tempfile.TemporaryDirectory(prefix="siq-install-management-") as temp:
        root = Path(temp)
        args.installer_managed_profile = True
        args.hermes_cli = root / "unavailable-hermes-cli"
        h = fixture.Harness(root, args)
        shutil.copy2(args.binary, h.binary)
        source = root / "skill"
        source.mkdir()
        (source / "SKILL.md").write_text(
            "---\nname: install-fixture\ndescription: Read a synthetic report.\n"
            "allowed-tools: read_file\n---\nRead a report.\n"
        )
        config = Path(h.env["HERMES_HOME"]) / "config.yaml"
        config_before = config.read_bytes()
        try:
            h.start()
            target = next(
                item
                for item in h.api("/v1/adapter/instances?platform=hermes")["instances"]
                if item["active"] and item["detected"]
            )
            imported = h.api(
                "/v1/skill-imports",
                {
                    "schema_version": "local-skill-import-create/v1",
                    "import_id": "si-" + "a" * 32,
                    "source_kind": "local_dir",
                    "path": str(source),
                    "actor_id": "fixture-human",
                },
                expected=201,
            )
            rec = imported["import"]
            prepared = h.api(
                "/v1/skill-imports/" + rec["import_id"] + "/permissions",
                {
                    "schema_version": "local-skill-import-permission-create/v1",
                    "request_id": "ip-" + "b" * 32,
                    "artifact_digest": rec["artifact_digest"],
                    "analysis_sha256": rec["analysis_sha256"],
                    "instance_id": target["instance_id"],
                    "actor_id": "fixture-human",
                },
                expected=201,
            )
            grant_id = prepared["grant"]["grant_id"]
            route = "/v1/grants/" + grant_id
            prepared = h.api(
                route + "/patch-desired",
                {
                    "expected_revision": prepared["state_revision"],
                    "actor_id": "fixture-human",
                    "tools": ["read_file"],
                    "filesystem": {"read_only": [str(root)], "read_write": []},
                },
            )
            challenge = h.api(
                route + "/challenge",
                {
                    "expected_revision": prepared["state_revision"],
                    "actor_id": "fixture-human",
                },
            )["challenge"]
            h.api(
                route + "/approve",
                {
                    "expected_revision": prepared["state_revision"],
                    "actor_id": "fixture-human",
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                },
            )
            pairing = h.command(
                [str(h.binary), "pair", "--port", h.endpoint.rsplit(":", 1)[1]]
            )
            code = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing).group()
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1100}, locale="zh-CN"
                )
                errors = []
                page.on("pageerror", lambda _: errors.append("pageerror"))
                page.goto(h.endpoint + "/grants?grant=" + grant_id)
                page.get_by_label("配对码", exact=True).fill(code)
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                expect(page.get_by_label("Skill 安装目录名", exact=True)).to_have_value(
                    "install-fixture"
                )
                page.get_by_label("批准人（人工 actor_id）", exact=True).fill(
                    "fixture-human"
                )
                checks["approved_grant_prefills_portable_skill_directory"] = True
                writes = []
                button = page.get_by_role("button", name="生成安装预览", exact=True)
                button.click()
                expect(page.locator(".install-plan-result")).to_contain_text(
                    "预览已核验，尚未安装。"
                )
                plan_id = parse_qs(urlparse(page.url).query)["install_plan"][0]
                plan = h.api("/v1/skill-installations/plans/" + plan_id)
                install_id = plan_id.replace("sip-", "sin-", 1)
                operation_route = "/v1/skill-installations/operations/" + install_id
                install = page.get_by_role("button", name="确认安装 Skill", exact=True)
                expect(install).to_be_disabled()
                page.get_by_label(
                    "我已核对安装位置、内容和权限，确认安装", exact=True
                ).check()
                expect(install).to_be_enabled()
                page.set_viewport_size({"width": 390, "height": 844})
                expect(page.locator(".sidebar")).to_be_hidden()
                install.scroll_into_view_if_needed()
                expect(install).to_be_in_viewport()
                checkbox = page.get_by_label(
                    "我已核对安装位置、内容和权限，确认安装", exact=True
                )
                fixture.require(
                    checkbox.bounding_box()["width"] < 30,
                    "confirmation checkbox stretched",
                )
                page.screenshot(
                    path=str(args.out_dir / "confirm-mobile.png"), animations="disabled"
                )
                page.set_viewport_size({"width": 1440, "height": 1100})
                checks["explicit_confirmation_required"] = True

                def lose_apply_response(intercept):
                    writes.append(intercept.request.post_data_json)
                    response = intercept.fetch()
                    fixture.require(
                        response.status == 200, "installation did not commit"
                    )
                    fixture.require(
                        response.json()["status"] == "installed_unverified",
                        "unexpected installation status",
                    )
                    intercept.abort("connectionfailed")

                page.route("**/v1/skill-installations/apply", lose_apply_response)
                install.evaluate("button => { button.click(); button.click(); }")
                panel = page.locator(
                    'section[aria-labelledby="installation-result-heading"]'
                )
                expect(panel).to_contain_text(
                    "Skill 文件已安装并完成内容核验，尚未验证运行保护。"
                )
                fixture.require(
                    len(writes) == 1, "duplicate confirmation sent multiple writes"
                )
                fixture.require(
                    writes[0]["plan_signature"] == plan["signature"],
                    "confirmation changed plan",
                )
                fixture.require(
                    "install_plan" not in parse_qs(urlparse(page.url).query),
                    "installed view reloads obsolete preview",
                )
                checks["committed_response_loss_reads_result_without_second_apply"] = (
                    True
                )
                destination = Path(h.env["HERMES_HOME"]) / "skills" / "install-fixture"
                entry = destination / "SKILL.md"
                original = entry.read_bytes()
                fixture.require(
                    original == (source / "SKILL.md").read_bytes(),
                    "target differs from source",
                )
                view = h.api(operation_route)
                fixture.require(
                    view["plan"]["signature"] == plan["signature"],
                    "result bound another preview",
                )
                fixture.require(
                    view["operation"]["runtime_verified"] is False,
                    "installation claimed runtime protection",
                )
                grant = h.api(route)["grant"]
                fixture.require(
                    grant["status"] == "approved", "installation activated grant"
                )
                fixture.require(
                    not h.api("/v1/runtime-identities")["items"],
                    "installation issued identity",
                )
                page.reload()
                expect(panel).to_contain_text(
                    "Skill 文件已安装并完成内容核验，尚未验证运行保护。"
                )
                fixture.require(len(writes) == 1, "reload reinstalled Skill")
                checks["refresh_reads_existing_target_without_activation"] = True
                page.get_by_role("link", name="查看内容变化", exact=True).click()
                expect(page).to_have_url(re.compile(r"/installed-skills\?install_id="))
                history = page.get_by_role("region", name="安装记录", exact=True)
                detail = page.get_by_role("region", name="当前内容检查", exact=True)
                expect(history).to_contain_text("install-fixture")
                expect(detail).to_contain_text("与安装时的内容和归属一致")
                expect(detail).to_contain_text(
                    "权限是否可用、平台接入和运行保护仍需独立验证"
                )
                checks[
                    "installation_link_finds_signed_history_and_current_baseline"
                ] = True
                page.reload()
                expect(detail).to_contain_text("与安装时的内容和归属一致")
                fixture.require(
                    len(writes) == 1, "history refresh repeated installation"
                )
                checks["deep_link_refresh_is_read_only"] = True
                inspections = []
                page.on(
                    "request",
                    lambda r: (
                        inspections.append(r.url)
                        if r.url.endswith("/inspection")
                        else None
                    ),
                )
                entry.write_text("local modification")
                expect(detail).to_contain_text(
                    "检测到安装内容或归属变化", timeout=40000
                )
                expect(detail).to_contain_text("内容或执行权限变化")
                expect(detail).not_to_contain_text("与安装时的内容和归属一致")
                checks["visible_page_automatically_detects_modified_file"] = True
                page.evaluate("""() => {
                    Object.defineProperty(document, 'visibilityState', {value:'hidden', configurable:true});
                    document.dispatchEvent(new Event('visibilitychange'));
                }""")
                expect(detail).to_contain_text("自动检查已暂停")
                count = len(inspections)
                page.wait_for_timeout(31000)
                fixture.require(
                    len(inspections) == count, "hidden page continued polling"
                )
                entry.write_bytes(original)
                page.evaluate("""() => {
                    Object.defineProperty(document, 'visibilityState', {value:'visible', configurable:true});
                    document.dispatchEvent(new Event('visibilitychange'));
                }""")
                expect(detail).to_contain_text("与安装时的内容和归属一致")
                checks["visibility_event_pauses_polling_and_rechecks_on_return"] = True
                extra = destination / "untracked"
                extra.mkdir()
                (extra / "payload.sh").write_text("exit 77\n")
                (destination / "line\nbreak").write_text("untracked")
                original_link = root / "original-entry-link"
                os.link(entry, original_link)
                entry.unlink()
                page.get_by_role("button", name="立即检查内容", exact=True).click()
                expect(detail).to_contain_text("已发现 3 项变化")
                expect(detail).to_contain_text("缺失")
                expect(detail).to_contain_text("line\\nbreak")
                expect(detail).not_to_contain_text("payload.sh")
                fixture.require(
                    (extra / "payload.sh").read_text() == "exit 77\n",
                    "unknown payload changed",
                )
                checks[
                    "missing_and_unknown_entries_reported_without_traversal_or_execution"
                ] = True
                page.set_viewport_size({"width": 1440, "height": 1100})
                detail.evaluate("el => el.scrollIntoView({block:'center'})")
                page.screenshot(
                    path=str(args.out_dir / "inspection-desktop.png"),
                    animations="disabled",
                )
                page.set_viewport_size({"width": 390, "height": 844})
                expect(page.locator(".sidebar")).to_be_hidden()
                detail.evaluate("el => el.scrollIntoView({block:'center'})")
                fixture.require(
                    page.locator("main.content").evaluate(
                        "el => el.scrollWidth <= el.clientWidth"
                    ),
                    "mobile overflow",
                )
                page.screenshot(
                    path=str(args.out_dir / "inspection-mobile.png"),
                    animations="disabled",
                )
                checks["mobile_change_details_and_actions_fit"] = True
                # Fixture restores the original inode without changing product state.
                os.link(original_link, entry)
                (destination / "line\nbreak").unlink()
                (extra / "payload.sh").unlink()
                extra.rmdir()
                page.get_by_role("button", name="立即检查内容", exact=True).click()
                expect(detail).to_contain_text("与安装时的内容和归属一致")

                def failed_inspection(intercept):
                    intercept.fulfill(
                        status=503,
                        content_type="application/json",
                        body='{"error":"skill_install_unavailable"}',
                    )

                page.route(
                    "**/v1/skill-installations/operations/*/inspection",
                    failed_inspection,
                )
                page.get_by_role("button", name="立即检查内容", exact=True).click()
                expect(detail).to_contain_text("当前状态无法确认")
                expect(detail).not_to_contain_text("与安装时的内容和归属一致")
                page.unroute(
                    "**/v1/skill-installations/operations/*/inspection",
                    failed_inspection,
                )
                checks["read_failure_removes_stale_matched_state"] = True
                retained = destination.with_name(destination.name + "-retained")
                destination.rename(retained)
                page.get_by_role("button", name="立即检查内容", exact=True).click()
                expect(detail).to_contain_text("未找到原安装目标")
                expect(detail).to_contain_text("这不代表 SIQ 已完成卸载")
                checks["missing_target_is_not_reported_as_successful_uninstall"] = True
                retained.rename(destination)
                (
                    h.state
                    / "skill-imports"
                    / "blobs"
                    / rec["import_id"]
                    / "payload"
                    / "SKILL.md"
                ).write_text("changed source")
                page.get_by_role("button", name="刷新安装记录", exact=True).click()
                expect(history).to_contain_text("install-fixture")
                expect(detail).to_contain_text("与安装时的内容和归属一致")
                checks[
                    "source_corruption_does_not_hide_signed_installation_baseline"
                ] = True
                page.get_by_role("link", name="查看安装结果与权限", exact=True).click()
                expect(page).to_have_url(re.compile(r"/grants\?grant=.*install_id="))
                expect(panel).to_contain_text("Skill 文件已安装并完成内容核验")
                checks[
                    "history_returns_to_original_installation_and_permission_flow"
                ] = True
                fixture.require(not errors, "browser page error")
                browser.close()
            fixture.require(
                config.read_bytes() == config_before,
                "inspection changed platform configuration",
            )
            fixture.require(
                not h.api("/v1/runtime-identities")["items"],
                "inspection issued runtime identity",
            )
            fixture.require(
                h.api(route)["grant"]["status"] == "approved",
                "inspection changed grant",
            )
            result = {
                "generated_at": datetime.now(UTC).isoformat(),
                "status": "passed",
                "checks": checks,
                "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                "scope": (
                    "Real isolated daemon, browser and synthetic installation. Visible-page polling plus "
                    "fixture visibility events, controlled target/source changes and simulated read failure. "
                    "Unknown payload never executed, no runtime authority or host configuration change. "
                    "No remote update, uninstall or cross-OS acceptance."
                ),
            }
            (args.out_dir / "result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n"
            )
            print(json.dumps({"status": "passed", "checks": len(checks)}))
        finally:
            h.stop()


if __name__ == "__main__":
    main()
