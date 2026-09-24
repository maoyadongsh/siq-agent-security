#!/usr/bin/env python3
"""Real registered-gateway selection and policy reads; no native selection or sandbox writes."""
import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from datetime import UTC, datetime
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("fixture", REPO / "scripts/validate-intent-v2-hermes.py")
fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["binary", "hermes-cli", "openshell-cli", "xdg-config", "out-dir"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--gateway", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--path-discovery", action="store_true")
    args = parser.parse_args()
    args.binary, args.hermes_cli, args.openshell_cli = args.binary.resolve(), args.hermes_cli.resolve(), args.openshell_cli.resolve()
    args.installer_managed_profile = True
    args.out_dir.mkdir(parents=True, exist_ok=True)
    checks, failure = {}, None
    metadata_root = args.xdg_config / "openshell/gateways"
    metadata = {str(p.relative_to(metadata_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in metadata_root.glob("*/metadata.json")}
    with tempfile.TemporaryDirectory(prefix="siq-openshell-gateways-") as temp:
        harness = fixture.Harness(Path(temp), args)
        shutil.copy2(args.binary, harness.binary)
        fail_flag, remove_flag, drift_flag, delay_flag = [Path(temp) / name for name in ["unavailable", "removed", "drift", "delay"]]
        calls_file = Path(temp) / "calls.jsonl"
        wrapper = Path(temp) / "openshell"
        wrapper.write_text(f'''#!{sys.executable}
import os,sys,time,json,subprocess
from pathlib import Path
args=sys.argv[1:]
rest=list(args)
name=""
while rest and rest[0] in ("--gateway", "--gateway-endpoint"):
    if rest[0]=="--gateway":name=rest[1]
    rest=rest[2:]
allowed=(rest in (["gateway","list","--output","json"],["gateway","info"],["status"],["--version"],["sandbox","list","--limit","1000","--output","json"]) or len(rest)==4 and rest[:2]==["policy","get"] and rest[-1]=="--full")
with open({str(calls_file)!r},"a") as f:f.write(json.dumps({{"allowed":allowed,"gateway":name,"operation":rest[0] if rest else ""}})+"\\n")
if not allowed:sys.exit(80)
if Path({str(fail_flag)!r}).exists():sys.exit(7)
if rest[:2]==["policy","get"] and Path({str(delay_flag)!r}).exists():time.sleep(2)
if rest[:2]==["gateway","list"]:
    result=subprocess.run([{str(args.openshell_cli)!r},*args],capture_output=True,text=True,timeout=15)
    if result.returncode:sys.exit(result.returncode)
    rows=json.loads(result.stdout)
    if Path({str(remove_flag)!r}).exists():rows=[r for r in rows if r["name"]!=Path({str(remove_flag)!r}).read_text()]
    if Path({str(drift_flag)!r}).exists():
        for row in rows:
            if row["name"]==Path({str(drift_flag)!r}).read_text():row["endpoint"]="https://127.0.0.1:1"
    print(json.dumps(rows));sys.exit(0)
os.execv({str(args.openshell_cli)!r},[{str(args.openshell_cli)!r},*args])
''')
        wrapper.chmod(0o700)
        harness.env.update({"XDG_CONFIG_HOME": str(args.xdg_config.resolve()), "SIQ_AS_OPENSHELL_CLI_BIN": str(wrapper), "SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT": args.endpoint, "SIQ_AS_OPENSHELL_GATEWAY_NAME": args.gateway})
        if args.path_discovery:
            harness.env["PATH"] = str(wrapper.parent) + ":" + harness.env.get("PATH", "/usr/bin:/bin")
            for key in ["SIQ_AS_OPENSHELL_CLI_BIN", "SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT", "SIQ_AS_OPENSHELL_GATEWAY_NAME", "SIQ_AS_OPENSHELL_ENV_SH", "SIQ_AS_OPENSHELL_GATEWAY_INSECURE"]:
                harness.env.pop(key, None)
        try:
            harness.start()
            registrations = harness.api("/v1/openshell/gateways")
            fixture.require(registrations["state"] == "available" and len(registrations["items"]) >= 2, "two native registrations required")
            primary = next(r for r in registrations["items"] if r["name"] == args.gateway)
            other = next(r for r in registrations["items"] if r["gateway_id"] != primary["gateway_id"])
            initial = harness.api("/v1/openshell/targets")
            fixture.require(initial["state"] == "available" and initial["items"], "current gateway has no native sandbox")
            if args.path_discovery:
                fixture.require(initial["source"] == "path" and not initial["can_inspect"], "PATH fixture accidentally preconfigured endpoint")
                checks["path_discovery_without_explicit_gateway_endpoint"] = True
            checks["native_gateway_catalog_has_multiple_registrations"] = not registrations["started_gateway"] and not registrations["changed_native_selection"]
            def selection(row):
                return {"schema_version": "local-openshell-gateway-select/v1", "gateway_id": row["gateway_id"], "configuration_fingerprint": row["configuration_fingerprint"]}
            pairing = harness.command([str(harness.binary), "pair", "--port", harness.endpoint.rsplit(":", 1)[1]])
            code = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing).group()
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1080}, locale="zh-CN", timezone_id="Asia/Shanghai")
                errors = []
                page.on("pageerror", lambda _: errors.append("pageerror"))
                page.goto(harness.endpoint + "/overview")
                page.get_by_label("配对码", exact=True).fill(code)
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                picker = page.get_by_role("region", name="OpenShell 网关选择")
                gateway_select = picker.get_by_label("选择已登记网关", exact=True)
                panel = page.get_by_role("region", name="OpenShell 环境发现")
                sandbox_select = panel.get_by_label("选择沙箱", exact=True)
                expect(gateway_select).to_be_visible(timeout=30000)
                fixture.require(gateway_select.locator("option").count() == len(registrations["items"]) + 1, "gateway choices differ from backend")
                with page.expect_response(lambda r: r.url.endswith("/v1/openshell/gateways/targets"), timeout=60000) as first:
                    gateway_select.select_option(primary["gateway_id"])
                first_body = first.value.json()
                fixture.require(first.value.status == 200 and first_body["gateway_id"] == primary["gateway_id"], "wrong selected gateway")
                catalog = first_body["catalog"]
                fixture.require(catalog["gateway"] == primary["name"] and catalog["items"] == initial["items"], "selected catalog mismatch")
                expect(sandbox_select).to_be_visible()
                item = next(r for r in catalog["items"] if r["phase"] == "Ready")
                sandbox_select.select_option(item["sandbox_id"])
                checks["gateway_choice_reads_exact_native_sandbox_catalog"] = True
                def inspect():
                    with page.expect_response(lambda r: r.url.endswith("/v1/openshell/gateways/inspect"), timeout=60000) as response:
                        panel.get_by_role("button", name="读取当前策略", exact=True).click()
                    fixture.require(response.value.status == 200, "native policy read failed")
                    result = response.value.json()
                    fixture.require(result["gateway_id"] == primary["gateway_id"] and result["inspection"]["sandbox_id"] == item["sandbox_id"] and result["inspection"]["enforcement_verified"] is False, "wrong policy projection")
                    return result
                inspect()
                expect(panel.get_by_text(item["name"] + "：当前策略已读回", exact=True)).to_be_visible()
                checks["selected_gateway_policy_button_uses_real_cli"] = True
                page.screenshot(path=str(args.out_dir / "gateway-policy.png"), full_page=True)
                page.reload()
                expect(gateway_select).to_have_value(primary["gateway_id"], timeout=30000)
                expect(sandbox_select).to_be_visible(timeout=60000)
                expect(panel.get_by_text(item["name"] + "：当前策略已读回", exact=True)).to_have_count(0)
                checks["refresh_restores_gateway_without_stale_policy_success"] = True
                sandbox_select.select_option(item["sandbox_id"])
                delay_flag.touch()
                with page.expect_request(lambda r: r.url.endswith("/v1/openshell/gateways/inspect")):
                    panel.get_by_role("button", name="读取当前策略", exact=True).click()
                with page.expect_response(lambda r: r.url.endswith("/v1/openshell/gateways/targets"), timeout=60000) as second:
                    gateway_select.select_option(other["gateway_id"])
                second_body = second.value.json()
                fixture.require(second.value.status == 200 and second_body["gateway_id"] == other["gateway_id"] and second_body["catalog"]["gateway"] == other["name"], "gateway switch fell back")
                delay_flag.unlink()
                page.wait_for_timeout(2500)
                expect(panel.get_by_text(item["name"] + "：当前策略已读回", exact=True)).to_have_count(0)
                checks["switch_cancels_old_read_and_clears_old_result"] = True
                if not second_body["catalog"]["items"]:
                    expect(panel.get_by_text("当前网关没有沙箱。此结果不代表其他网关也为空。", exact=True)).to_be_visible()
                    checks["empty_native_gateway_distinguished_from_main_gateway"] = True
                mismatch = {**selection(other), "schema_version": "local-openshell-gateway-inspect/v1", "sandbox_id": item["sandbox_id"], "name": item["name"], "endpoint_fingerprint": catalog["endpoint_fingerprint"]}
                harness.api("/v1/openshell/gateways/inspect", mismatch, expected=409)
                checks["cross_gateway_sandbox_selection_rejected"] = True
                drift_flag.write_text(primary["name"])
                harness.api("/v1/openshell/gateways/targets", selection(primary), expected=409)
                drift_flag.unlink()
                checks["changed_registration_rejects_old_fingerprint"] = True
                gateway_select.select_option(primary["gateway_id"])
                expect(sandbox_select).to_be_visible(timeout=60000)
                remove_flag.write_text(primary["name"])
                picker.get_by_role("button", name="刷新网关列表", exact=True).click()
                expect(picker.get_by_text("上次选择的网关暂不可用或登记已变化，请刷新列表或重新选择。", exact=True)).to_be_visible(timeout=30000)
                expect(panel).to_have_count(0)
                checks["removed_registration_never_silently_selects_default"] = True
                remove_flag.unlink()
                picker.get_by_role("button", name="刷新网关列表", exact=True).click()
                expect(sandbox_select).to_be_visible(timeout=60000)
                checks["registration_refresh_recovers_saved_selection"] = True
                fail_flag.touch()
                picker.get_by_role("button", name="刷新网关列表", exact=True).click()
                expect(picker.get_by_text("已登记网关清单未能完整读取，请检查现有 CLI 配置后刷新；此状态不代表没有网关。", exact=True)).to_be_visible(timeout=30000)
                expect(panel).to_have_count(0)
                fail_flag.unlink()
                picker.get_by_role("button", name="刷新网关列表", exact=True).click()
                expect(sandbox_select).to_be_visible(timeout=60000)
                checks["cli_failure_visible_and_retry_recovers"] = True
                page.goto(harness.endpoint + "/bindings")
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 0")
                expect(gateway_select).to_have_value(primary["gateway_id"], timeout=30000)
                expect(sandbox_select).to_be_visible(timeout=60000)
                sandbox_select.select_option(item["sandbox_id"])
                inspect()
                checks["mobile_runtime_page_restores_choice_and_reads_policy"] = gateway_select.evaluate("el => el.getBoundingClientRect().right <= innerWidth && el.getBoundingClientRect().left >= 0")
                page.screenshot(path=str(args.out_dir / "gateway-mobile.png"), full_page=True)
                checks["no_browser_errors"] = not errors
                browser.close()
            after = harness.api("/v1/openshell/gateways")
            checks["native_gateway_active_selection_unchanged"] = after["items"] == registrations["items"]
            checks["default_runtime_catalog_unchanged"] = harness.api("/v1/openshell/targets")["items"] == initial["items"]
            checks["no_grants_created"] = not harness.api("/v1/grants")["grants"]
            invocations = [json.loads(line) for line in calls_file.read_text().splitlines()]
            checks["all_native_cli_invocations_are_read_only"] = all(row["allowed"] for row in invocations)
        except Exception as exc:
            failure = {"category": type(exc).__name__, "frames": [{"file": Path(f.filename).name, "line": f.lineno} for f in traceback.extract_tb(exc.__traceback__)]}
        finally:
            harness.stop()
    after_metadata = {str(p.relative_to(metadata_root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in metadata_root.glob("*/metadata.json")}
    checks["all_native_gateway_metadata_unchanged"] = metadata == after_metadata
    result = {"schema_version": "siq.openshell-gateways-browser-proof/v1", "recorded_at": datetime.now(UTC).isoformat(), "passed": failure is None and bool(checks) and all(checks.values()), "failure": failure, "checks": checks, "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(), "openshell_cli_sha256": hashlib.sha256(args.openshell_cli.read_bytes()).hexdigest(), "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "scope": "real registered gateways and native read-only CLI, isolated candidate and Chromium; controlled metadata-output faults; no sandbox create/execute or policy writes"}
    (args.out_dir / "result.sanitized.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
