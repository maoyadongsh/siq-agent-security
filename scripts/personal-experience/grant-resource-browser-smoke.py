#!/usr/bin/env python3
"""Verify pending Grant resource editing in a real isolated daemon and Chromium."""

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
    with tempfile.TemporaryDirectory(prefix="siq-grant-resources-") as temporary:
        root = Path(temporary)
        home = root / "home"
        home.mkdir(mode=0o700)
        skill = root / "fixture-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: resource-fixture\ndescription: Synthetic fixture.\n"
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
                        "subject_id": "resource-browser-fixture",
                    },
                )
                gid = created["grant"]["grant_id"]
                route = "/v1/grants/" + gid

                initial = api(
                    "POST",
                    route + "/resources",
                    {
                        "schema_version": "grant-resource-edit/v1",
                        "expected_revision": created["state_revision"],
                        "actor_id": "fixture-operator",
                        "tools": ["read_file", "write_file", "web_fetch"],
                        "filesystem": {
                            "read_only": ["/work/reports with spaces,commas"],
                            "read_write": ["/work/output"],
                        },
                        "network": [
                            {"endpoint": "api.example.test:443", "effect": "allow"},
                            {"endpoint": "private.example.test:443", "effect": "deny"},
                        ],
                        "models": [],
                    },
                )
                api(
                    "POST",
                    route + "/require-approval",
                    {
                        "schema_version": "grant-tool-approval/v1",
                        "expected_revision": initial["state_revision"],
                        "actor_id": "fixture-operator",
                        "tools": ["read_file"],
                    },
                )

                def select():
                    page.reload()
                    page.get_by_role("row").filter(has_text=gid).click()
                    expect(page.get_by_role("button", name="编辑权限范围", exact=True)).to_be_enabled()

                def open_editor():
                    page.get_by_role("button", name="编辑权限范围", exact=True).click()
                    dialog = page.get_by_role("dialog", name="编辑权限范围", exact=True)
                    expect(dialog.get_by_label("只读目录", exact=True)).to_be_enabled()
                    return dialog

                def save(dialog, expected=200):
                    with page.expect_response(lambda r: r.url.endswith(route + "/resources") and r.status == expected):
                        dialog.get_by_role("button", name="保存待批准权限", exact=True).click()
                    if expected == 200:
                        expect(dialog).to_have_count(0)
                    return api("GET", route)

                select()
                dialog = open_editor()
                expect(dialog.get_by_label("只读目录", exact=True)).to_have_value("/work/reports with spaces,commas")
                expect(dialog.get_by_label("读写目录", exact=True)).to_have_value("/work/output")
                expect(dialog.get_by_label("拒绝的网络端点", exact=True)).to_have_value("private.example.test:443")
                outcomes["existing_resource_lists_prefilled"] = True
                actor = dialog.get_by_label("本次修改人", exact=True)
                actor.fill("")
                actor.press_sequentially("fixture-operator", delay=10)
                expect(actor).to_have_value("fixture-operator")
                expect(actor).to_be_focused()
                outcomes["typing_actor_preserves_focus"] = True
                dialog.get_by_text(re.compile("保留的限制与批准条件")).click()
                expect(dialog.get_by_text("tool · read_file · 保留该工具时仍需人工确认", exact=True)).to_be_visible()
                outcomes["per_use_approval_condition_visible"] = True
                before = api("GET", route)
                dialog.get_by_label("读写目录", exact=True).fill("/work/cancelled")
                dialog.get_by_role("button", name="取消", exact=True).click()
                outcomes["cancel_does_not_write"] = api("GET", route) == before
                dialog = open_editor()
                dialog.get_by_role("button", name="目录全部改为只读", exact=True).click()
                expect(dialog.get_by_label("读写目录", exact=True)).to_have_value("")
                expect(dialog.get_by_label("只读目录", exact=True)).to_have_value(
                    "/work/reports with spaces,commas\n/work/output"
                )
                saved = save(dialog)
                facts = saved["grant"]["facts"]
                outcomes["readonly_template_saved_pending"] = (
                    saved["grant"]["status"] == "pending_approval"
                    and not any(f["domain"] == "filesystem" and f["action"] == "fs.write" for f in facts)
                    and any(f["resource"]["value"] == "/work/reports with spaces,commas" for f in facts)
                    and any(
                        f["resource"]["value"] == "read_file" and f.get("conditions", {}).get("require_approval")
                        for f in facts
                    )
                )
                dialog = open_editor()
                dialog.get_by_label("读写目录", exact=True).fill("/work/my unsaved,draft")
                external = api(
                    "POST",
                    route + "/expiry",
                    {
                        "schema_version": "grant-expiry-edit/v1",
                        "expected_revision": saved["state_revision"],
                        "actor_id": "external-fixture-operator",
                        "duration_seconds": 600,
                    },
                )
                save(dialog, 409)
                expect(dialog.get_by_label("读写目录", exact=True)).to_have_value("/work/my unsaved,draft")
                expect(dialog.get_by_role("alert")).to_contain_text("你的输入仍保留")
                outcomes["stale_edit_preserves_input_and_external_change"] = api("GET", route) == external
                with page.expect_response(lambda r: r.url.endswith(route) and r.request.method == "GET"):
                    dialog.get_by_role("button", name="重新读取", exact=True).click()
                expect(dialog.get_by_label("读写目录", exact=True)).to_have_value("")
                outcomes["explicit_reload_reads_current_scope"] = True
                page.route("**" + route, lambda request: request.abort())
                dialog.get_by_role("button", name="重新读取", exact=True).click()
                expect(dialog.get_by_role("alert")).to_contain_text("无法读取当前权限")
                expect(dialog.get_by_role("button", name="保存待批准权限", exact=True)).to_be_disabled()
                outcomes["failed_reload_disables_save"] = True
                page.unroute("**" + route)
                dialog.get_by_role("button", name="重新读取", exact=True).click()
                expect(dialog.get_by_label("只读目录", exact=True)).to_be_enabled()
                dialog.get_by_label("读写目录", exact=True).fill("/work/final output,review")
                page.screenshot(path=str(args.out_dir / "grant-resources.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                outcomes["mobile_no_page_overflow"] = page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                )
                for name in ["取消", "重新读取", "保存待批准权限"]:
                    expect(dialog.get_by_role("button", name=name, exact=True)).to_be_in_viewport()
                outcomes["mobile_actions_visible"] = True
                page.screenshot(path=str(args.out_dir / "grant-resources-mobile.png"), full_page=True)
                saved = save(dialog)
                outcomes["save_preserves_external_expiry"] = (
                    saved["grant"]["expires_at"] == external["grant"]["expires_at"]
                )
                dialog = open_editor()
                dialog.get_by_role("button", name="清空允许范围", exact=True).click()
                expect(dialog.get_by_label("拒绝的网络端点", exact=True)).to_have_value("private.example.test:443")
                cleared = save(dialog)
                outcomes["clear_removes_all_editable_allows_preserves_network_deny"] = not any(
                    f["effect"] == "allow" and f["domain"] in ["tool", "filesystem", "network", "model"]
                    for f in cleared["grant"]["facts"]
                ) and any(f["domain"] == "network" and f["effect"] == "deny" for f in cleared["grant"]["facts"])
                with page.expect_response(lambda r: r.url.endswith(route + "/approve") and r.status == 200):
                    page.get_by_role("button", name="批准", exact=True).click()
                expect(page.get_by_role("button", name="编辑权限范围", exact=True)).to_be_disabled()
                outcomes["approved_grant_not_editable"] = api("GET", route)["grant"]["status"] == "approved"
                outcomes["no_page_errors"] = not errors
                browser.close()
        finally:
            process.terminate()
            process.wait(timeout=15)
    report = {
        "schema_version": "grant-resource-browser-smoke/v1",
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
