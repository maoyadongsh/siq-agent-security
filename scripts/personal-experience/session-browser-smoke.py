#!/usr/bin/env python3
"""Exercise the real embedded UI and daemon in an isolated personal test profile.

Requires an already-built local binary and Playwright Chromium. Credentials stay
in a temporary private directory or memory and are never written into evidence.
This checks session UX; it is not evidence of real agent platform integration.
"""

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--discovery", action="store_true", help="also exercise deterministic local discovery fixtures")
    parser.add_argument(
        "--hermes-cli", type=Path, help="verify native enable using an installed CLI and isolated profiles"
    )
    args = parser.parse_args()
    binary = args.binary.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    outcomes = {}
    with tempfile.TemporaryDirectory(prefix="siq-session-smoke-") as raw:
        root = Path(raw)
        home = root / "home"
        home.mkdir(mode=0o700)
        if args.discovery:
            fixtures = {
                ".openclaw/openclaw.json": json.dumps(
                    {
                        "agents": {
                            "list": [
                                {"id": "studio", "name": "Studio", "workspace": "~/.openclaw/workspace-studio"},
                                {"id": "research", "name": "Research"},
                            ]
                        }
                    }
                ),
                ".openclaw/skills/shared-note/SKILL.md": "---\nname: shared-note\n---\nShared fixture\n",
                ".openclaw/workspace-studio/skills/private-note/SKILL.md": (
                    "---\nname: private-note\n---\nPrivate fixture\n"
                ),
                ".hermes/config.yaml": "model: test-fixture\n",
                ".hermes/skills/category/same-name/SKILL.md": "---\nname: same-name\n---\nVersion A\n",
                ".hermes/skills/other/same-name/SKILL.md": "---\nname: same-name\n---\nVersion A\n",
                ".hermes/profiles/work/config.yaml": "model: test-fixture\n",
                ".hermes/profiles/work/skills/category/work-only/SKILL.md": "---\nname: work-only\n---\nWork fixture\n",
            }
            for relative, content in fixtures.items():
                target = home / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
        env = {
            **os.environ,
            "HOME": str(home),
            "USERPROFILE": str(home),
            "SIQ_AGENT_SECURITY_STATE_DIR": str(root / "state"),
            "AGENTSHIELD_STATE_DIR": str(root / "state"),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "HERMES_HOME": str(home / ".hermes"),
            "LOCALAPPDATA": str(home / "AppData/Local"),
            "SIQ_AGENT_SECURITY_HERMES_CLI": str(args.hermes_cli.resolve())
            if args.hermes_cli
            else str(root / "missing-hermes-cli"),
        }
        port = free_port()
        endpoint = f"http://127.0.0.1:{port}"
        process = None

        def cli(command):
            return subprocess.run(
                [str(binary), command, "--port", str(port)],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        def stop():
            nonlocal process
            if process is not None:
                process.terminate()
                process.wait(timeout=15)
                process = None

        def start():
            nonlocal process
            # Startup emits a one-time code. Discard it; the explicit pair CLI
            # below obtains a fresh one without retaining a log containing secrets.
            process = subprocess.Popen(
                [str(binary), "serve", "--port", str(port)],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("isolated daemon stopped before readiness")
                if cli("status").returncode == 0:
                    return
                time.sleep(0.1)
            raise RuntimeError("isolated daemon readiness timed out")

        def pair_code():
            result = cli("pair")
            match = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", result.stdout)
            if result.returncode != 0 or not match:
                raise RuntimeError("pair CLI did not return a valid code")
            return match.group(0)

        try:
            start()
            outcomes["cli_health_identity"] = json.loads(cli("status").stdout)["status"] == "ready"
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                page_errors = []
                page.on("pageerror", lambda _: page_errors.append("pageerror"))
                page.goto(endpoint + "/overview")
                expect(page.get_by_role("heading", name="连接你的本地管理台")).to_be_visible()
                page.get_by_label("配对码", exact=True).fill("wrong")
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                expect(page.get_by_role("alert")).to_contain_text("配对码无效")
                page.get_by_label("配对码", exact=True).fill(pair_code())
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                outcomes["pair_without_restart"] = True
                cookie = context.cookies()[0]
                outcomes["cookie_scope"] = (
                    cookie["httpOnly"] and cookie["sameSite"] == "Strict" and cookie["path"] == "/v1/session"
                )
                outcomes["no_script_credential"] = page.evaluate(
                    "document.cookie === '' && !Object.values(localStorage).some(v => /^[a-f0-9]{64}$/.test(v))"
                )
                page.reload()
                expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                outcomes["refresh_restores_session"] = True
                tab = context.new_page()
                tab.goto(endpoint + "/overview")
                expect(tab.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                outcomes["second_tab_restores_session"] = True
                if args.discovery:

                    def run_scan(button="重新扫描"):
                        with page.expect_response(
                            lambda response: response.url.endswith("/v1/discovery/scan") and response.status == 202
                        ) as created:
                            page.get_by_role("button", name=button, exact=True).click()
                        run_id = created.value.json()["run"]["run_id"]
                        page.wait_for_function(
                            "id => { const n = document.querySelector('[data-scan-id]'); "
                            "return n?.dataset.scanId === id && "
                            "['succeeded', 'partial'].includes(n.dataset.scanState); }",
                            arg=run_id,
                            timeout=30000,
                        )

                    page.goto(endpoint + "/agents")
                    expect(page.get_by_role("row").filter(has_text="same-name")).to_have_count(2)
                    outcomes["same_name_installations_distinct"] = True
                    page.get_by_role("row").filter(has_text="shared-note").click()
                    expect(page.get_by_role("heading", name="配置关联的可能使用者")).to_be_visible()
                    expect(page.get_by_role("link", name="Studio", exact=True)).to_be_visible()
                    expect(page.get_by_role("link", name="Research", exact=True)).to_be_visible()
                    outcomes["shared_skill_multiple_consumers"] = True
                    page.screenshot(path=str(args.out_dir / "shared-skill.png"), full_page=True)
                    page.goto(endpoint + "/agents")
                    chosen = page.get_by_role("row").filter(has_text="same-name").filter(has_text="skills/category/")
                    chosen.click()
                    installation_url = page.url
                    hash_cell = page.locator("dt").filter(has_text="内容哈希").locator("xpath=following-sibling::dd[1]")
                    old_hash = hash_cell.inner_text()
                    (home / ".hermes/skills/category/same-name/SKILL.md").write_text(
                        "---\nname: same-name\n---\nVersion B\n"
                    )
                    page.goto(endpoint + "/agents")
                    run_scan()
                    page.get_by_role("row").filter(has_text="same-name").filter(has_text="skills/category/").click()
                    if page.url != installation_url:
                        raise RuntimeError("content update changed installation identity")
                    if (
                        page.locator("dt")
                        .filter(has_text="内容哈希")
                        .locator("xpath=following-sibling::dd[1]")
                        .inner_text()
                        == old_hash
                    ):
                        raise RuntimeError("explicit scan left the old content hash cached")
                    outcomes["explicit_rescan_updates_content_without_changing_identity"] = True
                    extra = root / "imported-example"
                    extra.mkdir()
                    (extra / "SKILL.md").write_text("---\nname: imported-example\n---\n")
                    page.goto(endpoint + "/agents")
                    page.get_by_label("添加目录类型", exact=True).select_option("skill_dir")
                    page.get_by_label("额外目录（可选）", exact=True).fill(str(extra))
                    expect(page.get_by_role("button", name="添加目录并扫描", exact=True)).to_be_disabled()
                    page.get_by_role("button", name="预览扫描范围", exact=True).click()
                    expect(page.get_by_role("button", name="添加目录并扫描", exact=True)).to_be_enabled()
                    run_scan("添加目录并扫描")
                    expect(page.get_by_role("row").filter(has_text="imported-example")).to_have_count(1)
                    outcomes["manual_scope_preview_and_scan"] = True
                    run_scan()
                    expect(page.get_by_role("row").filter(has_text="imported-example")).to_have_count(1)
                    outcomes["repeat_scan_no_duplicate_installation"] = True
                    page.set_viewport_size({"width": 390, "height": 844})
                    sidebar = page.get_by_role("complementary", name="siq-agent-security 本地导航")
                    expect(sidebar).to_be_hidden()
                    page.get_by_role("button", name="打开导航", exact=True).click()
                    expect(sidebar).to_be_visible()
                    page.get_by_role("button", name="关闭导航", exact=True).click(position={"x": 380, "y": 400})
                    expect(sidebar).to_be_hidden()
                    outcomes["mobile_navigation_opens_and_closes"] = True
                    page.get_by_text("扫描范围：", exact=False).click()
                    outcomes["discovery_mobile_no_overflow"] = page.evaluate(
                        "document.documentElement.scrollWidth <= innerWidth"
                    )
                    page.evaluate("document.querySelectorAll('*').forEach(n => { if (n.scrollTop) n.scrollTop = 0; });")
                    page.screenshot(
                        path=str(args.out_dir / "discovery-mobile.png"), full_page=True, animations="disabled"
                    )
                    page.get_by_text("扫描范围：", exact=False).click()
                    page.set_viewport_size({"width": 1440, "height": 1000})
                    page.evaluate("document.querySelectorAll('*').forEach(n => { if (n.scrollTop) n.scrollTop = 0; });")
                    page.screenshot(path=str(args.out_dir / "discovery.png"), full_page=True)
                page.screenshot(path=str(args.out_dir / "connected.png"), full_page=True)
                if args.discovery:
                    page.goto(endpoint + "/settings")
                    hermes_row = page.get_by_role("row").filter(has=page.get_by_text("Hermes", exact=True))
                    # Catalog failures are recoverable inside the same dialog.
                    page.route("**/v1/adapter/instances?platform=hermes", lambda route: route.abort(), times=1)
                    hermes_row.get_by_role("button", name="管理实例", exact=True).click()
                    dialog = page.get_by_role("dialog", name="Hermes · 接入预览")
                    expect(dialog.get_by_role("alert")).to_be_visible()
                    expect(dialog.get_by_role("button", name="确认应用")).to_be_disabled()
                    dialog.get_by_role("button", name="重新预览").click()
                    expect(dialog.get_by_label("Hermes 实例 / profile")).to_be_visible()
                    outcomes["instance_catalog_retry_recovers_without_reopening"] = True
                    if args.hermes_cli:
                        dialog.get_by_role("checkbox").uncheck()
                    expect(dialog.get_by_role("button", name="确认应用")).to_be_enabled()
                    assert not (home / ".hermes/plugins/siq-agent-security/plugin.yaml").exists()
                    expect(dialog.get_by_text("安装当前版本的工具调用适配器文件", exact=True).first).to_be_visible()
                    page.screenshot(
                        path=str(args.out_dir / "adapter-preview.png"), full_page=True, animations="disabled"
                    )
                    dialog.get_by_role("button", name="确认应用").focus()
                    page.keyboard.press("Tab")
                    expect(dialog.get_by_label("Hermes 实例 / profile")).to_be_focused()
                    summary = dialog.locator("summary").first
                    summary.focus()
                    expect(summary).to_be_focused()
                    page.keyboard.press("Enter")
                    expect(dialog.locator("details").first).to_have_attribute("open", "")
                    page.keyboard.press("Enter")
                    outcomes["adapter_preview_keyboard_details"] = True
                    page.set_viewport_size({"width": 390, "height": 844})
                    outcomes["adapter_preview_mobile_no_overflow"] = dialog.evaluate(
                        "n => n.scrollWidth <= n.clientWidth && document.documentElement.scrollWidth <= innerWidth"
                    )
                    dialog.get_by_role("button", name="确认应用").scroll_into_view_if_needed()
                    page.screenshot(
                        path=str(args.out_dir / "adapter-preview-mobile.png"), full_page=True, animations="disabled"
                    )
                    page.set_viewport_size({"width": 1440, "height": 1000})
                    dialog.get_by_role("button", name="取消", exact=True).click()
                    assert not (home / ".hermes/plugins/siq-agent-security/plugin.yaml").exists()
                    outcomes["adapter_preview_and_cancel_do_not_write"] = True
                    hermes_row.get_by_role("button", name="管理实例", exact=True).click()
                    if args.hermes_cli:
                        page.get_by_role("dialog").get_by_role("checkbox").uncheck()
                    page.get_by_role("dialog").get_by_role("button", name="确认应用").click()
                    expect(hermes_row.get_by_text("发现安装文件", exact=True)).to_be_visible()
                    hermes_row.get_by_text("查看接入诊断", exact=True).click()
                    expect(
                        hermes_row.get_by_text("Hermes", exact=False).filter(has_text="需要原生").first
                    ).to_be_visible()
                    expect(hermes_row.get_by_text("接入待验证", exact=True)).to_be_visible()
                    outcomes["installed_files_do_not_claim_runtime_protection"] = True
                    unknown_file = home / ".hermes/plugins/siq-agent-security/user-note.txt"
                    unknown_file.write_text("preserve user fixture")
                    hermes_row.get_by_role("button", name="管理实例", exact=True).click()
                    dialog = page.get_by_role("dialog")
                    dialog.get_by_label("操作", exact=True).select_option("uninstall")
                    expect(dialog.get_by_role("button", name="确认应用")).to_be_enabled()
                    assert (home / ".hermes/plugins/siq-agent-security/plugin.yaml").exists()
                    dialog.get_by_role("button", name="确认应用").click()
                    expect(hermes_row.get_by_text("未安装", exact=True)).to_be_visible()
                    assert not (home / ".hermes/plugins/siq-agent-security/plugin.yaml").exists()
                    assert unknown_file.read_text() == "preserve user fixture"
                    outcomes["adapter_uninstall_requires_confirmation_and_preserves_unknown_file"] = True

                    if args.hermes_cli:
                        default_config = (home / ".hermes/config.yaml").read_bytes()
                        work_config = home / ".hermes/profiles/work/config.yaml"
                        original_work = work_config.read_bytes()
                        hermes_row.get_by_role("button", name="管理实例", exact=True).click()
                        dialog = page.get_by_role("dialog")
                        selector = dialog.get_by_label("Hermes 实例 / profile")
                        work_id = selector.locator("option").filter(has_text="work ·").get_attribute("value")
                        selector.select_option(work_id)
                        expect(dialog.get_by_role("checkbox")).to_be_checked()
                        expect(dialog.get_by_role("button", name="确认应用")).to_be_enabled(timeout=45000)
                        assert work_config.read_bytes() == original_work
                        page.screenshot(path=str(args.out_dir / "hermes-native-preview.png"), full_page=True)
                        dialog.get_by_role("button", name="确认应用").click()
                        expect(dialog).not_to_be_visible()
                        assert "siq-agent-security" in work_config.read_text()
                        assert (home / ".hermes/config.yaml").read_bytes() == default_config
                        assert (home / ".hermes/profiles/work/plugins/siq-agent-security/__init__.py").is_file()
                        assert not (home / ".hermes/plugins/siq-agent-security/__init__.py").exists()
                        outcomes["native_enable_applies_only_confirmed_profile"] = True
                        hermes_row.get_by_role("button", name="管理实例", exact=True).click()
                        dialog = page.get_by_role("dialog")
                        dialog.get_by_label("Hermes 实例 / profile").select_option(work_id)
                        expect(dialog.get_by_text("配置就绪，待验证", exact=True)).to_be_visible()
                        dialog.get_by_text("查看接入诊断", exact=True).click()
                        expect(dialog.get_by_text("原生命令已确认本实例启用配置", exact=False)).to_be_visible()
                        page.screenshot(path=str(args.out_dir / "hermes-instance-diagnosis.png"), full_page=True)
                        work_config.write_text(work_config.read_text() + "\nuser_added_after_install: keep-me\n")
                        dialog.get_by_label("操作", exact=True).select_option("uninstall")
                        expect(dialog.get_by_role("button", name="确认应用")).to_be_enabled(timeout=45000)
                        dialog.get_by_role("button", name="确认应用").click()
                        expect(dialog).not_to_be_visible()
                        assert "user_added_after_install: keep-me" in work_config.read_text()
                        assert "siq-agent-security" not in work_config.read_text()
                        assert not (home / ".hermes/profiles/work/plugins/siq-agent-security/__init__.py").exists()
                        assert (home / ".hermes/config.yaml").read_bytes() == default_config
                        outcomes["native_uninstall_preserves_other_profile_and_later_user_settings"] = True

                    workbuddy_row = page.get_by_role("row").filter(has=page.get_by_text("WorkBuddy", exact=True))
                    expect(workbuddy_row.get_by_role("button")).to_have_count(0)
                    expect(workbuddy_row.get_by_text("桌面接入待实测", exact=True)).to_be_visible()
                    outcomes["workbuddy_keeps_separate_verification_status"] = True
                    openclaw_row = page.get_by_role("row").filter(has=page.get_by_text("OpenClaw", exact=True))
                    openclaw_row.get_by_role("button", name="安装", exact=True).click()
                    dialog = page.get_by_role("dialog")
                    expect(dialog.get_by_role("button", name="确认应用")).to_be_enabled()
                    config_path = home / ".openclaw/openclaw.json"
                    external = json.loads(config_path.read_text())
                    external["preview_fixture"] = "user edit after preview"
                    config_path.write_text(json.dumps(external))
                    dialog.get_by_role("button", name="确认应用").click()
                    expect(dialog.get_by_role("alert")).to_contain_text("平台配置已变化")
                    assert json.loads(config_path.read_text())["preview_fixture"] == "user edit after preview"
                    assert not (home / ".openclaw/plugins/siq-agent-security/index.ts").exists()
                    outcomes["adapter_stale_preview_preserves_external_edit"] = True
                    dialog.get_by_role("button", name="重新预览").click()
                    dialog.get_by_role("button", name="确认应用").click()
                    expect(openclaw_row.get_by_text("配置就绪，待验证", exact=True)).to_be_visible()
                    config_path = home / ".openclaw/openclaw.json"
                    config = json.loads(config_path.read_text())
                    config["plugins"]["enabled"] = False
                    config_path.write_text(json.dumps(config))
                    page.reload()
                    expect(openclaw_row.get_by_text("配置待修复", exact=True)).to_be_visible()
                    openclaw_row.get_by_text("查看接入诊断", exact=True).click()
                    expect(
                        openclaw_row.get_by_text("宿主配置不可确认，或插件未登记、被禁用、未列入允许范围", exact=False)
                    ).to_be_visible()
                    outcomes["disabled_plugin_reports_configuration_failure"] = True
                    openclaw_row.scroll_into_view_if_needed()
                    page.screenshot(
                        path=str(args.out_dir / "adapter-diagnostics.png"), full_page=True, animations="disabled"
                    )
                page.get_by_role("button", name="退出管理", exact=True).click()
                expect(page.get_by_role("heading", name="连接你的本地管理台")).to_be_visible()
                page.reload()
                expect(page.get_by_role("heading", name="连接你的本地管理台")).to_be_visible()
                tab.reload()
                expect(tab.get_by_role("heading", name="连接你的本地管理台")).to_be_visible()
                outcomes["logout_revokes_across_tabs"] = True
                page.get_by_label("配对码", exact=True).fill(pair_code())
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                stop()
                start()
                page.reload()
                expect(page.get_by_role("heading", name="连接你的本地管理台")).to_be_visible()
                outcomes["restart_requires_pairing"] = True
                if args.discovery:
                    page.get_by_label("配对码", exact=True).fill(pair_code())
                    page.get_by_role("button", name="建立管理会话", exact=True).click()
                    expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                    page.goto(endpoint + "/agents")
                    expect(page.get_by_role("row").filter(has_text="imported-example")).to_have_count(1)
                    outcomes["manual_scope_survives_daemon_restart"] = True
                    page.get_by_role("button", name="退出管理", exact=True).click()
                    expect(page.get_by_role("heading", name="连接你的本地管理台")).to_be_visible()
                # Show the actual frontend retry flow while the document remains
                # available, simulating an unavailable API via browser routing.
                page.route("**/ui-config.json", lambda route: route.abort())
                page.reload()
                expect(page.get_by_role("heading", name="暂时无法打开本地管理")).to_be_visible()
                page.screenshot(path=str(args.out_dir / "connection-retry.png"), full_page=True)
                page.unroute("**/ui-config.json")
                page.get_by_role("button", name="重新连接", exact=True).click()
                expect(page.get_by_role("heading", name="连接你的本地管理台")).to_be_visible()
                outcomes["connection_retry_recovers"] = True
                page.set_viewport_size({"width": 390, "height": 844})
                outcomes["pairing_mobile_no_overflow"] = page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                )
                page.screenshot(path=str(args.out_dir / "pairing-mobile.png"), full_page=True)
                outcomes["no_page_errors"] = not page_errors
                browser.close()
        finally:
            stop()
    result = {
        "schema_version": "personal-session-smoke/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "scope": "isolated daemon and real Chromium; no real agent integration claimed",
        "discovery_fixtures": args.discovery,
        "checks": outcomes,
    }
    (args.out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if not outcomes or not all(outcomes.values()):
        raise RuntimeError("one or more session browser checks failed; see redacted result.json")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
