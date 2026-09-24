"""Control console + actual signed Edge ingest/API; synthetic destination only.

The research resolver/body permission journey has its own browser evidence.
This check proves the console button, configured URL and no-referrer behavior.
"""

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    root = Path(__file__).resolve().parents[2]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}"
    checks, process = [], None
    report = dict(passed=False, synthetic_identity=True, destination_fixture=True, production_iam=False)
    try:
        with (
            tempfile.TemporaryDirectory(prefix="siq-navigation-console-") as raw,
            (out / "private.log").open("x") as log,
        ):
            temporary = Path(raw)
            env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "TZ"}}
            env.update(SIQ_AS_DEV="1", SIQ_AS_ALLOW_SQLITE="1", SIQ_AS_DATABASE_URL=f"sqlite:///{temporary}/api.db",
                SIQ_AS_SIGNING_KEY_FILE=str(temporary / "signing.seed"), SIQ_AS_ENFORCEMENT_BACKEND="fake",
                SIQ_AS_BUSINESS_WEB_ORIGINS=json.dumps({"dev-tenant": endpoint}),
                VITE_DEV_MODE="true", VITE_DEV_TENANT_ID="dev-tenant", VITE_DEV_USER_ID="fixture-operator")
            web = temporary / "web"
            subprocess.run(["npm", "run", "build", "--", "--outDir", str(web)], cwd=root / "apps/web", env=env,
                           stdout=log, stderr=log, check=True, timeout=60)
            bootstrap = temporary / "serve.py"
            bootstrap.write_text('''import sys, json
from pathlib import Path
sys.path.insert(0, ''' + repr(str(root / "apps/control-api")) + ''')
from fastapi.testclient import TestClient
from fastapi.responses import FileResponse, JSONResponse
from app.main import app
from app.tests.edge_helpers import candidate, create_scan_task, register_edge, signed_batch, signed_evidence
import uvicorn
headers = {"X-Dev-Tenant-Id":"dev-tenant","X-Dev-User-Id":"fixture-operator",
    "X-Dev-Roles":"tenant_admin,security_admin,agent_owner,platform_operator"}
event = "sev_" + "a" * 64
with TestClient(app) as client:
    env = client.post("/api/v1/environments", headers=headers, json={"name":"合成导航验收"}).json()["id"]
    edge, key = register_edge(client, headers, env, "navigation-browser")
    task = create_scan_task(client, headers, env)
    evidence = signed_evidence(key,"navigation-browser","ev:nav-browser",source_type="gateway",source_locator="siq://business-security-event/"+event)
    asset = candidate("合成分析助手", ["ev:nav-browser"], source_type="siq_hub")
    response = client.post("/edge/v1/batches", headers=edge,
        json=signed_batch(key,task,candidates=[asset],evidence=[evidence]))
    assert response.status_code == 200, response.status_code
    identity = next(a["id"] for a in client.get("/api/v1/candidates",headers=headers).json()
        if a["name"] == "合成分析助手")
@app.get("/__test__/asset")
def asset_info(): return {"id":identity,"event":event}
@app.get("/analysis/security-event")
def destination(): return JSONResponse({"synthetic_destination":True})
WEB = Path(''' + repr(str(web)) + ''')
@app.get("/{path:path}")
def serve(path: str):
    target = (WEB/path).resolve()
    if not target.is_relative_to(WEB) or not target.is_file(): target = WEB/"index.html"
    return FileResponse(target)
uvicorn.run(app,host="127.0.0.1",port=''' + str(port) + ''',log_level="error",access_log=False)
''')
            process = subprocess.Popen([str(root / "apps/control-api/.venv/bin/python"), str(bootstrap)],
                                       env=env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError("fixture_exited")
                    try:
                        with urllib.request.urlopen(endpoint + "/__test__/asset", timeout=1) as response:
                            asset = json.load(response)
                        break
                    except OSError:
                        time.sleep(.1)
                else:
                    raise RuntimeError("fixture_not_ready")
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width":1280,"height":1000},
                                            locale="zh-CN", reduced_motion="reduce")
                    page.goto(endpoint + "/agents/" + asset["id"])
                    link = page.get_by_role("link", name="查看业务运行结果", exact=True)
                    expect(link).to_have_attribute(
                        "href", endpoint + "/analysis/security-event?event_id=" + asset["event"])
                    expect(page.get_by_text("需使用有数据访问权限的业务账号登录。", exact=False)).to_be_visible()
                    checks.append("signed_ingest_real_api_asset_navigation")
                    page.screenshot(path=str(out / "console-desktop.png"), full_page=True)
                    with page.expect_popup() as opened:
                        link.click()
                    popup = opened.value
                    popup.wait_for_load_state()
                    assert popup.url == endpoint + "/analysis/security-event?event_id=" + asset["event"]
                    assert popup.evaluate("document.referrer") == "" and popup.evaluate("window.opener === null")
                    checks.append("button_opens_exact_destination_no_referrer_or_opener")
                    popup.close()
                    page.set_viewport_size({"width":375,"height":800})
                    page.locator(".sidebar").wait_for(state="hidden")
                    link.scroll_into_view_if_needed()
                    box = link.bounding_box()
                    assert box and box["x"] >= 0 and box["x"] + box["width"] <= 375
                    page.screenshot(path=str(out / "console-mobile.png"), full_page=True)
                    expect(link).to_be_visible()
                    checks.append("mobile_navigation_button_visible")
                    browser.close()
                report["passed"] = True
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
    except Exception as error:
        report["failure_type"] = type(error).__name__
    finally:
        report["checks"] = checks
        report["owned_process_stopped"] = process is None or process.poll() is not None
        (out / "report.sanitized.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
