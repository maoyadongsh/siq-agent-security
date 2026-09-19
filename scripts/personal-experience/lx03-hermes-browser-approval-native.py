#!/usr/bin/env python3
"""Exercise real Hermes CLI approval retries through the embedded SIQ browser UI.

The model, reviewer and file target are isolated fixtures. This reuses the
native approval harness and changes only its confirmation resolution channel.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "scripts/personal-experience/hermes-approval-gap-native-smoke.py"


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_module():
    spec = importlib.util.spec_from_file_location("lx03_hermes_approval", BASE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-cli", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.hermes_cli = args.hermes_cli.resolve(strict=True)
    args.binary = args.binary.resolve(strict=True)
    require(args.out.parent.name.endswith("-private"), "output_must_be_private")
    require(not args.out.exists(), "refusing_to_overwrite_evidence")
    args.race_mode = "threads"
    native = native_module()

    class BrowserHarness(native.Harness):
        def __init__(self, root, options):
            super().__init__(root, options)
            self.browser_actions: list[dict[str, str]] = []

        def resolve(self, item, approve):
            call_id = item["tool_call_id"]
            require(self.confirmation_status(call_id) == "pending", "hold_not_pending_before_browser")
            pair_output = self.command(
                [str(self.binary), "pair", "--port", self.endpoint.rsplit(":", 1)[1]]
            )
            match = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pair_output)
            require(match is not None, "pairing_code_unavailable")
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True)
                    try:
                        page = browser.new_page(locale="zh-CN")
                        page_errors: list[str] = []
                        page.on("pageerror", lambda _: page_errors.append("pageerror"))
                        url = self.endpoint + "/confirmations?request=" + quote(item["decision_receipt_id"])
                        page.goto(url)
                        page.get_by_label("配对码", exact=True).fill(match.group(0))
                        page.get_by_role("button", name="建立管理会话", exact=True).click()
                        expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                        page.goto(url)
                        expect(page.get_by_role("heading", name="确认操作：" + self.write_tool)).to_be_visible()
                        page.get_by_label("确认人", exact=True).fill("automated-browser-reviewer")
                        page.get_by_text("我已核对本次操作和参数摘要").check()
                        action = "批准本次请求" if approve else "拒绝本次请求"
                        page.get_by_role("button", name=action, exact=True).click()
                        message = "已批准本次请求。确认记录：" if approve else "已拒绝本次请求。确认记录："
                        expect(page.get_by_text(re.compile(re.escape(message)))).to_be_visible()
                        require(not page_errors, "browser_page_error")
                    finally:
                        browser.close()
            except Exception as exc:
                # Playwright may include pairing details in exception text.
                raise RuntimeError("browser_confirmation_failed:" + type(exc).__name__) from None
            expected = "approved" if approve else "denied"
            require(self.confirmation_status(call_id) == expected, "browser_confirmation_status_mismatch")
            self.browser_actions.append({"call_id": call_id, "action": "approve" if approve else "deny"})
            return {"action": "allow" if approve else "deny"}

    with tempfile.TemporaryDirectory(prefix="siq-lx03-hermes-browser-approval-") as temporary:
        root = Path(temporary)
        harness = BrowserHarness(root, args)
        home = root / "home"
        home.mkdir(mode=0o700)
        harness.env.update({"HOME": str(home), "USERPROFILE": str(home),
                            "LOCALAPPDATA": str(home / "AppData/Local")})
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            harness.setup_authority()
            result = harness.probe()
            require(result["passed"], "native_approval_result_failed")
            require(len(harness.browser_actions) == len(native.LABELS), "browser_action_count_mismatch")
            require([item["call_id"] for item in harness.browser_actions] ==
                    ["write-" + label + "-original" for label in native.LABELS],
                    "browser_action_order_mismatch")
            require([item["action"] for item in harness.browser_actions] ==
                    ["deny" if label == "deny" else "approve" for label in native.LABELS],
                    "browser_action_decision_mismatch")
        finally:
            harness.stop()
    result["schema_version"] = "personal-lx03-hermes-browser-approval-native/v1"
    result["resolution_channel"] = "embedded_siq_ui_headless_chromium"
    result["browser_actions"] = harness.browser_actions
    result["browser_driver_sha256"] = digest(Path(__file__))
    result["base_approval_driver_sha256"] = digest(BASE)
    result["checks"] = [item.replace("console_approval_recorded", "browser_approval_recorded")
                        .replace("console_denial_recorded", "browser_denial_recorded")
                        .replace("grant_revoked_after_console_approval", "grant_revoked_after_browser_approval")
                        for item in result["checks"]]
    result["checks"].append("browser_six_resolutions_match_signed_native_retry_outcomes")
    result["browser_ui_resolutions"] = result.pop("console_resolutions")
    result["limitations"] = [item for item in result["limitations"]
                             if "desktop notification delivery and manual browser clicking" not in item]
    result["limitations"].append(
        "Browser clicks used headless Chromium and an automated reviewer; no desktop notification or human visual acceptance."
    )
    args.out.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with args.out.open("x") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"passed": True, "checks": len(result["checks"]),
                      "browser_actions": len(harness.browser_actions),
                      "receipt_count": result["receipt_count"]}))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print(f"Hermes browser approval failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
