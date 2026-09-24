#!/usr/bin/env python3
"""Exercise automatic discovery and exact-instance onboarding in an isolated HOME.

The real candidate daemon owns discovery, preview, install and uninstall.
Only synthetic configuration in an isolated HOME is changed; no model is called.
"""

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace

import yaml
from playwright.sync_api import expect, sync_playwright

from background_setup_harness import BackgroundSetupMixin, fixture_directory

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("fixture", ROOT / "scripts/validate-intent-v2-hermes.py")
fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture)


class BackgroundOnboardingHarness(BackgroundSetupMixin, fixture.Harness):
    pass


def native_config_preserved(before, after):
    # Hermes rewrites YAML formatting and its version marker. Empty plugin
    # containers are equivalent to absent containers; populated registrations
    # and every other user field must still match, including our own plugin.
    def normalized(raw):
        document = yaml.safe_load(raw)
        if not isinstance(document, dict):
            raise ValueError("fixture configuration must be a mapping")
        document.pop("_config_version", None)
        plugins = document.get("plugins")
        if isinstance(plugins, dict):
            for key in ("enabled", "disabled"):
                if plugins.get(key) == []:
                    del plugins[key]
            if plugins.get("entries") == {}:
                del plugins["entries"]
            if not plugins:
                document.pop("plugins")
        return document
    return normalized(before) == normalized(after)


def adapter_probe(harness, call_id, path=None, write=False):
    # Load the installed adapter and call its actual hooks, without a Hermes/model process.
    # The only tool body is a read of a synthetic file inside this temporary workspace.
    worker = '''import importlib.util, json, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("installed_adapter", sys.argv[1])
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
tool = "write_file" if sys.argv[4] == "write" else "read_file"
args = {"path": sys.argv[2]}
if tool == "write_file": args["content"] = "synthetic-write-must-be-denied"
context = {"session_id": "onboarding-fixture-session", "tool_call_id": sys.argv[3]}
decision = adapter._pre_tool_call(tool, args, **context)
allowed = decision is None
if allowed:
    result = Path(sys.argv[2]).write_text(args["content"]) if tool == "write_file" else Path(sys.argv[2]).read_text()
    adapter._post_tool_call(tool, args, result=result, **context)
print(json.dumps({"allowed": allowed, "blocked": isinstance(decision, dict) and decision.get("action") == "block"}))
'''
    plugin = Path(harness.env["HERMES_HOME"]) / "plugins/siq-agent-security/__init__.py"
    return json.loads(harness.command([sys.executable, "-c", worker, str(plugin),
        str(path or harness.workspace / "company-a/report.txt"), call_id, "write" if write else "read"]))


def openclaw_probe(harness, args, call_id, path=None, write=False):
    spec = harness.root / "openclaw-browser-probe.json"
    result = harness.root / "openclaw-browser-result.json"
    config_root = Path(harness.env["HOME"]) / ".openclaw"
    config = json.loads((config_root / "siq-agent-security.json").read_text())
    params = {"path": str(path or harness.workspace / "company-a/report.txt")}
    if write:
        params["content"] = "synthetic-write-must-be-denied"
    spec.write_text(json.dumps({"openclaw_root": str(args.openclaw_root.resolve()),
        "workspace": str(harness.workspace), "session_id": "onboarding-fixture-session",
        "session_epoch": "11111111-1111-4111-8111-111111111111",
        "agent_id": config["agentId"], "result_path": str(result),
        "calls": [{"id": call_id, "tool": "write" if write else "read", "params": params}]}))
    env = {**harness.env, "OPENCLAW_STATE_DIR": str(config_root),
        "OPENCLAW_CONFIG_PATH": str(config_root / "openclaw.json"), "OPENCLAW_DISABLE_BUNDLED_PLUGINS": "1"}
    process = subprocess.run([str(args.node), str(ROOT / "scripts/openclaw-native-worker.mjs"), str(spec)],
        env=env, cwd=harness.workspace, capture_output=True, text=True, timeout=120, check=False)
    if process.returncode != 0:
        known = ["SIQ native plugin was not loaded", "unsupported native runtime export", "Cannot find module",
                 "Cannot find package", "ERR_MODULE_NOT_FOUND", "ERR_PACKAGE_PATH_NOT_EXPORTED", "Invalid config"]
        harness.openclaw_native_metadata = {"worker_failed": True, "exit_code": process.returncode,
            "error_categories": [item for item in known if item in process.stderr + process.stdout]}
        raise RuntimeError("OpenClaw native probe failed")
    payload = json.loads(result.read_text())
    harness.openclaw_native_metadata = {key: value for key, value in payload.items() if key != "outputs"}
    output = json.loads(payload["outputs"][0]["result"])
    blocked = output.get("details", {}).get("status") == "blocked"
    return {"allowed": not blocked and not output.get("isError", False), "blocked": blocked}


