"""Real UI + signed backend batch revocation using disposable state, never live grants."""
import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=False)
    checks = {}
    with tempfile.TemporaryDirectory(prefix="siq-console-smoke-") as temporary:
        root = Path(temporary)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("SIQ_", "AGENTSHIELD_")) and "proxy" not in k.lower()}
        env["SIQ_AGENT_SECURITY_STATE_DIR"] = str(root / "state")
        # Even incidental home-based discovery must stay inside synthetic data.
        env["HOME"] = str(root / "home")
        Path(env["HOME"]).mkdir()
        env["XDG_CONFIG_HOME"] = str(root / "home" / ".config")
        env["XDG_DATA_HOME"] = str(root / "home" / ".local" / "share")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with (root / "private.log").open("wb") as log:
            process = subprocess.Popen([str(binary), "start", "--port", str(port)], env=env,
                                       stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("isolated service exited")
                    try:
                        with opener.open(url + "/healthz", timeout=1) as response:
                            if json.load(response)["status"] == "ready":
                                break
                    except (OSError, ValueError):
                        time.sleep(0.1)
                else:
                    raise RuntimeError("isolated service not ready")
                paired = subprocess.run([str(binary), "pair", "--port", str(port)], env=env,
                                        capture_output=True, timeout=15, check=True)
                code = re.search(rb"[a-f0-9]{4}(?:-[a-f0-9]{4}){3}", paired.stdout).group().decode()
                with sync_playwright() as driver:
                    browser = driver.chromium.launch(headless=True, env=env,
                        proxy={"server": "direct://", "bypass": "*"},
                        args=["--disable-gpu", "--disable-dev-shm-usage"])
                    context = browser.new_context(viewport={"width": 1440, "height": 1000},
                        proxy={"server": "direct://", "bypass": "*"}, reduced_motion="reduce",
                        service_workers="block")
                    violations = []

                    def only_isolated_service(route):
                        if not route.request.url.startswith(url + "/"):
                            violations.append("non-isolated request blocked")
                            route.abort()
                        else:
                            route.continue_()

                    context.route("**/*", only_isolated_service)
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(type(error).__name__))
                    page.goto(url + "/overview", wait_until="domcontentloaded")
                    page.get_by_text("手动配对 / 旧版本连接", exact=True).click()
                    page.get_by_label("配对码", exact=True).fill(code)
                    with page.expect_response(lambda r: r.url.endswith("/v1/pair") and r.status == 200) as pairing:
                        page.get_by_role("button", name="建立管理会话", exact=True).click()
                    admin = pairing.value.json()["session"]
                    expect(page.get_by_role("heading", name="我的智能体", exact=True)).to_be_visible()
                    expect(page.locator("nav .nav-group").first.get_by_role("link")).to_have_count(4)
                    checks["four_entries_and_legacy_overview_redirect"] = True

                    def api(path, body=None):
                        data = json.dumps(body).encode() if body is not None else None
                        request = urllib.request.Request(url + path, data=data, headers={
                            "Authorization": "Bearer " + admin, "Content-Type": "application/json"})
                        with opener.open(request, timeout=15) as response:
                            return json.load(response)

                    admitted = api("/v1/admit", {"path": str(ROOT / "apps/agentshield/internal/admission/testdata/skills/benign/official-like")})
                    ids = []
                    for role in ("console-smoke-role-a", "console-smoke-role-b"):
                        created = api("/v1/grants", {"admission_id": admitted["admission"]["admission_id"],
                                                   "platform": "hermes", "subject_id": role})
                        ids.append(created["grant"]["grant_id"])
                    page.get_by_role("link", name="权限管理", exact=True).click()
                    expect(page.get_by_role("heading", name="权限管理", exact=True)).to_be_visible()
                    page.get_by_label("选择当前筛选的所有可撤权项", exact=True).check()
                    page.get_by_placeholder("角色、Skill 或授权标识").fill("role-a")
                    expect(page.get_by_text("已选 2 项（其中 1 项在筛选外）", exact=False)).to_be_visible()
                    page.get_by_role("button", name="预览批量撤权", exact=True).click()
                    expect(page.get_by_role("heading", name="确认撤销 2 项授权", exact=True)).to_be_visible()
                    expect(page.get_by_role("button", name="确认执行撤权", exact=True)).to_be_disabled()
                    assert all(g["status"] == "pending_approval" for g in api("/v1/grants")["grants"])
                    page.get_by_role("button", name="取消", exact=True).click()
                    assert all(g["status"] == "pending_approval" for g in api("/v1/grants")["grants"])
                    checks["explicit_preview_hidden_selection_and_cancel_no_mutation"] = True
                    page.get_by_role("button", name="预览批量撤权", exact=True).click()
                    expect(page.get_by_role("heading", name="确认撤销 2 项授权", exact=True)).to_be_visible()
                    page.screenshot(path=str(args.out_dir / "batch-preview-desktop.png"), full_page=True)
                    for width, height in ((375, 812), (812, 375)):
                        page.set_viewport_size({"width": width, "height": height})
                        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "page overflow"
                        expect(page.get_by_role("button", name="确认执行撤权", exact=True)).to_be_visible()
                    page.screenshot(path=str(args.out_dir / "batch-preview-small.png"), full_page=True)
                    checks["small_portrait_landscape_and_reduced_motion"] = True
                    page.set_viewport_size({"width": 1440, "height": 1000})
                    page.get_by_label("我已核对完整对象及共享影响，确认撤权", exact=True).check()
                    with page.expect_response(lambda r: r.url.endswith("/v1/grant-batches/apply")) as applied:
                        page.get_by_role("button", name="确认执行撤权", exact=True).click()
                    outcome = applied.value.json()
                    expect(page.get_by_role("heading", name="批量操作结果", exact=True)).to_be_visible()
                    assert {item["grant_id"] for item in outcome["items"]} == set(ids)
                    assert all(item["status"] == "revoked" for item in outcome["items"])
                    assert all(g["status"] == "revoked" for g in api("/v1/grants")["grants"])
                    audits = [event for event in api("/v1/audit")["events"] if event["event"] == "grant_revoke"]
                    assert len(audits) == 2 and all(e["note"] == "batch=" + outcome["batch_id"] for e in audits)
                    checks["real_signed_batch_revocation_and_transactional_audit"] = True
                    # Save only versioned, non-secret protocol documents for Python schema validation.
                    request = json.loads(applied.value.request.post_data)
                    (args.out_dir / "batch-contract-output.json").write_text(json.dumps([request["plan"], request, outcome], indent=2) + "\n")
                    page.screenshot(path=str(args.out_dir / "batch-result-desktop.png"), full_page=True)
                    page.get_by_role("link", name="查看此批次操作审计", exact=True).click()
                    expect(page.get_by_placeholder("gb-…（留空显示最近记录）")).to_have_value(outcome["batch_id"])
                    audit_card = page.locator('.card').filter(has=page.get_by_role('heading', name='操作审计', exact=True))
                    expect(audit_card.locator('tbody tr')).to_have_count(2)
                    checks["batch_audit_deep_link_and_filter"] = True
                    for path, heading in (("/findings", "安全中心"), ("/activities", "运行审计"),
                                          ("/grants", "签发")):
                        page.goto(url + path, wait_until="domcontentloaded")
                        expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                        if path != "/grants":
                            expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
                    assert not errors
                    assert not violations
                    checks["legacy_grant_route_and_no_javascript_errors"] = True
                    browser.close()
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
    report = {"schema_version": "personal-console-smoke/v1", "checks": checks,
              "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
              "scope": "isolated Linux ARM64 + Chromium, synthetic grants; not native host execution or signed release"}
    (args.out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "checks": len(checks)}))


if __name__ == "__main__":
    main()
