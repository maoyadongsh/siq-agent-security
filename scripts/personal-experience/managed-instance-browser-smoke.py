#!/usr/bin/env python3
"""Exercise the managed instance approval and installation UI with an isolated daemon."""

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

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
    args.installer_managed_profile = True
    args.out_dir.mkdir(parents=True, exist_ok=True)
    checks = {}
    with tempfile.TemporaryDirectory(prefix="siq-managed-browser-") as temp:
        h = fixture.Harness(Path(temp), args)
        shutil.copy2(args.binary, h.binary)
        try:
            h.start()
            skill = h.root / "fixture-skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: managed-browser-fixture\ndescription: Synthetic report reader.\n"
                "allowed-tools: read_file write_file\n---\nRead a synthetic report.\n"
            )
            h.api("/v1/admit", {"path": str(skill)})
            pairing = h.command([str(h.binary), "pair", "--port", h.endpoint.rsplit(":", 1)[1]])
            code = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing).group()
            profile = Path(h.env["HERMES_HOME"])
            before = (profile / "config.yaml").read_bytes()
            config_path = profile / "plugins/siq-agent-security/config.json"
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda _: errors.append("pageerror"))
                page.goto(h.endpoint + "/settings")
                page.get_by_label("配对码", exact=True).fill(code)
                page.get_by_role("button", name="建立管理会话", exact=True).click()

                def open_instance():
                    page.get_by_role("button", name="管理实例", exact=True).click()
                    dialog = page.get_by_role("dialog")
                    expect(dialog.get_by_label("Hermes 实例 / profile", exact=True)).to_be_enabled()
                    expect(dialog.get_by_label("接入方式", exact=True)).to_have_value("permissions")
                    return dialog

                dialog = open_instance()
                expect(dialog.get_by_role("button", name="起草并编辑实例权限", exact=True)).to_be_enabled()
                expect(dialog.get_by_role("button", name="确认应用", exact=True)).to_be_disabled()
                dialog.get_by_role("button", name="取消", exact=True).click()
                fixture.require(
                    not h.api("/v1/grants")["grants"] and not config_path.exists(), "cancel created authority or files"
                )
                checks["open_and_cancel_do_not_create_authority_or_host_files"] = True
                dialog = open_instance()
                dialog.get_by_label("本次操作者", exact=True).fill("synthetic-browser-operator")
                dialog.get_by_role("button", name="起草并编辑实例权限", exact=True).click()
                editor = page.get_by_role("dialog", name="编辑权限范围", exact=True)
                expect(page.get_by_role("dialog")).to_have_count(1)
                expect(editor.get_by_label("只读目录", exact=True)).to_be_enabled()
                editor.get_by_label("允许的工具", exact=True).fill("read_file\nwrite_file")
                editor.get_by_label("只读目录", exact=True).fill(str(h.workspace))
                editor.get_by_label("读写目录", exact=True).fill("")
                editor.get_by_role("button", name="保存待批准权限", exact=True).click()
                expect(editor).to_have_count(0)
                dialog = page.get_by_role("dialog")
                expect(dialog.get_by_role("button", name="确认权限并应用授权", exact=True)).to_be_disabled()
                fixture.require(
                    h.api("/v1/grants")["grants"][0]["status"] == "pending_approval", "editing approved grant"
                )
                checks["editor_replaces_focus_trap_and_only_saves_pending_permissions"] = True
                current = h.api("/v1/grants")["grants"][0]
                versioned = h.api("/v1/grants/" + current["grant_id"])
                h.api(
                    "/v1/grants/" + current["grant_id"] + "/expiry",
                    {
                        "schema_version": "grant-expiry-edit/v1",
                        "duration_seconds": 7200,
                        "expected_revision": versioned["state_revision"],
                        "actor_id": "second-synthetic-operator",
                    },
                )
                dialog.get_by_label("我已核对以上权限范围", exact=True).check()
                dialog.get_by_role("button", name="确认权限并应用授权", exact=True).click()
                expect(dialog.get_by_role("alert")).to_contain_text("请刷新状态并重新核对")
                fixture.require(
                    h.api("/v1/grants")["grants"][0]["status"] == "pending_approval", "stale preview was approved"
                )
                dialog.get_by_role("button", name="刷新权限状态", exact=True).click()
                expect(dialog.get_by_role("button", name="确认权限并应用授权", exact=True)).to_be_disabled()
                expect(dialog.get_by_label("我已核对以上权限范围", exact=True)).not_to_be_checked()
                checks["concurrent_grant_change_requires_refresh_and_new_confirmation"] = True
                dialog.get_by_label("我已核对以上权限范围", exact=True).check()
                dialog.get_by_role("button", name="确认权限并应用授权", exact=True).click()
                expect(dialog.get_by_role("button", name="使用此授权并准备接入", exact=True)).to_be_disabled()
                fixture.require(h.api("/v1/grants")["grants"][0]["status"] == "deployed", "approval did not deploy")
                fixture.require(
                    not h.api("/v1/runtime-identities")["items"] and not config_path.exists(),
                    "approval installed without confirmation",
                )
                checks["explicit_approval_deploys_without_installing"] = True
                dialog.get_by_label("我已核对以上权限范围", exact=True).check()
                dialog.get_by_label("单次会话最长运行时间", exact=True).select_option("3600")
                dialog.get_by_role("button", name="使用此授权并准备接入", exact=True).click()
                expect(dialog.get_by_role("button", name="确认应用", exact=True)).to_be_enabled(timeout=30000)
                identity = h.api("/v1/runtime-identities")["items"][0]
                fixture.require(
                    identity["session_ttl_seconds"] == 3600 and identity["runtime_state"] == "unverified",
                    "wrong issuance state",
                )
                fixture.require(
                    not config_path.exists() and (profile / "config.yaml").read_bytes() == before, "preview wrote host"
                )
                expect(dialog.get_by_text("允许 · 只读目录 · " + str(h.workspace), exact=True)).to_be_visible()
                checks["session_duration_and_preview_are_explicit"] = True
                page.screenshot(path=str(args.out_dir / "managed-preview.png"))
                dialog.get_by_role("button", name="取消", exact=True).click()
                dialog = open_instance()
                expect(dialog.get_by_role("button", name="确认应用", exact=True)).to_be_enabled(timeout=30000)
                fixture.require(len(h.api("/v1/runtime-identities")["items"]) == 1, "reopening duplicated identity")
                checks["reopening_reuses_issued_identity"] = True
                page.set_viewport_size({"width": 390, "height": 844})
                apply_button = dialog.get_by_role("button", name="确认应用", exact=True)
                expect(apply_button).to_be_in_viewport()
                fixture.require(
                    page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "mobile horizontal overflow"
                )
                page.screenshot(path=str(args.out_dir / "managed-mobile.png"))
                checks["mobile_confirmation_visible_without_horizontal_overflow"] = True
                held = []
                page.route("**/v1/adapter/install", lambda route: held.append(route))
                apply_button.click()
                expect(dialog.get_by_label("Hermes 实例 / profile", exact=True)).to_be_disabled()
                expect(dialog.get_by_label("接入方式", exact=True)).to_be_disabled()
                expect(dialog.get_by_label("确认停用，后续工具调用将被阻止", exact=True)).to_be_disabled()
                expect(dialog.get_by_role("button", name="刷新权限状态", exact=True)).to_be_disabled()
                page.keyboard.press("Escape")
                expect(dialog).to_have_count(1)
                fixture.require(len(held) == 1, "install request was not held")
                held[0].continue_()
                expect(dialog).to_have_count(0, timeout=30000)
                page.unroute("**/v1/adapter/install")
                checks["installation_blocks_competing_permission_actions_and_close"] = True
                installed = json.loads(config_path.read_text())
                fixture.require(
                    installed["runtime_identity_id"] == identity["identity_id"]
                    and installed["agent_id"] == identity["agent_id"],
                    "UI installed wrong identity",
                )
                fixture.require(
                    (h.root / "hermes/config.yaml").read_text() == "fixture_default: unchanged\n",
                    "other profile changed",
                )
                checks["confirmed_install_writes_only_selected_profile"] = True
                page.set_viewport_size({"width": 1440, "height": 1000})
                dialog = open_instance()
                expect(dialog.get_by_role("button", name="停用此实例权限", exact=True)).to_be_disabled()
                dialog.get_by_label("确认停用，后续工具调用将被阻止", exact=True).check()
                dialog.get_by_role("button", name="停用此实例权限", exact=True).click()
                expect(dialog.get_by_role("button", name="使用此授权并准备接入", exact=True)).to_be_visible()
                expect(dialog.get_by_role("button", name="确认应用", exact=True)).to_be_disabled()
                fixture.require(
                    h.api("/v1/runtime-identities")["items"][0]["status"] == "revoked", "UI revocation missing"
                )
                checks["explicit_withdrawal_revokes_identity_and_invalidates_install_preview"] = True
                dialog.get_by_label("操作", exact=True).select_option("uninstall")
                expect(dialog.get_by_role("button", name="确认应用", exact=True)).to_be_enabled(timeout=30000)
                dialog.get_by_role("button", name="确认应用", exact=True).click()
                expect(dialog).to_have_count(0)
                fixture.require(not config_path.exists(), "uninstall retained managed adapter config")

                def native_get(key):
                    return json.loads(h.command([str(args.hermes_cli), "config", "get", key, "--json"]))

                plugins = native_get("plugins")
                fixture.require(
                    native_get("fixture_setting") == "retain" and native_get("terminal.env") == "local",
                    "uninstall changed unrelated settings",
                )
                fixture.require(
                    "siq-agent-security" not in plugins.get("enabled", [])
                    and "siq-agent-security" not in plugins.get("disabled", [])
                    and "allow_tool_override" not in plugins.get("entries", {}).get("siq-agent-security", {}),
                    "uninstall failed to restore native registration",
                )
                checks["uninstall_restores_registration_and_preserves_unrelated_settings"] = True
                fixture.require(not errors, "browser runtime errors")
                checks["no_browser_runtime_errors"] = True
                browser.close()
        finally:
            h.stop()
    report = {
        "schema_version": "personal-managed-instance-browser/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "passed": True,
        "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "checks": checks,
        "scope": (
            "Linux Chromium and isolated Hermes profile using actual public native enable CLI; "
            "synthetic operator and Skill"
        ),
    }
    (args.out_dir / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
