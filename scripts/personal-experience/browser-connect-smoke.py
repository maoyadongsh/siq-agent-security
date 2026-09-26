#!/usr/bin/env python3
"""Isolated real-browser connection/24-hour session checks; never touch installed services."""

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=False)
    checks = {}
    with tempfile.TemporaryDirectory(prefix="siq-browser-connect-") as temporary:
        root = Path(temporary)
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("SIQ_", "AGENTSHIELD_")) and "proxy" not in k.lower()
        }
        env["SIQ_AGENT_SECURITY_STATE_DIR"] = str(root / "state")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        process = None
        with (root / "private.log").open("wb") as log:

            def start():
                child = subprocess.Popen([str(binary), "start", "--port", str(port)], env=env, stdout=log, stderr=log)
                for _ in range(100):
                    if child.poll() is not None:
                        raise RuntimeError("isolated daemon exited")
                    try:
                        with opener.open(url + "/healthz", timeout=1) as response:
                            if json.load(response)["status"] == "ready":
                                return child
                    except (OSError, ValueError):
                        time.sleep(0.1)
                child.terminate()
                child.wait(timeout=10)
                raise RuntimeError("isolated daemon not ready")

            def cli(*command):
                return subprocess.run(
                    [str(binary), *command, "--port", str(port)], env=env, capture_output=True, timeout=15, check=False
                )

            try:
                process = start()
                with sync_playwright() as driver:
                    browser = driver.chromium.launch(
                        headless=True,
                        proxy={"server": "direct://", "bypass": "*"},
                        env=env,
                        args=["--disable-gpu", "--disable-dev-shm-usage"],
                    )
                    context = browser.new_context(
                        viewport={"width": 1280, "height": 900}, proxy={"server": "direct://", "bypass": "*"}
                    )
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(type(error).__name__))
                    page.goto(url + "/overview", wait_until="domcontentloaded")
                    expect(page.get_by_role("button", name="通过智能体连接", exact=True)).to_be_visible()
                    page.screenshot(path=str(args.out_dir / "connect-desktop.png"))
                    page.set_viewport_size({"width": 375, "height": 812})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(path=str(args.out_dir / "connect-mobile.png"))
                    checks["desktop_and_mobile_entry"] = True
                    page.get_by_role("button", name="通过智能体连接", exact=True).click()
                    prompt = page.get_by_label("发送给智能体的连接请求")
                    expect(prompt).to_be_visible()
                    request_id = re.search(r"[a-f0-9]{32}", prompt.input_value()).group()
                    proof = next(c for c in context.cookies() if c["name"].startswith("siq_connect_"))
                    assert (
                        proof["httpOnly"]
                        and proof["sameSite"] == "Strict"
                        and proof["value"] not in prompt.input_value()
                    )
                    stranger = browser.new_context(proxy={"server": "direct://", "bypass": "*"})
                    stranger_page = stranger.new_page()
                    stranger_page.goto(url + "/overview", wait_until="domcontentloaded")
                    assert (
                        stranger_page.evaluate(
                            """async id => (await fetch('/v1/session/connect/poll', {
                      method: 'POST', headers: {'X-SIQ-Session': '1', 'Content-Type': 'application/json'},
                      body: JSON.stringify({request_id: id})
                    })).status""",
                            request_id,
                        )
                        == 401
                    )
                    stranger.close()
                    checks["other_browser_cannot_claim"] = True
                    page.get_by_role("button", name="取消连接", exact=True).click()
                    expect(page.get_by_role("button", name="通过智能体连接", exact=True)).to_be_enabled()
                    assert cli("connect", "--request", request_id, "--confirm-connect").returncode != 0
                    checks["cancelled_request_cannot_be_approved"] = True
                    page.get_by_role("button", name="通过智能体连接", exact=True).click()
                    expect(prompt).to_be_visible()
                    request_id = re.search(r"[a-f0-9]{32}", prompt.input_value()).group()
                    assert cli("connect", "--request", request_id).returncode != 0
                    confirmed = cli("connect", "--request", request_id, "--confirm-connect")
                    assert confirmed.returncode == 0
                    assert not re.search(rb"[a-f0-9]{64}", confirmed.stdout + confirmed.stderr)
                    expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible(timeout=15000)
                    checks["explicit_cli_confirmation_auto_connects"] = True
                    cookie = next(c for c in context.cookies() if c["name"].startswith("siq_session_"))
                    assert 86300 < cookie["expires"] - time.time() <= 86400
                    page.reload(wait_until="domcontentloaded")
                    expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                    restored = next(c for c in context.cookies() if c["name"] == cookie["name"])
                    assert restored["expires"] == cookie["expires"]
                    checks["fixed_24h_cookie_and_reload_recovery"] = True
                    page.get_by_role("button", name="退出管理", exact=True).click()
                    expect(page.get_by_role("button", name="通过智能体连接", exact=True)).to_be_visible()
                    checks["logout_invalidates_session"] = True
                    # Manual fallback remains usable; code stays only in private memory.
                    paired = cli("pair")
                    assert paired.returncode == 0
                    code = re.search(rb"[a-f0-9]{4}(?:-[a-f0-9]{4}){3}", paired.stdout).group().decode()
                    page.get_by_text("手动配对 / 旧版本连接", exact=True).click()
                    page.get_by_label("配对码", exact=True).fill(code)
                    page.get_by_role("button", name="建立管理会话", exact=True).click()
                    expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                    checks["manual_pairing_fallback"] = True
                    process.terminate()
                    process.wait(timeout=15)
                    process = start()
                    page.reload(wait_until="domcontentloaded")
                    expect(page.get_by_role("button", name="通过智能体连接", exact=True)).to_be_visible()
                    checks["restart_requires_reconnection"] = True
                    assert not errors
                    checks["no_browser_javascript_errors"] = True
                    browser.close()
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                    process.wait(timeout=15)
    report = {
        "schema_version": "siq-browser-connect-smoke/v1",
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "checks": checks,
        "scope": "isolated Linux ARM64 daemon and Chromium; not a signed installation or live agent acceptance",
    }
    with (args.out_dir / "report.json").open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"passed": True, "checks": len(checks)}))


if __name__ == "__main__":
    main()
