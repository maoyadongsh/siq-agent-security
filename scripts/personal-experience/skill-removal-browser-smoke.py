#!/usr/bin/env python3
"""Verify explicit Skill removal, unknown-content retention and lost-response recovery in an isolated browser."""

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
                remove = page.get_by_role("button", name="移除此 Skill", exact=True)
                expect(remove).to_be_enabled()
                remove.click()
                dialog = page.get_by_role("dialog", name="移除 Skill", exact=True)
                confirm = dialog.get_by_role("button", name="确认移除 Skill", exact=True)
                expect(confirm).to_be_disabled()
                expect(dialog).to_contain_text("会撤销此安装对应的授权")
                expect(page.get_by_role("button", name="刷新安装记录", exact=True)).to_be_disabled()
                dialog.get_by_role("button", name="关闭", exact=True).click()
                expect(dialog).to_be_hidden()
                expect(remove).to_be_enabled()
                fixture.require(h.api(operation_route + "/removal")["status"] == "not_requested", "opening removed files")
                fixture.require(entry.read_bytes() == original, "cancel modified target")
                checks["open_review_cancel_never_removes_or_revokes"] = True

                user_file = destination / "user-notes.txt"
                user_file.write_text("preserve user notes")
                expect(detail).to_have_attribute("aria-busy", "false")
                expect(remove).to_be_enabled()
                remove.click()
                expect(dialog).to_be_visible()
                page.screenshot(path=str(args.out_dir / "removal-desktop.png"), animations="disabled")
                posts = []
                fail_reads = False

                def lose_remove_response(intercept):
                    nonlocal fail_reads
                    if intercept.request.method == "POST":
                        posts.append(intercept.request.post_data_json)
                        response = intercept.fetch()
                        fixture.require(response.status == 200 and response.json()["status"] == "cleanup_pending", "pending removal failed")
                        fail_reads = True
                        intercept.abort("connectionfailed")
                    elif fail_reads:
                        intercept.fulfill(status=503, content_type="application/json", body='{"error":"skill_install_unavailable"}')
                    else:
                        intercept.continue_()

                page.route("**" + operation_route + "/removal", lose_remove_response)
                dialog.get_by_label("我已核对目标和权限范围，确认移除", exact=True).check()
                confirm.evaluate("button => { button.click(); button.click(); }")
                expect(dialog).to_contain_text("当前无法确认移除状态")
                expect(dialog.get_by_role("button", name="确认移除 Skill", exact=True)).to_have_count(0)
                fixture.require(len(posts) == 1, "duplicate removal POST")
                fixture.require(h.api(route)["grant"]["status"] == "revoked", "removal did not revoke")
                fixture.require(user_file.read_text() == "preserve user notes" and entry.read_bytes() == original, "partial cleanup deleted user/original content")
                checks["lost_write_and_read_failure_clear_old_actions_without_repost"] = True
                fail_reads = False
                dialog.get_by_role("button", name="重新查询移除状态", exact=True).click()
                expect(dialog).to_contain_text("文件清理尚未完成")
                expect(dialog).to_contain_text("fixture-human")
                retry = dialog.get_by_role("button", name="按原确认继续移除", exact=True)
                expect(retry).to_be_disabled()
                fixture.require(len(posts) == 1, "read retried POST")
                checks["pending_recovery_requires_new_confirmation_and_preserves_user_files"] = True
                page.set_viewport_size({"width": 390, "height": 844})
                expect(page.locator(".sidebar")).to_be_hidden()
                retry.scroll_into_view_if_needed()
                expect(retry).to_be_in_viewport()
                fixture.require(dialog.evaluate("e => e.scrollWidth <= e.clientWidth"), "mobile modal overflow")
                dialog.get_by_role("button", name="关闭", exact=True).scroll_into_view_if_needed()
                page.screenshot(path=str(args.out_dir / "removal-mobile.png"), animations="disabled")
                dialog.get_by_role("button", name="关闭", exact=True).click()
                page.reload()
                expect(page.get_by_role("button", name="继续移除与恢复", exact=True)).to_be_enabled()
                page.get_by_role("button", name="继续移除与恢复", exact=True).click()
                expect(dialog).to_contain_text("文件清理尚未完成")
                fixture.require(len(posts) == 1, "reload repeated POST")
                checks["reload_restores_original_pending_operation_without_write"] = True
                page.unroute("**" + operation_route + "/removal", lose_remove_response)

                def record_retry(intercept):
                    if intercept.request.method == "POST":
                        posts.append(intercept.request.post_data_json)
                    intercept.continue_()

                page.route("**" + operation_route + "/removal", record_retry)
                # Simulate the owner preserving their notes outside the SIQ target.
                user_file.rename(root / "preserved-user-notes.txt")
                dialog.get_by_label("我已核对目标和权限范围，确认移除", exact=True).check()
                retry.click()
                expect(dialog).to_contain_text("已记录移除完成")
                fixture.require(len(posts) == 2 and posts[0] == posts[1], "retry changed original scope")
                fixture.require(not destination.exists(), "owned target retained")
                fixture.require((root / "preserved-user-notes.txt").read_text() == "preserve user notes", "user content lost")
                expect(dialog.get_by_role("button", name="按原确认继续移除", exact=True)).to_have_count(0)
                checks["explicit_retry_uses_original_request_and_completes"] = True
                dialog.get_by_role("button", name="关闭", exact=True).click()
                expect(detail).to_contain_text("已记录移除完成")
                expect(detail.get_by_role("link", name="查看授权记录", exact=True)).to_have_attribute("href", "/grants?grant=" + grant_id)
                destination.mkdir()
                (destination / "new-user-file.txt").write_text("new unrelated file")
                page.reload()
                expect(detail).to_contain_text("已记录移除完成")
                page.get_by_role("button", name="查看移除记录", exact=True).click()
                expect(dialog).to_contain_text("同路径后来出现的文件不会再次清理")
                fixture.require((destination / "new-user-file.txt").read_text() == "new unrelated file", "history touched reused path")
                fixture.require(len(posts) == 2, "completion triggered another POST")
                checks["completed_history_never_cleans_reused_path"] = True
                fixture.require(not errors, "browser page error")
                browser.close()
            fixture.require(config.read_bytes() == config_before, "removal modified host configuration")
            fixture.require(not h.api("/v1/runtime-identities")["items"], "browser issued unintended identity")
            result = {
                "generated_at": datetime.now(UTC).isoformat(), "status": "passed", "checks": checks,
                "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "scope": "Real browser and isolated daemon/profile, synthetic owner and Skill. Explicit removal, lost responses, pending recovery and reused target. No OS/Skill-attribution acceptance; actual process crashes are separate Go evidence.",
            }
            (args.out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"status": "passed", "checks": len(checks)}))
        finally:
            h.stop()


if __name__ == "__main__":
    main()
