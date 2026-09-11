#!/usr/bin/env python3
"""Exercise the runtime-check UI with Chromium, a real daemon and isolated Hermes."""

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("native_fixture", REPO / "scripts/validate-intent-v2-hermes.py")
fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--hermes-cli", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    args.binary, args.hermes_cli = args.binary.resolve(), args.hermes_cli.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.installer_managed_profile = True
    checks = {}
    with tempfile.TemporaryDirectory(prefix="siq-runtime-browser-") as temporary:
        harness = fixture.Harness(Path(temporary), args)
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            harness.install_profile()
            pairing = subprocess.run(
                [str(harness.binary), "pair", "--port", str(urlparse(harness.endpoint).port)],
                env=harness.env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            match = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing.stdout)
            fixture.require(pairing.returncode == 0 and match, "browser pairing unavailable")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda _: errors.append("pageerror"))
                page.goto(harness.endpoint + "/settings")
                page.get_by_label("配对码", exact=True).fill(match.group())
                with page.expect_response(lambda r: r.url.endswith("/v1/pair") and r.status == 200) as paired:
                    page.get_by_role("button", name="建立管理会话", exact=True).click()
                credential = paired.value.json()["session"]
                page.get_by_role("button", name="运行自检", exact=True).click()
                dialog = page.get_by_role("dialog")
                start = dialog.get_by_role("button", name="确认并开始自检", exact=True)
                expect(dialog.get_by_text("将执行的检查", exact=True)).to_be_visible(timeout=20000)
                expect(dialog.get_by_label("自检实例 / profile")).to_have_value(
                    next(i for i in harness.api("/v1/adapter/instances?platform=hermes")["instances"] if i["active"])[
                        "instance_id"
                    ]
                )
                fixture.require(not harness.api("/v1/grants")["grants"], "opening preview created grant")
                checks["active_instance_selected_without_authority"] = True
                dialog.get_by_label("确认人", exact=True).fill("synthetic-browser-operator")
                expect(start).to_be_enabled()
                start.click()
                expect(dialog.get_by_role("button", name="取消自检", exact=True)).to_be_visible()
                # Closing the view must preserve the in-flight job. Reopening
                # retrieves it from the server without starting another host.
                dialog.get_by_role("button", name="关闭（后台继续）", exact=True).click()
                page.get_by_role("button", name="运行自检", exact=True).click()
                expect(dialog.get_by_text("本次自检通过", exact=True)).to_be_visible(timeout=140000)
                expect(dialog.get_by_text("临时权限与材料：已撤权并清理", exact=True)).to_be_visible()
                checks["confirmed_native_check_survives_closed_view"] = True
                checks["cleanup_and_five_receipts_visible"] = dialog.get_by_text(
                    "本次关联 5 条回执，可在回执页追溯。", exact=True
                ).is_visible()
                checks["all_probe_evidence_visible"] = dialog.locator(".card li").count() == 5
                fixture.require(len(harness.api("/v1/grants")["grants"]) == 1, "reopening launched duplicate host")
                checks["reopening_does_not_duplicate_launch"] = True
                page.screenshot(path=str(args.out_dir / "runtime-check-passed.png"), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                checks["mobile_dialog_content_fits"] = dialog.evaluate(
                    "el => el.scrollWidth <= el.clientWidth + 1 && "
                    "el.getBoundingClientRect().right <= window.innerWidth"
                )
                page.screenshot(path=str(args.out_dir / "runtime-check-mobile.png"), full_page=True)
                start.scroll_into_view_if_needed()
                checks["mobile_confirmation_reachable"] = start.evaluate(
                    "el => { const r = el.getBoundingClientRect(); return r.top >= 0 && r.left >= 0 && "
                    "r.bottom <= window.innerHeight && r.right <= window.innerWidth && "
                    "el.contains(document.elementFromPoint(r.x + r.width/2, r.y + r.height/2)); }"
                )
                page.screenshot(path=str(args.out_dir / "runtime-check-mobile-actions.png"), full_page=True)
                start.focus()
                page.keyboard.press("Tab")
                checks["keyboard_focus_stays_in_dialog"] = dialog.evaluate("el => el.contains(document.activeElement)")
                page.set_viewport_size({"width": 1440, "height": 1000})
                config = Path(harness.env["HERMES_HOME"]) / "config.yaml"
                before = config.read_bytes()
                config.write_bytes(before + b"\n# fixture configuration drift\n")
                dialog.get_by_role("button", name="重新预览", exact=True).click()
                expect(dialog.get_by_text("自检结果已失效", exact=True)).to_be_visible(timeout=20000)
                checks["configuration_drift_invalidates_display"] = True

                # An externally edited configuration must be reconciled before
                # another launch. Restore this owned fixture, without silently
                # changing configuration in the product or reviving old evidence.
                expect(start).to_be_disabled()
                checks["unreconciled_configuration_blocks_launch"] = True
                config.write_bytes(before)
                dialog.get_by_role("button", name="重新预览", exact=True).click()
                expect(dialog.get_by_text("自检结果已失效", exact=True)).to_be_visible(timeout=20000)
                expect(start).to_be_enabled()
                start.click()
                dialog.get_by_role("button", name="取消自检", exact=True).click()
                expect(dialog.get_by_text("自检已取消", exact=True)).to_be_visible(timeout=20000)
                expect(dialog.get_by_text("临时权限与材料：已撤权并清理", exact=True)).to_be_visible()
                checks["cancel_revokes_and_cleans"] = all(
                    g["status"] == "revoked" for g in harness.api("/v1/grants")["grants"]
                )
                checks["no_page_errors"] = not errors
                checks["no_credentials_in_web_storage"] = page.evaluate(
                    "token => !JSON.stringify([Object.entries(localStorage), "
                    "Object.entries(sessionStorage)]).includes(token)",
                    credential,
                )
                browser.close()
        finally:
            harness.stop()
    fixture.require(all(checks.values()), "browser checks failed: " + ", ".join(k for k, v in checks.items() if not v))
    result = {
        "schema_version": "product-runtime-check-browser-smoke/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "passed": True,
        "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "checks": checks,
        "scope": "Linux Chromium, product UI/API, real public Hermes CLI, isolated profile and synthetic operator",
    }
    (args.out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