def verify_inventory(page, harness, checks, out_dir):
    """Click through real inventory, admission, grant, identity and revoke APIs."""
    page.goto(harness.endpoint + "/agents")
    expect(page.get_by_role("heading", name="智能体与 Skill", exact=True)).to_be_visible()
    assets = harness.api("/v1/assets")["assets"]
    kinds = (("frameworks", "智能体框架", {"platform_config"}),
             ("roles", "智能体角色", {"hermes_profile", "openclaw_agent"}),
             ("skills", "Skill", {"skill_dir"}))
    for kind, label, sources in kinds:
        count = (len({row["framework"] for row in assets if row["source_type"] in {"platform_config", "hermes_profile", "openclaw_agent"}
                      and row["framework"] not in {"", "unknown"}}) if kind == "frameworks"
                 else sum(row["source_type"] in sources for row in assets))
        assert count > 0, "fixture category was not discovered"
        page.get_by_role("button", name=f"{label}（{count}）", exact=True).click()
        expect(page).to_have_url(re.compile(rf"kind={kind}$"))
        expect(page.get_by_role("heading", name=f"{label}（{count}）", exact=True)).to_be_visible()
        expect(page.locator("tbody tr")).to_have_count(count)
        if kind == "frameworks":
            page.locator("tbody tr").filter(has_text="Hermes").get_by_role("button", name="查看角色", exact=True).click()
            expect(page.get_by_label("所属框架", exact=True)).to_have_value("hermes")
            role_count = sum(row["source_type"] == "hermes_profile" for row in assets)
            expect(page.locator("tbody tr")).to_have_count(role_count)
            page.reload()
            expect(page.get_by_label("所属框架", exact=True)).to_have_value("hermes")
            expect(page.locator("tbody tr")).to_have_count(role_count)
            page.get_by_label("所属框架", exact=True).select_option("")
    checks["categories_match_real_backend_inventory"] = True
    skill = page.locator("tbody tr").filter(has_text="onboarding-fixture")
    with page.expect_response(lambda res: res.url.endswith("/v1/admit")) as response:
        skill.get_by_role("button", name="安全检查", exact=True).click()
    assert response.value.ok, "Skill admission failed"
    admission = response.value.json()["admission"]
    expect(page.get_by_role("status").filter(has_text="检查结果已保存")).to_be_visible()
    page.reload()
    expect(page.get_by_role("heading", name=re.compile(r"^Skill（"))).to_be_visible()
    persisted = harness.api("/v1/admissions")["admissions"]
    checks["skill_check_persisted_after_reload"] = any(item["admission_id"] == admission["admission_id"] for item in persisted)
    page.screenshot(path=str(out_dir / "skills.png"), full_page=True, animations="disabled")
    skill.get_by_role("link", name="查看详情", exact=True).click()
    expect(page.get_by_role("heading", name="onboarding-fixture", exact=True)).to_be_visible()
    # A name is not a trusted permission subject; no invented shortcut.
    expect(page.get_by_role("link", name="查看关联授权的权限", exact=True)).to_have_count(0)
    checks["skill_detail_without_guessed_permission_subject"] = True
    return admission


