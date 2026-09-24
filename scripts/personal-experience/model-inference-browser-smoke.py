#!/usr/bin/env python3
"""Real model-answer UI/API with isolated state and optional fixed public Step 5 test."""

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import tempfile
import threading
import traceback
import time
import socket
import uuid
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
    probe = {"status": 200, "calls": [], "mode": "pass"}
    gate = threading.Event()
    gate.set()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            marker = re.search(r"SIQ_MODEL_TEST_[0-9a-f]{24}", body["messages"][0]["content"])
            probe["calls"].append({
                "path_ok": self.path == "/v1/chat/completions",
                "auth_ok": self.headers.get("Authorization") == "Bearer synthetic-private-key",
                "public_prompt_only": bool(marker) and len(body) == 4 and body["max_tokens"] == 512,
                "selected_model": body.get("model") == "fixture-model",
            })
            mode, status = probe["mode"], probe["status"]
            gate.wait(15)
            if mode == "disconnect":
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            answer = marker.group() if marker and mode == "pass" else "SYNTHETIC_WRONG_ANSWER"
            self.wfile.write(json.dumps({"model": "fixture-model", "choices": [
                {"finish_reason": "stop", "message": {"role": "assistant", "content": answer}}
            ]}).encode())

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
                target = next(row for row in catalog["items"] if row["platform"] == "hermes" and row["model"] == "fixture-model")
                fixture.require(not probe["calls"], "discovery contacted model")
                checks["discovery_does_not_generate_tokens"] = True
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
                    panel = page.get_by_role("region", name="模型服务发现")
                    select = panel.get_by_label("选择模型配置", exact=True)
                    expect(select).to_be_visible(timeout=30000)
                    select.select_option(target["id"])
                    answer_panel = panel.get_by_label("模型回答测试", exact=True)
                    start = answer_panel.get_by_role("button", name="测试模型回答", exact=True)
                    refresh = answer_panel.get_by_role("button", name="刷新测试状态", exact=True)

                    def latest(row):
                        return harness.api("/v1/model-inference-tests?model_id=" + row["id"])["record"]

                    def wait_record(row, status):
                        deadline = time.monotonic() + 65
                        while time.monotonic() < deadline:
                            record = latest(row)
                            if record and record["status"] != "running":
                                fixture.require(record["status"] == status, "unexpected inference status: " + record["status"])
                                return record
                            time.sleep(0.15)
                        raise AssertionError("inference did not finish")

                    def start_test():
                        expect(start).to_be_enabled(timeout=15000)
                        with page.expect_response(lambda r: r.url.endswith("/v1/model-inference-tests") and r.request.method == "POST") as response:
                            start.click()
                        fixture.require(response.value.status == 202, "test not accepted")
                        return response.value.json()

                    gate.clear()
                    running = start_test()
                    expect(answer_panel.get_by_role("button", name="模型测试进行中…", exact=True)).to_be_disabled()
                    expect(select).to_be_disabled()
                    request = {"schema_version": "local-model-inference-create/v1", "model_id": target["id"], "fingerprint": target["fingerprint"], "request_id": running["request_id"], "confirm_test": True}
                    duplicate = harness.api("/v1/model-inference-tests", request)
                    fixture.require(duplicate["request_id"] == running["request_id"], "duplicate changed identity")
                    harness.api("/v1/model-inference-tests", {**request, "request_id": "mt-" + uuid.uuid4().hex}, expected=409)
                    page.reload()
                    expect(select).to_be_visible(timeout=30000)
                    if select.input_value() != target["id"]:
                        select.select_option(target["id"])
                    expect(answer_panel.get_by_role("button", name="模型测试进行中…", exact=True)).to_be_disabled(timeout=10000)
                    gate.set()
                    completed = wait_record(target, "passed")
                    expect(answer_panel.get_by_text("模型回答测试通过", exact=True)).to_be_visible(timeout=10000)
                    fixture.require(len(probe["calls"]) == 1 and completed["request_id"] == running["request_id"], "refresh or retry duplicated inference")
                    checks["real_post_and_refresh_restore_same_single_request"] = True
                    checks["server_rejects_concurrent_new_request"] = True
                    page.screenshot(path=str(args.out_dir / "model-answer-passed.png"), full_page=True)
                    page.reload()
                    expect(select).to_be_visible(timeout=30000)
                    if select.input_value() != target["id"]:
                        select.select_option(target["id"])
                    expect(answer_panel.get_by_text("模型回答测试通过", exact=True)).to_be_visible(timeout=10000)
                    fixture.require(len(probe["calls"]) == 1, "completed refresh called model")
                    checks["completed_result_read_back_after_reload"] = True

                    # A lost POST reply must be recovered by GET, not another paid call.
                    before = len(probe["calls"])
                    def lose_reply(route):
                        route.fetch()
                        route.abort()
                    page.route("**/v1/model-inference-tests", lose_reply, times=1)
                    start.click()
                    expect(answer_panel.get_by_text("测试提交尚未确认，可能已有测试进行中。请先刷新状态；再次提交会复用本次标识。", exact=True)).to_be_visible()
                    refresh.click()
                    wait_record(target, "passed")
                    expect(answer_panel.get_by_text("模型回答测试通过", exact=True)).to_be_visible(timeout=10000)
                    fixture.require(len(probe["calls"]) == before + 1, "lost reply caused duplicate")
                    checks["lost_post_reply_recovers_without_resubmission"] = True

                    page.route("**/v1/model-inference-tests?*", lambda route: route.abort(), times=1)
                    refresh.click()
                    expect(answer_panel.get_by_text("暂时无法读取测试状态，请刷新状态；不会自动重新发送测试。", exact=True)).to_be_visible()
                    expect(start).to_be_disabled()
                    expect(answer_panel.get_by_text("模型回答测试通过", exact=True)).to_have_count(0)
                    refresh.click()
                    expect(answer_panel.get_by_text("模型回答测试通过", exact=True)).to_be_visible()
                    fixture.require(len(probe["calls"]) == before + 1, "read retry called model")
                    checks["read_failure_hides_success_and_refresh_recovers"] = True

                    for status, mode, expected, label in [
                        (401, "pass", "auth_failed", "认证未通过，请在原框架核对凭据"),
                        (429, "pass", "rate_limited", "服务限流，本次未自动重试"),
                        (503, "pass", "service_error", "服务返回异常，本次未自动重试"),
                        (200, "wrong", "response_mismatch", "模型已响应，但未通过测试内容或模型身份核对"),
                        (200, "disconnect", "uncertain", "未取得最终结果，服务可能已接收请求；本次未自动重试"),
                    ]:
                        probe["status"], probe["mode"] = status, mode
                        before = len(probe["calls"])
                        start_test()
                        wait_record(target, expected)
                        expect(answer_panel.get_by_text(label, exact=True)).to_be_visible(timeout=10000)
                        expect(answer_panel.get_by_text("模型回答测试通过", exact=True)).to_have_count(0)
                        fixture.require(len(probe["calls"]) == before + 1, "failure was retried")
                        checks[expected + "_visible_without_retry"] = True
                    probe["status"], probe["mode"] = 200, "pass"
                    gate.clear()
                    start_test()
                    config.write_text(text + "fixture_changed: true\n")
                    gate.set()
                    wait_record(target, "configuration_changed")
                    expect(answer_panel.get_by_text("配置或凭据已变化，本次结果已失效", exact=True)).to_be_visible(timeout=10000)
                    checks["inflight_configuration_drift_invalidates_result"] = True
                    before = len(probe["calls"])
                    with page.expect_response(lambda r: r.url.endswith("/v1/model-inference-tests") and r.request.method == "POST") as stale:
                        start.click()
                    fixture.require(stale.value.status == 409 and len(probe["calls"]) == before, "stale config called model")
                    checks["stale_selection_rejected_before_network"] = True
                    panel.get_by_role("button", name="重新发现模型", exact=True).click()
                    expect(select).to_be_visible()
                    select.select_option(target["id"])
                    expect(answer_panel.get_by_text("配置已变化，上次测试结果已失效", exact=True)).to_be_visible()
                    start_test()
                    wait_record(target, "passed")
                    expect(answer_panel.get_by_text("模型回答测试通过", exact=True)).to_be_visible(timeout=10000)
                    checks["rediscovery_allows_explicit_new_test"] = True
                    secret_file.unlink()
                    panel.get_by_role("button", name="重新发现模型", exact=True).click()
                    expect(select).to_be_visible()
                    select.select_option(target["id"])
                    expect(start).to_be_disabled()
                    checks["missing_credential_disables_inference"] = True

                    catalog = harness.api("/v1/model-connections")
                    claw_row = next(row for row in catalog["items"] if row["platform"] == "openclaw" and row["role"] == "primary")
                    select.select_option(claw_row["id"])
                    start_test()
                    wait_record(claw_row, "passed")
                    expect(answer_panel.get_by_text("模型回答测试通过", exact=True)).to_be_visible(timeout=10000)
                    checks["openclaw_selected_config_executes_inference"] = True
                    if args.step_config:
                        cloud = next(row for row in catalog["items"] if row["provider"] == "stepfun-step-plan")
                        select.select_option(cloud["id"])
                        start_test()
                        deadline = time.monotonic() + 65
                        while time.monotonic() < deadline:
                            observation = latest(cloud)
                            if observation and observation["status"] != "running":
                                cloud_status = observation["status"]
                                break
                            time.sleep(0.2)
                        fixture.require(cloud_status == "passed", "Step 5 fixed completion did not pass: " + str(cloud_status))
                        expect(answer_panel.get_by_text("模型回答测试通过", exact=True)).to_be_visible(timeout=10000)
                        checks["actual_step5_fixed_public_completion_passed"] = True
                        page.screenshot(path=str(args.out_dir / "step5-answer-passed.png"), full_page=True)
                    page.goto(harness.endpoint + "/bindings")
                    expect(select).to_be_visible(timeout=30000)
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.wait_for_function("document.querySelector('.sidebar').getBoundingClientRect().right <= 0")
                    select.select_option(claw_row["id"])
                    start_test()
                    wait_record(claw_row, "passed")
                    expect(answer_panel.get_by_text("模型回答测试通过", exact=True)).to_be_visible(timeout=10000)
                    checks["mobile_runtime_page_button_executes"] = start.evaluate("el => el.getBoundingClientRect().right <= innerWidth && el.getBoundingClientRect().left >= 0")
                    page.screenshot(path=str(args.out_dir / "model-answer-mobile.png"), full_page=True)
                    checks["no_browser_errors"] = not errors
                    browser.close()
                checks["all_synthetic_calls_use_exact_public_test"] = all(all(c.values()) for c in probe["calls"])
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
        gate.set()
        service.shutdown()
        service.server_close()
        worker.join(timeout=5)
    if args.step_config:
        checks["existing_openclaw_config_unchanged"] = (
            hashlib.sha256(args.step_config.read_bytes()).hexdigest() == source_hash
        )
    result = {
        "schema_version": "siq.model-inference-browser-proof/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "passed": failure is None and bool(checks) and all(checks.values()),
        "failure": failure,
        "checks": checks,
        "cloud_inference_status": cloud_status,
        "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "real UI and isolated daemon; synthetic authenticated chat completion failures/recovery plus optional actual Step 5 fixed public completion; no business data or native agent execution",
    }
    (args.out_dir / "result.sanitized.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
