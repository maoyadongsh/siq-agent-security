#!/usr/bin/env python3
"""Registered project to native Hermes: isolated real daemon/UI, optional research profile read-only."""
import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import tempfile
import threading
import traceback
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("fixture", REPO / "scripts/validate-intent-v2-hermes.py")
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
CATALOG = "/v1/adapter/instances?platform=hermes&include_projects=true"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "hermes-cli", "out-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--research-project", type=Path)
    args = parser.parse_args()
    args.binary, args.hermes_cli = args.binary.resolve(), args.hermes_cli.resolve()
    args.installer_managed_profile = True
    args.out_dir.mkdir(parents=True, exist_ok=True)
    checks, failure = {}, None
    calls = []
    release_model = threading.Event()
    release_model.set()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(self.path == "/v1/models" and self.headers.get("Authorization") == "Bearer synthetic-project-key")
            if not release_model.wait(timeout=20):
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"data":[{"id":"project-fixture-model"}]}')

        def log_message(self, *unused):
            pass

    service = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=service.serve_forever, daemon=True).start()
    research_file = args.research_project / "agents/hermes/profiles/siq_analysis/config.yaml" if args.research_project else None
    research_hash = hashlib.sha256(research_file.read_bytes()).hexdigest() if research_file else None
    try:
        with tempfile.TemporaryDirectory(prefix="siq-project-hermes-") as temp:
            harness = fixture.Harness(Path(temp), args)
            shutil.copy2(args.binary, harness.binary)
            harness.env.pop("HERMES_HOME", None)
            project = Path(temp) / "研究项目"
            profile = project / "agents/hermes/profiles/project-analysis"
            skill = profile / "skills/project-report"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: project-report\ndescription: Read public fixture reports.\n---\n# Report\n")
            config = profile / "config.yaml"
            config.write_text(f"terminal:\n  env: local\nfixture_setting: retain\nmodel:\n  default: project-fixture-model\n  provider: custom:fixture\n  api_mode: openai_chat\n  base_url: http://127.0.0.1:{service.server_port}/v1\n  key_env: SIQ_PROJECT_MODEL_KEY\n")
            (profile / ".env").write_text("SIQ_PROJECT_MODEL_KEY=synthetic-project-key\n")
            (profile / ".env").chmod(0o600)
            sentinel = project / "not-executed"
            (project / "start.sh").write_text(f"touch '{sentinel}'\n")
            other = Path(harness.env["HOME"]) / ".hermes/profiles/project-analysis"
            other.mkdir(parents=True)
            (other / "config.yaml").write_text("fixture_default: unchanged\n")
            other_hash = hashlib.sha256((other / "config.yaml").read_bytes()).hexdigest()
            before = config.read_bytes()
            try:
                harness.start()
                checks["unregistered_project_not_discovered"] = not any(i["source"] == "registered_project" for i in harness.api(CATALOG)["instances"])
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1440, "height": 1080}, locale="zh-CN", timezone_id="Asia/Shanghai")
                    errors = []
                    page.on("pageerror", lambda _: errors.append("pageerror"))

                    def pair():
                        output = harness.command([str(harness.binary), "pair", "--port", harness.endpoint.rsplit(":", 1)[1]])
                        code = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", output).group()
                        page.goto(harness.endpoint + "/overview")
                        page.get_by_label("配对码", exact=True).fill(code)
                        page.get_by_role("button", name="建立管理会话", exact=True).click()
                        expect(page.get_by_role("button", name="重新发现", exact=True)).to_be_enabled(timeout=30000)

                    def add_project(path):
                        details = page.locator("details").filter(has=page.locator("summary", has_text="高级选项：补充目录与扫描范围")).first
                        if not details.evaluate("el => el.open"):
                            details.locator("summary").first.click()
                        page.get_by_label("添加目录类型", exact=True).select_option("project_dir")
                        page.get_by_label("额外目录（可选）", exact=True).fill(str(path))
                        with page.expect_response(lambda r: r.url.endswith("/v1/discovery/preview")) as response:
                            page.get_by_role("button", name="预览扫描范围", exact=True).click()
                        fixture.require(response.value.status == 200, "project preview failed")
                        return response.value.json()

                    def scan_project():
                        with page.expect_response(lambda r: r.url.endswith("/v1/discovery/scan")) as response:
                            page.get_by_role("button", name="添加目录并扫描", exact=True).click()
                        fixture.require(response.value.status == 202, "scan not accepted")
                        expect(page.get_by_role("button", name="重新发现", exact=True)).to_be_enabled(timeout=30000)

                    pair()
                    preview = add_project(project)
                    fixture.require(any("project-analysis/config.yaml" in row["path"] for row in preview["roots"]), "project profile missing from preview")
                    checks["preview_shows_profiles_without_persisting_or_writing"] = config.read_bytes() == before and not any(i["source"] == "registered_project" for i in harness.api(CATALOG)["instances"])
                    scan_project()
                    card = page.locator(".environment-connection").filter(has=page.get_by_text("查看项目位置", exact=True)).filter(has_text="project-analysis")
                    expect(card).to_be_visible(timeout=30000)
                    instance = next(i for i in harness.api(CATALOG)["instances"] if i["source"] == "registered_project")
                    identity = instance["instance_id"]
                    checks["project_and_same_named_default_remain_distinct"] = sum(i["name"] == "project-analysis" for i in harness.api(CATALOG)["instances"]) == 2
                    model = next(i for i in harness.api("/v1/model-connections")["items"] if i["instance_id"] == identity)
                    panel = page.get_by_role("region", name="模型服务发现")
                    expect(panel.get_by_label("选择模型配置", exact=True)).to_be_visible()
                    panel.get_by_label("选择模型配置", exact=True).select_option(model["id"])
                    checks["scan_refreshes_model_catalog_without_reload_or_network"] = not calls
                    with page.expect_response(lambda r: r.url.endswith("/v1/model-connections/check")) as response:
                        panel.get_by_role("button", name="检查模型服务", exact=True).click()
                    checks["project_model_button_uses_existing_private_env_reference"] = response.value.status == 200 and response.value.json()["status"] == "listed" and calls == [True]
                    release_model.clear()
                    try:
                        with page.expect_response(lambda r: r.url.endswith("/v1/model-connections/check")) as inflight:
                            panel.get_by_role("button", name="检查模型服务", exact=True).click()
                            page.get_by_role("button", name="重新发现", exact=True).click()
                            expect(page.get_by_role("button", name="重新发现", exact=True)).to_be_enabled(timeout=30000)
                            expect(panel.get_by_role("button", name="正在检查模型服务…", exact=True)).to_be_visible()
                            with page.expect_response(lambda r: r.url.endswith("/v1/model-connections")) as refreshed:
                                release_model.set()
                        fixture.require(refreshed.value.status == 200, "automatic model refresh failed")
                        expect(panel.get_by_text("服务可达，模型已列出", exact=True)).to_be_visible()
                        checks["inventory_scan_does_not_cancel_inflight_model_check"] = inflight.value.status == 200 and calls == [True, True]
                        checks["unchanged_configuration_refresh_preserves_check_result"] = True
                    finally:
                        release_model.set()
                    config.write_text(config.read_text() + "fixture_refresh: changed\n")
                    with page.expect_response(lambda r: r.url.endswith("/v1/model-connections")):
                        page.get_by_role("button", name="重新发现", exact=True).click()
                    expect(panel.get_by_text("服务可达，模型已列出", exact=True)).to_have_count(0)
                    checks["configuration_drift_on_scan_clears_old_model_success"] = calls == [True, True]
                    assets = harness.api("/v1/assets")
                    checks["project_skill_visible_in_real_inventory"] = "project-report" in json.dumps(assets)
                    page.reload()
                    expect(card).to_be_visible(timeout=30000)
                    checks["refresh_preserves_registered_project_and_identity"] = any(i["instance_id"] == identity for i in harness.api(CATALOG)["instances"])
                    card.get_by_role("button", name="接入此实例", exact=True).click()
                    dialog = page.get_by_role("dialog")
                    dialog.get_by_label("接入方式", exact=True).select_option("connection")
                    expect(dialog.get_by_role("button", name="确认应用", exact=True)).to_be_enabled(timeout=30000)
                    dialog.get_by_role("button", name="取消", exact=True).click()
                    checks["cancelled_preview_does_not_install"] = not (profile / "plugins/siq-agent-security").exists()
                    card.get_by_role("button", name="接入此实例", exact=True).click()
                    dialog.get_by_label("接入方式", exact=True).select_option("connection")
                    expect(dialog.get_by_label("由 Hermes 同步启用本实例插件")).to_be_checked()
                    expect(dialog.get_by_role("button", name="确认应用", exact=True)).to_be_enabled(timeout=30000)
                    dialog.get_by_role("button", name="确认应用", exact=True).click()
                    expect(dialog).not_to_be_visible(timeout=30000)
                    checks["project_install_persists_exact_instance_without_grants"] = next(i for i in harness.api(CATALOG)["instances"] if i["instance_id"] == identity)["diagnosis"]["configuration_state"] == "ready" and not harness.api("/v1/grants")["grants"]
                    checks["native_install_preserves_other_profile"] = hashlib.sha256((other / "config.yaml").read_bytes()).hexdigest() == other_hash
                    page.get_by_role("button", name="验证刚接入的实例", exact=True).click()
                    expect(dialog.get_by_label("自检实例 / profile")).to_have_value(identity)
                    dialog.get_by_label("确认人", exact=True).fill("synthetic-project-operator")
                    start = dialog.get_by_role("button", name="确认并开始自检", exact=True)
                    expect(start).to_be_enabled(timeout=30000)
                    start.click()
                    expect(dialog.get_by_text("本次自检通过", exact=True)).to_be_visible(timeout=140000)
                    expect(dialog.get_by_text("临时权限与材料：已撤权并清理", exact=True)).to_be_visible()
                    checks["registered_project_native_hermes_allow_deny_and_cleanup"] = dialog.get_by_text("本次关联 5 条回执。", exact=True).is_visible()
                    with page.expect_response(lambda r: r.url.endswith("/activity")) as activity_response:
                        dialog.get_by_role("button", name="查看本次运行记录", exact=True).click()
                    activity = activity_response.value.json()
                    expect(page).to_have_url(re.compile(r"/activities/"), timeout=20000)
                    query = parse_qs(urlparse(page.url).query)
                    checks["native_result_links_to_exact_activity"] = activity["instance_id"] == identity and query["task_id"] == [activity["activity"]["binding"]["task_id"]]
                    page.goto(harness.endpoint + "/overview")
                    expect(card).to_be_visible(timeout=30000)
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 1")
                    card.get_by_text("查看项目位置", exact=True).click()
                    checks["mobile_project_selection_fits"] = card.evaluate("el => { const r = el.getBoundingClientRect(); return el.scrollWidth <= el.clientWidth + 1 && r.left >= 0 && r.right <= window.innerWidth; }")
                    action = card.get_by_role("button", name="验证连接", exact=True)
                    action.scroll_into_view_if_needed()
                    checks["mobile_project_action_not_obscured"] = action.evaluate("el => { const r = el.getBoundingClientRect(); return el.contains(document.elementFromPoint(r.x + r.width/2, r.y + r.height/2)); }")
                    page.screenshot(path=str(args.out_dir / "project-mobile.png"), full_page=True)
                    page.set_viewport_size({"width": 1440, "height": 1080})
                    parked = project.with_name("parked-project")
                    project.rename(parked)
                    try:
                        page.get_by_role("button", name="重新发现", exact=True).click()
                        expect(card).not_to_be_visible(timeout=30000)
                        harness.api("/v1/adapter/preview", {"platform": "hermes", "action": "install", "instance_id": identity}, expected=409)
                        checks["moved_project_removed_and_stale_action_rejected"] = True
                    finally:
                        parked.rename(project)
                    expect(page.get_by_role("button", name="重新发现", exact=True)).to_be_enabled(timeout=30000)
                    page.get_by_role("button", name="重新发现", exact=True).click()
                    expect(card).to_be_visible(timeout=30000)
                    checks["restored_project_recovers_original_identity"] = any(i["instance_id"] == identity for i in harness.api(CATALOG)["instances"])
                    if research_file:
                        expect(page.get_by_role("button", name="重新发现", exact=True)).to_be_enabled(timeout=30000)
                        add_project(args.research_project)
                        scan_project()
                        research = page.locator(".environment-connection").filter(has=page.get_by_text("Hermes · siq_analysis", exact=True))
                        expect(research).to_be_visible(timeout=30000)
                        checks["actual_research_siq_analysis_discovered_read_only"] = any(i["name"] == "siq_analysis" and i["source"] == "registered_project" for i in harness.api(CATALOG)["instances"])
                        checks["actual_research_configuration_unchanged"] = hashlib.sha256(research_file.read_bytes()).hexdigest() == research_hash
                    harness.stop()
                    harness.start()
                    context = browser.new_context(viewport={"width": 1440, "height": 1080}, locale="zh-CN")
                    page = context.new_page()
                    pair()
                    checks["daemon_restart_preserves_project_registration"] = any(i["instance_id"] == identity for i in harness.api(CATALOG)["instances"])
                    cli = json.loads(harness.command([str(harness.binary), "adapter", "instances", "hermes"]))
                    checks["cli_and_ui_resolve_same_registered_instance"] = any(i["instance_id"] == identity for i in cli["instances"])
                    harness.stop()
                    inventory = json.loads(harness.command([str(harness.binary), "inventory"]))
                    checks["cli_inventory_reuses_same_persisted_project_scope"] = any(i.get("attributes", {}).get("instance_id") == identity for i in inventory["candidates"])
                    checks["discovery_never_executes_project_script"] = not sentinel.exists()
                    checks["no_browser_errors"] = not errors
                    browser.close()
                fixture.require(all(checks.values()), "project proof failed")
            finally:
                harness.stop()
    except Exception as exc:
        failure = {"type": type(exc).__name__, "frames": [{"file": Path(f.filename).name, "line": f.lineno} for f in traceback.extract_tb(exc.__traceback__)]}
    finally:
        service.shutdown()
        service.server_close()
    result = {"schema_version": "siq.project-hermes-browser-proof/v1", "recorded_at": datetime.now(UTC).isoformat(), "passed": failure is None and all(checks.values()), "checks": checks, "failure": failure, "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(), "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "hermes_cli_sha256": hashlib.sha256(args.hermes_cli.read_bytes()).hexdigest(), "scope": "Owned project real browser, daemon, installer and native Hermes self-check; synthetic local model-list server; optional existing research profile discovery read-only; no business or cloud calls"}
    (args.out_dir / "result.sanitized.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