def verify_inline_first_check(page, harness, checks):
    assert not harness.api("/v1/admissions")["admissions"], "fixture should start without prior checks"
    card = page.locator(".environment-connection").filter(has_text="Hermes").filter(has_text="work").first
    card.get_by_role("button", name=re.compile("接入此实例|管理此实例")).click()
    expect(page.get_by_label("已发现的 Skill", exact=True)).to_be_visible()
    assets = harness.api("/v1/assets")["assets"]
    blocked_skill = next(item for item in assets if "onboarding-blocked" in item["source_locator"])
    safe_skill = next(item for item in assets if "onboarding-fixture" in item["source_locator"])
    page.get_by_label("已发现的 Skill", exact=True).select_option(blocked_skill["id"])
    with page.expect_response(lambda res: res.url.endswith("/v1/admit")) as blocked:
        page.get_by_role("button", name="检查并继续", exact=True).click()
    assert blocked.value.ok and blocked.value.json()["admission"]["verdict"] == "quarantine"
    expect(page.get_by_role("alert").filter(has_text="不能作为权限参考")).to_be_visible()
    expect(page.get_by_label("参考检查结果", exact=True)).not_to_be_visible()
    assert not harness.api("/v1/grants")["grants"]
    checks["inline_quarantined_skill_cannot_prepare_permissions"] = True
    page.get_by_label("已发现的 Skill", exact=True).select_option(safe_skill["id"])
    skill_path = safe_skill["admit_path"]
    skill_root = Path(harness.env["HOME"]) / skill_path[2:] if skill_path.startswith("~/") else Path(skill_path)
    assert skill_root.is_relative_to(harness.root)
    moved = harness.root / "temporarily-unavailable-skill"
    skill_root.rename(moved)
    try:
        with page.expect_response(lambda res: res.url.endswith("/v1/admit")) as missing:
            page.get_by_role("button", name="检查并继续", exact=True).click()
        assert not missing.value.ok
        expect(page.get_by_role("alert")).to_be_visible()
        expect(page.get_by_label("已发现的 Skill", exact=True)).to_have_value(safe_skill["id"])
    finally:
        moved.rename(skill_root)
    with page.expect_response(lambda res: res.url.endswith("/v1/admit")) as checked:
        page.get_by_role("button", name="检查并继续", exact=True).click()
    assert checked.value.ok
    admission = checked.value.json()["admission"]
    expect(page.get_by_label("参考检查结果", exact=True)).to_have_value(admission["admission_id"])
    assert not harness.api("/v1/grants")["grants"]
    assert not harness.api("/v1/runtime-identities")["items"]
    checks["first_check_inside_connection_without_automatic_grant"] = True
    checks["inline_missing_skill_preserves_selection_and_retry_recovers"] = True
    page.get_by_role("button", name="取消", exact=True).last.click()
    expect(page.get_by_label("参考检查结果", exact=True)).not_to_be_visible()


