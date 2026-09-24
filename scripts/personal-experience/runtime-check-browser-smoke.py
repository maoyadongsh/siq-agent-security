#!/usr/bin/env python3
"""Exercise the runtime-check UI with Chromium, a real daemon and isolated Hermes."""

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import traceback
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("native_fixture", REPO / "scripts/validate-intent-v2-hermes.py")
fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--hermes-cli", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    args.binary, args.hermes_cli = args.binary.resolve(), args.hermes_cli.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.installer_managed_profile = True
    checks = {}
    failure = None
    with tempfile.TemporaryDirectory(prefix="siq-runtime-browser-") as temporary:
        harness = fixture.Harness(Path(temporary), args)
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            pairing = subprocess.run(
                [str(harness.binary), "pair", "--port", str(urlparse(harness.endpoint).port)],
                env=harness.env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            match = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing.stdout)
            fixture.require(pairing.returncode == 0 and match, "browser pairing unavailable")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="zh-CN", timezone_id="Asia/Shanghai")
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda _: errors.append("pageerror"))
                page.goto(harness.endpoint + "/overview")
                page.get_by_label("配对码", exact=True).fill(match.group())
                with page.expect_response(lambda r: r.url.endswith("/v1/pair") and r.status == 200) as paired:
                    page.get_by_role("button", name="建立管理会话", exact=True).click()
                credential = paired.value.json()["session"]
                card = page.locator(".environment-connection").filter(has_text="Hermes · work")
                expect(card).to_be_visible(timeout=30000)
                card.get_by_role("button", name="接入此实例", exact=True).click()
                install = page.get_by_role("dialog")
                install.get_by_label("接入方式", exact=True).select_option("connection")
                expect(install.get_by_label("由 Hermes 同步启用本实例插件")).to_be_checked()
                apply = install.get_by_role("button", name="确认应用", exact=True)
                expect(apply).to_be_enabled(timeout=20000)
                apply.click()
                expect(install).not_to_be_visible(timeout=30000)
                instance = next(i for i in harness.api("/v1/adapter/instances?platform=hermes")["instances"] if i["active"])
                fixture.require(instance["diagnosis"]["configuration_state"] == "ready", "install not read back ready")
                fixture.require(not harness.api("/v1/grants")["grants"], "connection install created grant")
                config = Path(harness.env["HERMES_HOME"]) / "config.yaml"
                installed_config = config.read_bytes()
                checks["browser_installs_native_connection_without_authority"] = True
                checks["installation_preserves_user_setting"] = "fixture_setting: retain" in config.read_text()
                checks["other_profile_preserved"] = (harness.root / "hermes/config.yaml").read_text() == "fixture_default: unchanged\n"
                page.get_by_role("button", name="验证刚接入的实例", exact=True).click()
                dialog = page.get_by_role("dialog")
                start = dialog.get_by_role("button", name="确认并开始自检", exact=True)
                expect(dialog.get_by_text("将执行的检查", exact=True)).to_be_visible(timeout=20000)
                expect(dialog.get_by_label("自检实例 / profile")).to_have_value(
                    next(i for i in harness.api("/v1/adapter/instances?platform=hermes")["instances"] if i["active"])[
                        "instance_id"
                    ]
                )
                fixture.require(not harness.api("/v1/grants")["grants"], "opening preview created grant")
                checks["active_instance_selected_without_authority"] = True
                dialog.get_by_label("确认人", exact=True).fill("synthetic-browser-operator")
                expect(start).to_be_enabled()
                start.click()
                expect(dialog.get_by_role("button", name="取消自检", exact=True)).to_be_visible()
                started_check = dialog.locator("[data-runtime-check-id]").get_attribute("data-runtime-check-id")
                # Closing the view must preserve the in-flight job. Reopening
                # retrieves it from the server without starting another host.
                dialog.get_by_role("button", name="关闭（后台继续）", exact=True).click()
                page.reload()
                card.get_by_role("button", name="验证连接", exact=True).click()
                expect(dialog.get_by_text("本次自检通过", exact=True)).to_be_visible(timeout=140000)
                expect(dialog.get_by_text("临时权限与材料：已撤权并清理", exact=True)).to_be_visible()
                checks["confirmed_native_check_survives_closed_view"] = True
                checks["cleanup_and_five_receipts_visible"] = dialog.get_by_text(
                    "本次关联 5 条回执。", exact=True
                ).is_visible()
                checks["all_probe_evidence_visible"] = dialog.locator(".card li").count() == 5
                fixture.require(len(harness.api("/v1/grants")["grants"]) == 1, "reopening launched duplicate host")
                checks["reopening_does_not_duplicate_launch"] = True
                checks["reload_restores_same_check_without_repairing"] = (
                    dialog.locator("[data-runtime-check-id]").get_attribute("data-runtime-check-id") == started_check
                )
                checks["native_check_preserves_installed_configuration"] = config.read_bytes() == installed_config
                page.screenshot(path=str(args.out_dir / "runtime-check-passed.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                checks["mobile_dialog_content_fits"] = dialog.evaluate(
                    "el => el.scrollWidth <= el.clientWidth + 1 && "
                    "el.getBoundingClientRect().right <= window.innerWidth"
                )
                page.screenshot(path=str(args.out_dir / "runtime-check-mobile.png"), full_page=True)
                start.scroll_into_view_if_needed()
                checks["mobile_confirmation_reachable"] = start.evaluate(
                    "el => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.left >= 0 && "
                    "r.bottom <= window.innerHeight && r.right <= window.innerWidth && "
                    "el.contains(document.elementFromPoint(r.x + r.width/2, r.y + r.height/2)); }"
                )
                page.screenshot(path=str(args.out_dir / "runtime-check-mobile-actions.png"), full_page=True)
                start.focus()
                page.keyboard.press("Tab")
                checks["keyboard_focus_stays_in_dialog"] = dialog.evaluate("el => el.contains(document.activeElement)")
                page.set_viewport_size({"width": 1440, "height": 1000})
                # Make only this owned fixture's receipt snapshot temporarily
                # unavailable. The real API must reject navigation, then recover
                # without recreating a check or guessing an activity identifier.
                receipt_files = list((harness.state / "receipts").glob("*/*.jsonl"))
                fixture.require(len(receipt_files) == 1, "unexpected receipt fixture layout")
                receipt_file = receipt_files[0]
                parked = receipt_file.with_suffix(".temporarily-unavailable")
                receipt_file.rename(parked)
                try:
                    with page.expect_response(lambda r: r.url.endswith(f"/{started_check}/activity")) as rejected:
                        dialog.get_by_role("button", name="查看本次运行记录", exact=True).click()
                    fixture.require(rejected.value.status == 500, "missing snapshot returned a link")
                    expect(dialog.get_by_text("暂时无法读取本次运行记录，请检查服务连接后重试。", exact=True)).to_be_visible()
                    checks["activity_lookup_failure_stays_in_dialog"] = True
                finally:
                    parked.rename(receipt_file)
                with page.expect_response(lambda r: r.url.endswith(f"/{started_check}/activity") and r.status == 200) as linked:
                    dialog.get_by_role("button", name="查看本次运行记录", exact=True).click()
                reference = linked.value.json()
                expect(page.get_by_role("heading", name="运行详情", exact=True)).to_be_visible()
                detail_path = f"/v1/task-activities/{reference['activity']['activity_id']}?snapshot={reference['snapshot']}"
                detail = harness.api(detail_path)
                result = harness.api(f"/v1/runtime-checks/{started_check}")
                fixture.require({r["receipt_id"] for r in detail["receipts"]} == set(result["receipt_ids"]), "linked another check's receipts")
                checks["activity_shortcut_matches_all_actual_check_receipts"] = True
                expect(page.get_by_text("效果仍未知", exact=True)).to_be_visible(timeout=20000)
                checks["self_check_not_presented_as_verified_business_result"] = True
                page.reload()
                expect(page.get_by_role("heading", name="运行详情", exact=True)).to_be_visible()
                page.get_by_role("button", name="刷新详情", exact=True).click()
                page.get_by_role("link", name="返回运行记录", exact=True).click()
                expect(page.get_by_label("任务", exact=True)).to_have_value(reference["activity"]["binding"]["task_id"])
                expect(page.get_by_label("智能体", exact=True)).to_have_value(reference["activity"]["binding"]["agent_id"])
                expect(page.get_by_label("会话", exact=True)).to_have_value(reference["activity"]["binding"]["session_id"])
                expect(page.get_by_role("link", name="查看活动记录", exact=True)).to_have_count(1)
                page.reload()
                expect(page.get_by_role("link", name="查看活动记录", exact=True)).to_have_count(1)
                checks["activity_detail_refresh_back_and_filter_reload"] = True
                page.get_by_label("调用裁决", exact=True).select_option("deny")
                with page.expect_response(lambda r: "/v1/task-activities/query?" in r.url and r.status == 200) as filtered:
                    page.get_by_role("button", name="最近24小时", exact=True).click()
                filtered_data = filtered.value.json()
                fixture.require(filtered_data["total"] == 1, "time and decision filter lost native activity")
                fixture.require(filtered_data["items"][0]["decisions"]["allow"] == 2, "observations counted as allowed calls")
                fixture.require(filtered_data["items"][0]["decisions"]["deny"] == 1, "native denial missing from summary")
                scope = parse_qs(urlparse(page.url).query)
                page.get_by_role("link", name="查看活动记录", exact=True).click()
                expect(page.get_by_role("heading", name="运行详情", exact=True)).to_be_visible()
                page.reload()
                page.get_by_role("link", name="返回运行记录", exact=True).click()
                page.reload()
                for key in ("from", "to", "action", "task_id", "agent_id", "session_id"):
                    fixture.require(parse_qs(urlparse(page.url).query).get(key) == scope.get(key), "detail lost filter scope")
                expect(page.get_by_label("调用裁决", exact=True)).to_have_value("deny")
                expect(page.get_by_role("link", name="查看活动记录", exact=True)).to_have_count(1)
                checks["time_decision_filters_and_native_counts_survive_detail_return"] = True
                before_invalid = page.url
                page.get_by_label("记录时间从", exact=True).fill("2001-01-01T00:00")
                page.get_by_label("到（不含）", exact=True).fill("2000-01-01T00:00")
                page.get_by_role("button", name="应用筛选", exact=True).click()
                expect(page.get_by_text("开始时间必须早于结束时间。", exact=True)).to_be_visible()
                fixture.require(page.url == before_invalid, "invalid time range changed scope")
                checks["invalid_time_range_preserves_results"] = True
                page.get_by_label("记录时间从", exact=True).fill("2000-01-01T00:00")
                page.get_by_label("到（不含）", exact=True).fill("2001-01-01T00:00")
                page.get_by_role("button", name="应用筛选", exact=True).click()
                expect(page.get_by_text("没有匹配当前筛选条件的运行记录。", exact=True)).to_be_visible()
                page.get_by_role("button", name="清空筛选", exact=True).click()
                expect(page.get_by_role("link", name="查看活动记录", exact=True)).to_have_count(1)
                checks["empty_time_filter_and_clear_recover_real_records"] = True
                # Real denied API requests create unassigned signed receipts;
                # no tool is executed, and no caller-supplied binding is trusted.
                decision_token = (harness.state / "token").read_text().strip()
                for index in range(51):
                    denied = harness.api("/v1/decide", {
                        "platform": "hermes", "agent_id": "synthetic-pagination-agent",
                        "session_id": f"synthetic-pagination-{index}", "tool": "read_file",
                        "tool_call_id": f"synthetic-pagination-{index}",
                        "params": {"path": str(harness.workspace / "not-executed.txt")},
                    }, token=decision_token)
                    fixture.require(denied["action"] == "deny", "unbound pagination request allowed")
                page.get_by_role("button", name="未归属活动", exact=True).click()
                expect(page.get_by_role("link", name="查看活动记录", exact=True)).to_have_count(50)
                page.get_by_role("button", name="下一页", exact=True).click()
                expect(page.get_by_role("link", name="查看活动记录", exact=True)).to_have_count(1)
                page.get_by_role("link", name="查看活动记录", exact=True).click()
                expect(page.get_by_role("heading", name="运行详情", exact=True)).to_be_visible()
                page.get_by_role("button", name="刷新详情", exact=True).click()
                page.get_by_role("link", name="返回运行记录", exact=True).click()
                expect(page.get_by_role("link", name="查看活动记录", exact=True)).to_have_count(1)
                fixture.require(parse_qs(urlparse(page.url).query).get("offset") == ["50"], "detail refresh lost list offset")
                page.reload()
                expect(page.get_by_role("link", name="查看活动记录", exact=True)).to_have_count(1)
                page.get_by_role("button", name="上一页", exact=True).click()
                expect(page.get_by_role("link", name="查看活动记录", exact=True)).to_have_count(50)
                checks["real_unassigned_pagination_detail_refresh_back_reload"] = True
                page.get_by_role("button", name="已归属任务", exact=True).click()
                expect(page.get_by_role("link", name="查看活动记录", exact=True)).to_have_count(1)
                page.screenshot(path=str(args.out_dir / "runtime-check-filtered-activity.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                # Wait for the responsive drawer transition before measuring
                # whether the apply control is unobscured.
                page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 0")
                checks["mobile_activity_filters_fit"] = page.get_by_role("form", name="筛选任务活动").evaluate(
                    "el => el.scrollWidth <= el.clientWidth + 1 && el.getBoundingClientRect().right <= innerWidth"
                )
                page.get_by_role("button", name="应用筛选", exact=True).scroll_into_view_if_needed()
                checks["mobile_activity_apply_reachable"] = page.get_by_role("button", name="应用筛选", exact=True).evaluate(
                    "el => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight && "
                    "el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)); }"
                )
                page.screenshot(path=str(args.out_dir / "runtime-check-activity-mobile.png"), full_page=True)
                page.set_viewport_size({"width": 1440, "height": 1000})
                page.goto(harness.endpoint + "/overview")
                card.get_by_role("button", name="验证连接", exact=True).click()
                expect(dialog.get_by_text("本次自检通过", exact=True)).to_be_visible(timeout=20000)
                config = Path(harness.env["HERMES_HOME"]) / "config.yaml"
                before = config.read_bytes()
                config.write_bytes(before + b"\n# fixture configuration drift\n")
                dialog.get_by_role("button", name="重新预览", exact=True).click()
                expect(dialog.get_by_text("自检结果已失效", exact=True)).to_be_visible(timeout=20000)
                checks["configuration_drift_invalidates_display"] = True
                historical = harness.api(f"/v1/runtime-checks/{started_check}/activity")
                checks["invalidated_check_keeps_historical_activity_without_reviving_status"] = (
                    historical["activity"]["activity_id"] == reference["activity"]["activity_id"]
                    and harness.api(f"/v1/runtime-checks/{started_check}")["status"] == "invalidated"
                )

                # An externally edited configuration must be reconciled before
                # another launch. Restore this owned fixture, without silently
                # changing configuration in the product or reviving old evidence.
                expect(start).to_be_disabled()
                checks["unreconciled_configuration_blocks_launch"] = True
                config.write_bytes(before)
                dialog.get_by_role("button", name="重新预览", exact=True).click()
                expect(dialog.get_by_text("自检结果已失效", exact=True)).to_be_visible(timeout=20000)
                expect(start).to_be_enabled()
                start.click()
                dialog.get_by_role("button", name="取消自检", exact=True).click()
                expect(dialog.get_by_text("自检已取消", exact=True)).to_be_visible(timeout=20000)
                expect(dialog.get_by_text("临时权限与材料：已撤权并清理", exact=True)).to_be_visible()
                checks["cancel_revokes_and_cleans"] = all(
                    g["status"] == "revoked" for g in harness.api("/v1/grants")["grants"]
                )
                dialog.get_by_role("button", name="关闭", exact=True).click()
                card.get_by_role("button", name="管理此实例", exact=True).click()
                dialog.get_by_label("操作", exact=True).select_option("uninstall")
                expect(dialog.get_by_role("button", name="确认应用", exact=True)).to_be_enabled(timeout=20000)
                dialog.get_by_role("button", name="确认应用", exact=True).click()
                expect(dialog).not_to_be_visible(timeout=30000)
                expect(card.get_by_role("button", name="接入此实例", exact=True)).to_be_visible(timeout=20000)
                expect(page.get_by_role("button", name="验证刚接入的实例", exact=True)).to_have_count(0)
                expect(card.get_by_role("button", name="验证连接", exact=True)).to_have_count(0)
                checks["uninstall_does_not_offer_install_continuation"] = True
                checks["uninstall_removes_owned_plugin"] = not (config.parent / "plugins/siq-agent-security").exists()
                checks["no_page_errors"] = not errors
                checks["no_credentials_in_web_storage"] = page.evaluate(
                    "token => !JSON.stringify([Object.entries(localStorage), "
                    "Object.entries(sessionStorage)]).includes(token)",
                    credential,
                )
                browser.close()
        except Exception as exc:
            failure = {"category": type(exc).__name__, "frames": [
                {"file": Path(frame.filename).name, "line": frame.lineno}
                for frame in traceback.extract_tb(exc.__traceback__)
            ]}
        finally:
            harness.stop()
    result = {
        "schema_version": "product-runtime-check-browser-smoke/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "passed": failure is None and bool(checks) and all(checks.values()),
        "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "hermes_cli_sha256": hashlib.sha256(args.hermes_cli.read_bytes()).hexdigest(),
        "failure": failure,
        "checks": checks,
        "scope": "Linux Chromium, product UI/API, real public Hermes CLI, isolated profile and synthetic operator",
    }
    (args.out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
