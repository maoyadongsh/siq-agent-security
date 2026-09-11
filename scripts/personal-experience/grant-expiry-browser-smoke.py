#!/usr/bin/env python3
"""Verify pending Grant lifetime editing in a real isolated daemon and Chromium."""

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    outcomes = {}
    with tempfile.TemporaryDirectory(prefix="siq-grant-expiry-") as temporary:
        root = Path(temporary)
        home = root / "home"
        home.mkdir(mode=0o700)
        skill = root / "fixture-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: expiry-fixture\ndescription: Synthetic fixture.\n"
            "allowed-tools: read_file\n---\nRead a synthetic report.\n"
        )
        env = {
            **os.environ,
            "HOME": str(home),
            "USERPROFILE": str(home),
            "LOCALAPPDATA": str(home / "AppData/Local"),
            "HERMES_HOME": str(home / ".hermes"),
            "SIQ_AGENT_SECURITY_STATE_DIR": str(root / "state"),
            "AGENTSHIELD_STATE_DIR": str(root / "state"),
        }
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        endpoint = f"http://127.0.0.1:{port}"

        def cli(command):
            return subprocess.run(
                [str(binary), command, "--port", str(port)],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        process = subprocess.Popen(
            [str(binary), "serve", "--port", str(port)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("isolated daemon exited")
                if cli("status").returncode == 0:
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("isolated daemon unavailable")
            pairing = cli("pair")
            match = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing.stdout)
            if pairing.returncode or not match:
                raise RuntimeError("pairing failed")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda _: errors.append("pageerror"))
                page.goto(endpoint + "/grants")
                page.get_by_label("配对码", exact=True).fill(match.group())
                with page.expect_response(lambda r: r.url.endswith("/v1/pair") and r.status == 200) as paired:
                    page.get_by_role("button", name="建立管理会话", exact=True).click()
                credential = paired.value.json()["session"]

                def api(method, path, body=None, expected=200):
                    response = context.request.fetch(
                        endpoint + path, method=method, data=body, headers={"Authorization": "Bearer " + credential}
                    )
                    if response.status != expected:
                        raise RuntimeError("fixture API status mismatch")
                    return response.json()

                admitted = api("POST", "/v1/admit", {"path": str(skill)})
                created = api(
                    "POST",
                    "/v1/grants",
                    {
                        "admission_id": admitted["admission"]["admission_id"],
                        "platform": "hermes",
                        "subject_id": "expiry-browser-fixture",
                    },
                )
                gid = created["grant"]["grant_id"]
                route = "/v1/grants/" + gid

                def select():
                    page.reload()
                    page.get_by_role("row").filter(has_text=gid).click()
                    expect(page.get_by_label("授权期限（从保存时开始）")).to_be_visible()

                def save(duration):
                    page.get_by_label("授权期限（从保存时开始）").select_option(duration)
                    with page.expect_response(lambda r: r.url.endswith(route + "/expiry") and r.status == 200):
                        page.get_by_role("button", name="保存期限", exact=True).click()
                    expect(page.get_by_text("授权期限已保存，请检查权限后人工批准。", exact=True)).to_be_visible()
                    return api("GET", route)

                select()
                page.get_by_label("批准人（人工 actor_id）").fill("fixture-operator")
                saved = save("600")
                deadline = datetime.fromisoformat(saved["grant"]["expires_at"])
                outcomes["server_deadline_saved_before_approval"] = (
                    590 < (deadline - datetime.now(UTC)).total_seconds() <= 600
                    and saved["grant"]["status"] == "pending_approval"
                )
                outcomes["explicit_unlimited_saved"] = save("unlimited")["grant"]["expires_at"] is None
                current = api("GET", route)
                external = api(
                    "POST",
                    route + "/expiry",
                    {
                        "schema_version": "grant-expiry-edit/v1",
                        "expected_revision": current["state_revision"],
                        "actor_id": "fixture-operator",
                        "duration_seconds": 900,
                    },
                )
                with page.expect_response(lambda r: r.url.endswith(route + "/expiry") and r.status == 409):
                    page.get_by_role("button", name="保存期限", exact=True).click()
                expect(page.get_by_role("alert")).to_be_visible()
                outcomes["stale_editor_cannot_replace_deadline"] = (
                    api("GET", route)["grant"]["expires_at"] == external["grant"]["expires_at"]
                )
                select()
                saved = save("3600")
                page.screenshot(path=str(args.out_dir / "grant-expiry.png"), full_page=True)
                with page.expect_response(lambda r: r.url.endswith(route + "/approve") and r.status == 200):
                    page.get_by_role("button", name="批准", exact=True).click()
                expect(page.get_by_label("授权期限（从保存时开始）")).to_have_count(0)
                approved = api("GET", route)
                outcomes["human_approval_preserves_deadline"] = (
                    approved["grant"]["status"] == "approved"
                    and approved["grant"]["expires_at"] == saved["grant"]["expires_at"]
                )
                api(
                    "POST",
                    route + "/expiry",
                    {
                        "schema_version": "grant-expiry-edit/v1",
                        "expected_revision": approved["state_revision"],
                        "actor_id": "fixture-operator",
                        "duration_seconds": None,
                    },
                    expected=400,
                )
                outcomes["approved_deadline_cannot_be_extended"] = True
                with page.expect_response(lambda r: r.url.endswith(route + "/deploy") and r.status == 200):
                    page.get_by_role("button", name="标记已部署", exact=True).click()
                outcomes["deployment_does_not_claim_effective"] = api("GET", route)["grant"]["status"] == "deployed"
                page.set_viewport_size({"width": 390, "height": 844})
                sidebar = page.get_by_role("complementary", name="siq-agent-security 本地导航")
                expect(sidebar).not_to_be_in_viewport()
                page.get_by_role("button", name="打开导航", exact=True).click()
                expect(sidebar).to_be_in_viewport()
                page.get_by_role("button", name="关闭导航", exact=True).click(position={"x": 380, "y": 400})
                expect(sidebar).not_to_be_in_viewport()
                outcomes["mobile_navigation_opens_and_closes"] = True
                outcomes["mobile_main_content_not_clipped"] = page.locator("main.content").evaluate(
                    "element => element.scrollWidth <= element.clientWidth"
                )
                page.get_by_role("heading", level=2).filter(has_text=gid).scroll_into_view_if_needed()
                outcomes["mobile_no_page_overflow"] = page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                )
                page.screenshot(
                    path=str(args.out_dir / "grant-expiry-mobile.png"), full_page=True, animations="disabled"
                )
                outcomes["no_page_errors"] = not errors
                browser.close()
        finally:
            process.terminate()
            process.wait(timeout=15)
    report = {
        "schema_version": "grant-expiry-browser-smoke/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "isolated daemon and Chromium; synthetic pending grant, no real platform execution",
        "checks": outcomes,
        "passed": bool(outcomes) and all(outcomes.values()),
    }
    (args.out_dir / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if not report["passed"]:
        raise RuntimeError("browser checks failed; see redacted evidence")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