def verify_permissions(page, harness, checks, out_dir, admission, platform, probe):
    tool = "read_file" if platform == "hermes" else "read"
    page.goto(harness.endpoint + "/overview")
    card = page.locator(".environment-connection").filter(has_text="Hermes" if platform == "hermes" else "OpenClaw")
    card = (card.filter(has_text="work") if platform == "hermes" else card).first
    card.get_by_role("button", name=re.compile("接入此实例|管理此实例")).click()
    page.get_by_label("本次操作者", exact=True).fill("onboarding-fixture-operator")
    page.get_by_label("参考检查结果", exact=True).select_option(admission["admission_id"])
    page.get_by_role("checkbox", name=re.compile("我确认以此检查结果为参考")).check()
    with page.expect_response(lambda res: res.url.endswith("/v1/grants/instance-drafts")) as drafted:
        page.get_by_role("button", name="起草并编辑实例权限", exact=True).click()
    assert drafted.value.ok
    grant_id = drafted.value.json()["grant"]["grant_id"]
    expect(page.get_by_label("允许的工具", exact=True)).not_to_be_visible()
    group = page.get_by_role("group", name="选择要允许的工具", exact=True)
    for checkbox in group.get_by_role("checkbox").all():
        checkbox.set_checked(checkbox.get_attribute("type") == "checkbox" and f"（{tool}）" in checkbox.locator("..").inner_text())
    page.get_by_label("只读目录", exact=True).fill("")
    page.get_by_label("读写目录", exact=True).fill(str(harness.workspace))
    page.get_by_label("允许的网络端点", exact=True).fill("api.example.test:443")
    page.get_by_role("button", name="采用只读资料方案", exact=True).click()
    expect(page.get_by_label("只读目录", exact=True)).to_have_value(str(harness.workspace))
    expect(page.get_by_label("读写目录", exact=True)).to_have_value("")
    expect(page.get_by_label("允许的网络端点", exact=True)).to_have_value("")
    checks[f"{platform}_checkbox_and_readonly_proposal_require_no_tool_typing"] = True
    page.get_by_label("本次修改人", exact=True).fill("onboarding-fixture-operator")
    with page.expect_response(lambda res: res.url.endswith(f"/v1/grants/{grant_id}/resources")) as resource_save:
        page.get_by_role("button", name="保存待批准权限", exact=True).click()
    assert resource_save.value.status == 200
    expect(page.get_by_role("group", name="选择要允许的工具", exact=True)).not_to_be_visible()
    saved = harness.api(f"/v1/grants/{grant_id}")["grant"]
    assert saved["status"] == "pending_approval"
    assert any(f["domain"] == "filesystem" and f["action"] == "fs.read" and f["resource"]["value"] == str(harness.workspace) for f in saved["facts"])
    assert {f["resource"]["value"] for f in saved["facts"] if f["domain"] == "tool" and f["effect"] == "allow"} == {tool}
    assert not any(f["effect"] == "allow" and (f["domain"] in {"network", "model"} or f["action"] == "fs.write") for f in saved["facts"])
    checks[f"{platform}_permission_draft_edit_persisted_without_approval"] = True
    page.get_by_role("checkbox", name="我已核对以上权限范围", exact=True).check()
    page.get_by_role("button", name="确认权限并应用授权", exact=True).click()
    expect(page.get_by_role("button", name="使用此授权并准备接入", exact=True)).to_be_visible()
    deployed = harness.api(f"/v1/grants/{grant_id}")["grant"]
    checks[f"{platform}_permission_approval_and_deploy_readback"] = deployed["status"] == "deployed"
    page.screenshot(path=str(out_dir / f"{platform}-permission-approved.png"), full_page=True, animations="disabled")
    page.get_by_role("checkbox", name="我已核对以上权限范围", exact=True).check()
    page.get_by_role("button", name="使用此授权并准备接入", exact=True).click()
    try:
        expect(page.get_by_role("button", name="确认应用", exact=True)).to_be_enabled(timeout=30000)
    except AssertionError:
        page.screenshot(path=str(out_dir / "permission-preview-failure.png"), full_page=True, animations="disabled")
        raise
    with page.expect_response(lambda res: res.url.endswith("/v1/adapter/install")) as applied:
        page.get_by_role("button", name="确认应用", exact=True).click()
    assert applied.value.ok
    expect(page.get_by_label("操作", exact=True)).not_to_be_visible()
    identities = harness.api("/v1/runtime-identities")["items"]
    identity = next(item for item in identities if item["grant_ref"]["grant_id"] == grant_id)
    checks[f"{platform}_permission_bound_install_readback"] = identity["status"] == "issued"
    allowed = probe("onboarding-allowed")
    assert allowed["allowed"], "saved permission must allow the synthetic read through installed adapter"
    checks[f"{platform}_installed_adapter_allowed_synthetic_read"] = True
    write_target = harness.workspace / f"{platform}-readonly-denied.txt"
    refused_write = probe("onboarding-removed-write", write_target, True)
    checks[f"{platform}_readonly_removed_write_denied_without_effect"] = refused_write["blocked"] and not refused_write["allowed"] and not write_target.exists()

    outside = harness.root / "outside-allowed-workspace.txt"
    outside.write_text("Synthetic material outside the approved scope.\n")
    denied = probe("onboarding-outside-scope", outside)
    checks[f"{platform}_installed_adapter_denies_outside_approved_directory"] = denied["blocked"] and not denied["allowed"]
    page.reload()
    card.get_by_role("button", name=re.compile("接入此实例|管理此实例")).click()
    page.get_by_role("link", name="查看此实例运行记录", exact=True).click()
    expect(page.get_by_label("智能体", exact=True)).to_have_value(identity["agent_id"])
    activities = harness.api("/v1/task-activities?view=tasks&offset=0&limit=50")["items"]
    own = [item for item in activities if item.get("binding", {}).get("agent_id") == identity["agent_id"]]
    assert len(own) == 1, "synthetic activity missing or ambiguous"
    row = page.locator("tbody tr").filter(has_text=own[0]["binding"]["session_id"])
    expect(row).to_have_count(1)
    row.get_by_role("link", name="查看活动记录", exact=True).click()
    expect(page.get_by_role("heading", name="运行详情", exact=True)).to_be_visible()
    expect(page.get_by_role("heading", name="真实结果", exact=True)).to_be_visible()
    result_card = page.locator(".task-security-card").filter(has=page.get_by_role("heading", name="真实结果", exact=True))
    expect(result_card.get_by_text("未设置结果核验", exact=True)).to_be_visible()
    checks[f"{platform}_missing_result_evidence_not_shown_as_completed"] = True
    expect(page.get_by_text("当前任务视图不能替代", exact=False)).not_to_be_visible()
    page.screenshot(path=str(out_dir / f"{platform}-activity-detail.png"), full_page=True, animations="disabled")
    expect(page.locator("tbody tr").filter(has_text=tool).first).not_to_be_visible()
    page.get_by_text("查看工具调用和审计详情", exact=True).click()
    expect(page.locator("tbody tr").filter(has_text=tool).first).to_be_visible()
    page.reload()
    expect(page.get_by_role("heading", name="真实结果", exact=True)).to_be_visible()
    page.get_by_role("link", name="返回运行记录", exact=True).click()
    expect(page.get_by_label("智能体", exact=True)).to_have_value(identity["agent_id"])
    expect(page.locator("tbody tr").filter(has_text=own[0]["binding"]["session_id"])).to_have_count(1)
    checks[f"{platform}_instance_activity_filter_detail_result_reload_and_back"] = True
    page.goto(harness.endpoint + "/overview")
    card.get_by_role("button", name=re.compile("接入此实例|管理此实例")).click()
    expect(page.get_by_role("button", name="停用此实例权限", exact=True)).to_be_visible()
    page.get_by_role("checkbox", name="确认停用，后续工具调用将被阻止", exact=True).check()
    page.get_by_role("button", name="停用此实例权限", exact=True).click()
    expect(page.get_by_role("button", name="停用此实例权限", exact=True)).not_to_be_visible()
    expect(page.get_by_role("button", name="确认应用", exact=True)).to_be_disabled()
    readback = next(item for item in harness.api("/v1/runtime-identities")["items"] if item["identity_id"] == identity["identity_id"])
    checks[f"{platform}_permission_revocation_persisted_blocks_apply"] = readback["status"] == "revoked"
    blocked = probe("onboarding-after-revoke")
    checks[f"{platform}_installed_adapter_blocks_read_after_ui_revocation"] = blocked["blocked"] and not blocked["allowed"]
    page.get_by_label("操作", exact=True).select_option("uninstall")
    expect(page.get_by_role("button", name="确认应用", exact=True)).to_be_enabled()
    with page.expect_response(lambda res: res.url.endswith("/v1/adapter/uninstall")) as removed:
        page.get_by_role("button", name="确认应用", exact=True).click()
    assert removed.value.ok
    expect(page.get_by_label("操作", exact=True)).not_to_be_visible()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--openclaw-root", type=Path, help="also verify OpenClaw permission lifecycle with this installed native runtime")
    parser.add_argument("--node", type=Path)
    parser.add_argument("--background-service", action="store_true", help="run the journey through an isolated real systemd user service")
    args = parser.parse_args()
    if bool(args.openclaw_root) != bool(args.node):
        parser.error("--openclaw-root and --node must be supplied together")
    args.out_dir.mkdir(parents=True, exist_ok=False)
    checks = {}
    failure = None
    failure_point = None
    cleanup = {"safe": False}
    service_checks = {}
    with fixture_directory(args, cleanup) as directory:
        root = Path(directory)
        harness_type = BackgroundOnboardingHarness if args.background_service else fixture.Harness
        harness = harness_type(root, SimpleNamespace(installer_managed_profile=True,
            hermes_cli=root / "unavailable-hermes-cli"))
        shutil.copy2(args.binary, harness.binary)
        home = Path(harness.env["HOME"])
        openclaw = home / ".openclaw"
        openclaw.mkdir()
        (openclaw / "openclaw.json").write_text('{"agents":{"list":[{"id":"fixture-role","workspace":"~/.openclaw/workspace-fixture"}]}}\n')
        skill = home / ".agents/skills/onboarding-fixture"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: onboarding-fixture\ndescription: Read synthetic onboarding notes.\nallowed-tools: read_file write_file read write terminal\n---\nRead the supplied synthetic notes only.\n")
        blocked_skill = home / ".agents/skills/onboarding-blocked"
        blocked_skill.mkdir()
        shutil.copyfile(ROOT / "apps/agentshield/internal/admission/testdata/skills/malicious/deception/SKILL.md", blocked_skill / "SKILL.md")
        configs = [Path(harness.env["HERMES_HOME"]) / "config.yaml", openclaw / "openclaw.json"]
        before = [path.read_bytes() for path in configs]
        try:
            harness.start()
            pairing = harness.command([str(harness.binary), "pair", "--port", harness.endpoint.rsplit(":",1)[1]])
            code = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing).group()
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width":1440,"height":1000}, locale="zh-CN")
                errors, scans, writes = [], [], []
                page.on("pageerror", lambda _: errors.append("pageerror"))
                def observe(request):
                    if request.method == "POST" and request.url.endswith("/v1/discovery/scan"):
                        scans.append(request.post_data_json)
                    if request.method == "POST" and re.search(r"/v1/adapter/(install|uninstall)$", request.url):
                        writes.append("adapter_write")
                page.on("request", observe)
                page.goto(harness.endpoint + "/overview")
                page.get_by_label("配对码", exact=True).fill(code)
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                expect(page.get_by_role("heading", name="接入当前环境", exact=True)).to_be_visible()
                expect(page.locator('[data-scan-state="succeeded"], [data-scan-state="partial"]')).to_be_visible(timeout=30000)
                checks["default_scan_automatic_once"] = scans == [{}]
                expect(page.get_by_label("额外目录（可选）", exact=True)).not_to_be_visible()
                checks["advanced_paths_collapsed"] = True
                cards = page.locator(".environment-connection")
                expect(cards.filter(has_text="Hermes").first).to_be_visible()
                expect(cards.filter(has_text="OpenClaw").first).to_be_visible()
                checks["both_platforms_detected"] = True
                cards.filter(has_text="Hermes").filter(has_text="work").first.get_by_role("button", name="接入此实例").click()
                expect(page.get_by_label("Hermes 实例", exact=True)).to_be_disabled()
                selected = page.get_by_label("Hermes 实例", exact=True)
                target = selected.locator("option:checked").inner_text()
                checks["exact_instance_preselected"] = "work" in target
                page.get_by_role("button", name="取消", exact=True).last.click()
                expect(page.get_by_label("Hermes 实例", exact=True)).not_to_be_visible()
                checks["cancel_does_not_install"] = not writes
                page.screenshot(path=str(args.out_dir / "desktop.png"), full_page=True, animations="disabled")
                for width in (375, 768):
                    page.set_viewport_size({"width":width,"height":1000})
                    expect(page.get_by_role("heading", name="接入当前环境", exact=True)).to_be_visible()
                    if width < 768:
                        expect(page.locator('.sidebar')).to_be_hidden()
                    checks[f"setup_controls_fit_{width}"] = page.locator(".environment-connections").evaluate(
                        "el => { const r=el.getBoundingClientRect(); return r.left >= 0 && r.right <= innerWidth; }")
                    mobile_action = cards.filter(has_text="Hermes").filter(has_text="work").first.get_by_role("button", name="接入此实例")
                    mobile_action.click()
                    expect(page.get_by_label("Hermes 实例", exact=True)).to_be_visible()
                    page.keyboard.press('Escape')
                    expect(page.get_by_label("Hermes 实例", exact=True)).not_to_be_visible()
                    expect(mobile_action).to_be_focused()
                    checks[f"setup_click_escape_focus_{width}"] = True
                    page.locator('.content').evaluate('el => el.scrollTop = 0')
                    page.screenshot(path=str(args.out_dir / f"viewport-{width}.png"), full_page=True, animations="disabled")
                page.set_viewport_size({"width":1440,"height":1000})
                for platform, label in (("hermes", "Hermes"), ("openclaw", "OpenClaw")):
                    card = cards.filter(has_text=label)
                    if platform == "hermes":
                        card = card.filter(has_text="work")
                    card = card.first
                    catalog = harness.api(f"/v1/adapter/instances?platform={platform}")
                    target = next(item for item in catalog["instances"]
                                  if (item["name"] == "work" if args.background_service and platform == "hermes" else item["active"]))
                    baseline = target["diagnosis"]["configuration_state"]
                    card.get_by_role("button", name=re.compile("接入此实例|管理此实例")).click()
                    with page.expect_response(lambda res: "/v1/adapter/preview" in res.url and res.request.method == "POST") as preview:
                        page.get_by_label("接入方式", exact=True).select_option("connection")
                    plan = preview.value.json()
                    assert plan["instance_id"] == target["instance_id"]
                    assert not plan.get("runtime_identity_id"), "connection-only must not grant authority"
                    if platform == "openclaw":
                        concurrent = json.loads(configs[1].read_text())
                        concurrent["fixture_concurrent"] = True
                        configs[1].write_text(json.dumps(concurrent) + "\n")
                        with page.expect_response(lambda res: res.url.endswith("/v1/adapter/install")) as stale:
                            page.get_by_role("button", name="确认应用", exact=True).click()
                        assert stale.value.status == 409, "changed config must invalidate preview"
                        expect(page.get_by_role("alert")).to_be_visible()
                        assert json.loads(configs[1].read_text()) == concurrent
                        with page.expect_response(lambda res: "/v1/adapter/preview" in res.url and res.request.method == "POST") as retried:
                            page.get_by_role("button", name="重新预览", exact=True).click()
                        plan = retried.value.json()
                        checks["stale_config_rejected_and_repreview_recovers"] = retried.value.ok
                    expect(page.get_by_role("button", name="确认应用", exact=True)).to_be_enabled()
                    with page.expect_response(lambda res: res.url.endswith("/v1/adapter/install")) as applied:
                        page.get_by_role("button", name="确认应用", exact=True).click()
                    assert applied.value.ok, "install request failed"
                    expect(page.get_by_label("接入方式", exact=True)).not_to_be_visible()
                    for change in plan["changes"]:
                        path = home / change["path"][2:] if change["path"].startswith("~/") else Path(change["path"])
                        assert path.is_relative_to(root), "fixture must stay isolated"
                        assert hashlib.sha256(path.read_bytes()).hexdigest() == change["after_sha256"]
                    checks[f"{platform}_install_files_match_preview"] = bool(plan["changes"])
                    installed = next(item for item in harness.api(f"/v1/adapter/instances?platform={platform}")["instances"]
                                     if item["instance_id"] == target["instance_id"])
                    checks[f"{platform}_backend_state_changed"] = installed["diagnosis"]["configuration_state"] != baseline
                    page.reload()
                    card.get_by_role("button", name=re.compile("接入此实例|管理此实例")).click()
                    expect(page.get_by_label(f"{label} 实例", exact=True)).to_have_value(target["instance_id"])
                    # The modal diagnosis is freshly fetched after a full browser reload.
                    assert installed["diagnosis"]["runtime_state"] == "unverified"
                    checks[f"{platform}_reload_exact_instance_without_false_runtime_claim"] = True
                    with page.expect_response(lambda res: "/v1/adapter/preview" in res.url and res.request.method == "POST") as uninstall_preview:
                        page.get_by_label("操作", exact=True).select_option("uninstall")
                    removal = uninstall_preview.value.json()
                    expect(page.get_by_role("button", name="确认应用", exact=True)).to_be_enabled()
                    with page.expect_response(lambda res: res.url.endswith("/v1/adapter/uninstall")) as removed:
                        page.get_by_role("button", name="确认应用", exact=True).click()
                    assert removed.value.ok, "uninstall request failed"
                    expect(page.get_by_label("操作", exact=True)).not_to_be_visible()
                    for change in removal["changes"]:
                        path = home / change["path"][2:] if change["path"].startswith("~/") else Path(change["path"])
                        assert path.is_relative_to(root)
                        if change["action"] == "remove":
                            assert not path.exists()
                        else:
                            assert hashlib.sha256(path.read_bytes()).hexdigest() == change["after_sha256"]
                    restored = next(item for item in harness.api(f"/v1/adapter/instances?platform={platform}")["instances"]
                                    if item["instance_id"] == target["instance_id"])
                    checks[f"{platform}_uninstall_backend_readback"] = restored["diagnosis"]["configuration_state"] == baseline
                checks["four_explicit_connector_writes_plus_one_rejected_stale_attempt"] = len(writes) == 5
                page.get_by_role("button", name="重新发现", exact=True).click()
                expect(page.locator('[data-scan-state="succeeded"], [data-scan-state="partial"]')).to_be_visible(timeout=30000)
                checks["explicit_rescan"] = scans == [{}, {}]
                verify_inline_first_check(page, harness, checks)
                admission = verify_inventory(page, harness, checks, args.out_dir)
                verify_permissions(page, harness, checks, args.out_dir, admission, "hermes",
                    lambda call, path=None, write=False: adapter_probe(harness, call, path, write))
                if args.openclaw_root:
                    verify_permissions(page, harness, checks, args.out_dir, admission, "openclaw",
                        lambda call, path=None, write=False: openclaw_probe(harness, args, call, path, write))
                checks["no_browser_errors"] = not errors
                browser.close()
            checks["hermes_existing_config_preserved"] = (native_config_preserved(before[0], configs[0].read_bytes())
                if args.background_service else configs[0].read_bytes() == before[0])
            checks["openclaw_existing_settings_preserved"] = json.loads(configs[1].read_bytes()).get("agents") == json.loads(before[1])["agents"]
            checks["other_hermes_profile_unchanged"] = (root / "hermes/config.yaml").read_text() == "fixture_default: unchanged\n"
        except Exception as exc:
            # Persist failure evidence too; never serialize request bodies or credentials.
            failure = type(exc).__name__
            frames = [frame for frame in traceback.extract_tb(exc.__traceback__) if Path(frame.filename).resolve() == Path(__file__).resolve()]
            if frames:
                failure_point = {"function": frames[-1].name, "line": frames[-1].lineno}
        finally:
            if args.background_service:
                harness.close(verify_reentry=failure is None and sys.exc_info()[0] is None)
                service_checks = harness.service_checks
                cleanup["safe"] = True
            else:
                harness.stop()
        checks["isolated_daemon_stopped"] = not harness.service_started if args.background_service else harness.proc is None
    result = {"schema_version":"siq.ux.environment-onboarding-proof.v1", "passed":failure is None and all(checks.values()),
        "scope":"isolated_HOME_real_daemon_browser_discovery_admission_permissions_install_revoke_activity", "production_eligible":False,
        "failure_category":failure, "failure_point":failure_point,
        "binary_sha256":hashlib.sha256(args.binary.read_bytes()).hexdigest(), "checks":checks,
        "service_mode": "systemd_user_setup" if args.background_service else "direct_process", "service_checks": service_checks,
        "not_proven":["Hermes_native_plugin_loading_and_runtime_verification", "OpenClaw_full_model_session", "OpenClaw_permission_grant_lifecycle", "business_result_artifact_verification", "model_and_OpenShell_unified_discovery",
                      "enterprise_onboarding", "usability_study", "installed_release_upgrade"]}
    if args.openclaw_root:
        if checks.get("openclaw_installed_adapter_blocks_read_after_ui_revocation"):
            result["not_proven"].remove("OpenClaw_permission_grant_lifecycle")
        result["openclaw_native_runtime"] = getattr(harness, "openclaw_native_metadata", None)
    (args.out_dir / "summary.sanitized.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))
    return 0 if result['passed'] else 1


if __name__ == "__main__":
    raise SystemExit(main())
