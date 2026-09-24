#!/usr/bin/env python3
"""Real UI/API/model-list HTTP in an isolated HOME; optional existing Step config read-only."""

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

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "fixture", REPO / "scripts/validate-intent-v2-hermes.py"
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["binary", "hermes-cli", "out-dir"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--step-config", type=Path)
    args = parser.parse_args()
    args.binary, args.hermes_cli = args.binary.resolve(), args.hermes_cli.resolve()
    args.installer_managed_profile = True
    args.out_dir.mkdir(parents=True, exist_ok=True)
    checks, failure, cloud_status = {}, None, None
    probe = {"status": 200, "calls": [], "data": [{"id": "fixture-model"}]}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            probe["calls"].append(
                {
                    "path_ok": self.path == "/v1/models",
                    "auth_ok": self.headers.get("Authorization")
                    == "Bearer synthetic-private-key",
                }
            )
            self.send_response(probe["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"data": probe["data"]}).encode())

        def log_message(self, *unused):
            pass

    service = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=service.serve_forever, daemon=True)
    worker.start()
    source_hash = (
        hashlib.sha256(args.step_config.read_bytes()).hexdigest()
        if args.step_config
        else None
    )
    try:
        with tempfile.TemporaryDirectory(prefix="siq-model-connections-") as temp:
            harness = fixture.Harness(Path(temp), args)
            shutil.copy2(args.binary, harness.binary)
            profile = Path(harness.env["HERMES_HOME"])
            config = profile / "config.yaml"
            base = f"http://127.0.0.1:{service.server_port}/v1"
            text = f"model:\n  default: fixture-model\n  provider: custom:fixture\n  api_mode: openai_chat\n  base_url: {base}\n  key_env: SIQ_FIXTURE_LIST_KEY\n"
            config.write_text(text)
            secret_file = profile / ".env"
            secret_file.write_text("SIQ_FIXTURE_LIST_KEY=synthetic-private-key\n")
            secret_file.chmod(0o600)
            claw = Path(harness.env["HOME"]) / ".openclaw"
            claw.mkdir()
            providers = {
                "fixture": {
                    "api": "openai-completions",
                    "baseUrl": base,
                    "apiKey": "synthetic-private-key",
                }
            }
            fallbacks = []
            secret_providers = {}
            if args.step_config:
                source = json.loads(args.step_config.read_text())
                existing = source["models"]["providers"]["stepfun-step-plan"]
                fixture.require(
                    "stepfun-step-plan/step-5-preview"
                    in source["agents"]["defaults"]["model"]["fallbacks"],
                    "Step 5 not present in existing configuration",
                )
                reference = existing.get("apiKey")
                if isinstance(reference, dict) and reference.get("source") == "file":
                    name = reference["provider"]
                    secret_providers[name] = source["secrets"]["providers"][name]
                providers["stepfun-step-plan"] = {
                    key: existing[key]
                    for key in ["api", "baseUrl", "apiKey", "auth", "authHeader"]
                    if key in existing
                }
                fixture.require(
                    existing["baseUrl"] == "https://api.stepfun.com/step_plan/v1",
                    "unexpected cloud destination",
                )
                fallbacks = ["stepfun-step-plan/step-5-preview"]
            claw_config = claw / "openclaw.json"
            claw_config.write_text(
                json.dumps(
                    {
                        "models": {"providers": providers},
                        "secrets": {"providers": secret_providers},
                        "agents": {
                            "defaults": {
                                "model": {
                                    "primary": "fixture/fixture-model",
                                    "fallbacks": fallbacks,
                                }
                            }
                        },
                    }
                )
            )
            claw_config.chmod(0o600)
            try:
                harness.start()
                catalog = harness.api("/v1/model-connections")
                target = next(
                    row
                    for row in catalog["items"]
                    if row["platform"] == "hermes" and row["model"] == "fixture-model"
                )
                fixture.require(
                    catalog["network_requested"] is False and not probe["calls"],
                    "discovery called service",
                )
                fixture.require(
                    "synthetic-private-key" not in json.dumps(catalog), "key escaped"
                )
                checks[
                    "discovery_reads_configuration_without_network_or_key_output"
                ] = True
                pairing = harness.command(
                    [
                        str(harness.binary),
                        "pair",
                        "--port",
                        harness.endpoint.rsplit(":", 1)[1],
                    ]
                )
                code = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing).group()
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    page = browser.new_page(
                        viewport={"width": 1440, "height": 1080},
                        locale="zh-CN",
                        timezone_id="Asia/Shanghai",
                    )
                    errors = []
                    page.on("pageerror", lambda _: errors.append("pageerror"))
                    page.goto(harness.endpoint + "/overview")
                    page.get_by_label("配对码", exact=True).fill(code)
                    page.get_by_role("button", name="建立管理会话", exact=True).click()
                    panel = page.get_by_role("region", name="模型服务发现")
                    select = panel.get_by_label("选择模型配置", exact=True)
                    expect(select).to_be_visible(timeout=30000)
                    select.select_option(target["id"])

                    def check_model():
                        with page.expect_response(
                            lambda r: r.url.endswith("/v1/model-connections/check"),
                            timeout=20000,
                        ) as response:
                            panel.get_by_role(
                                "button", name="检查模型服务", exact=True
                            ).click()
                        return response.value.status, response.value.json()

                    status, result = check_model()
                    fixture.require(
                        status == 200
                        and result["status"] == "listed"
                        and result["inference_verified"] is False,
                        "service list check failed",
                    )
                    expect(
                        panel.get_by_text("服务可达，模型已列出", exact=True)
                    ).to_be_visible()
                    checks["hermes_button_reaches_real_authenticated_http"] = len(
                        probe["calls"]
                    ) == 1 and all(all(c.values()) for c in probe["calls"])
                    page.screenshot(
                        path=str(args.out_dir / "model-listed.png"), full_page=True
                    )
                    for code, category, label in [
                        (401, "auth_failed", "认证未通过，请在原框架核对凭据"),
                        (429, "rate_limited", "服务限流，请稍后重试"),
                        (503, "service_error", "服务返回异常，请稍后重试"),
                    ]:
                        probe["status"] = code
                        status, result = check_model()
                        fixture.require(
                            status == 200 and result["status"] == category,
                            "failure category mismatch",
                        )
                        expect(panel.get_by_text(label, exact=True)).to_be_visible()
                        expect(
                            panel.get_by_text("服务可达，模型已列出", exact=True)
                        ).to_have_count(0)
                        checks[category + "_replaces_old_success"] = True
                    probe["status"] = 200
                    config.write_text(text + "fixture_changed: true\n")
                    calls = len(probe["calls"])
                    status, _ = check_model()
                    fixture.require(
                        status == 409 and len(probe["calls"]) == calls,
                        "stale configuration contacted service",
                    )
                    expect(
                        panel.get_by_text(
                            "配置可能已变化，或本地检查未完成。请重新发现后再试。",
                            exact=True,
                        )
                    ).to_be_visible()
                    checks["changed_configuration_rejected_before_network"] = True
                    panel.get_by_role("button", name="重新发现模型", exact=True).click()
                    expect(select).to_be_visible()
                    select.select_option(target["id"])
                    status, result = check_model()
                    fixture.require(
                        status == 200 and result["status"] == "listed",
                        "recovery failed",
                    )
                    checks["rediscovery_recovers_real_check"] = True
                    secret_file.unlink()
                    panel.get_by_role("button", name="重新发现模型", exact=True).click()
                    expect(select).to_be_visible()
                    select.select_option(target["id"])
                    expect(
                        panel.get_by_role("button", name="检查模型服务", exact=True)
                    ).to_be_disabled()
                    expect(
                        panel.get_by_text("已有凭据暂时无法复用", exact=True)
                    ).to_be_visible()
                    checks["missing_credential_disables_check"] = True
                    catalog = harness.api("/v1/model-connections")
                    claw_row = next(
                        row
                        for row in catalog["items"]
                        if row["platform"] == "openclaw" and row["role"] == "primary"
                    )
                    select.select_option(claw_row["id"])
                    status, result = check_model()
                    fixture.require(
                        status == 200 and result["status"] == "listed",
                        "OpenClaw check failed",
                    )
                    checks["openclaw_primary_uses_own_configuration"] = True
                    if args.step_config:
                        cloud = next(
                            row
                            for row in catalog["items"]
                            if row["provider"] == "stepfun-step-plan"
                        )
                        select.select_option(cloud["id"])
                        status, result = check_model()
                        fixture.require(
                            status == 200
                            and result["id"] == cloud["id"]
                            and result["inference_verified"] is False,
                            "cloud check response invalid",
                        )
                        cloud_status = result["status"]
                        checks["step5_existing_config_checked_without_model_switch"] = (
                            True
                        )
                    page.reload()
                    expect(select).to_be_visible(timeout=30000)
                    expect(
                        panel.get_by_text("服务可达，模型已列出", exact=True)
                    ).to_have_count(0)
                    checks["refresh_does_not_restore_stale_success"] = True
                    page.goto(harness.endpoint + "/bindings")
                    expect(select).to_be_visible(timeout=30000)
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_function(
                        "document.querySelector('.sidebar').getBoundingClientRect().right <= 0"
                    )
                    select.select_option(claw_row["id"])
                    status, result = check_model()
                    fixture.require(
                        status == 200 and result["status"] == "listed",
                        "mobile action failed",
                    )
                    checks["runtime_page_mobile_button_executes"] = select.evaluate(
                        "el => el.getBoundingClientRect().right <= innerWidth && el.getBoundingClientRect().left >= 0"
                    )
                    page.screenshot(
                        path=str(args.out_dir / "model-mobile.png"), full_page=True
                    )
                    checks["no_browser_errors"] = not errors
                    browser.close()
                checks["no_grants_created"] = not harness.api("/v1/grants")["grants"]
            except Exception as exc:
                failure = {
                    "category": type(exc).__name__,
                    "frames": [
                        {"file": Path(f.filename).name, "line": f.lineno}
                        for f in traceback.extract_tb(exc.__traceback__)
                    ],
                }
            finally:
                harness.stop()
    finally:
        service.shutdown()
        service.server_close()
        worker.join(timeout=5)
    if args.step_config:
        checks["existing_openclaw_config_unchanged"] = (
            hashlib.sha256(args.step_config.read_bytes()).hexdigest() == source_hash
        )
    result = {
        "schema_version": "siq.model-connections-browser-proof/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "passed": failure is None and bool(checks) and all(checks.values()),
        "failure": failure,
        "checks": checks,
        "cloud_list_status": cloud_status,
        "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "real UI and isolated daemon; synthetic authenticated HTTP model listing plus optional existing Step cloud configuration; no inference or business data",
    }
    (args.out_dir / "result.sanitized.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
