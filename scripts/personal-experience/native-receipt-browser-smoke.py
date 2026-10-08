#!/usr/bin/env python3
"""Exercise native receipt presentation with explicit HTTP fixtures, not native execution."""

import argparse
import copy
import importlib.util
import json
import re
import shutil
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("native_fixture", REPO / "scripts/validate-intent-v2-hermes.py")
fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.binary = args.binary.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    samples = REPO / "apps/agentshield/testdata/contracts"
    skill = json.loads((samples / "native-receipt-with-skill-v3.sample.json").read_text())
    no_skill = json.loads((samples / "native-receipt-no-skill-v3.sample.json").read_text())
    checks = {}
    with tempfile.TemporaryDirectory(prefix="siq-native-receipt-browser-") as temp:
        args.installer_managed_profile = True
        args.hermes_cli = Path(temp) / "unavailable-hermes-cli"
        harness = fixture.Harness(Path(temp), args)
        harness.config("optional")
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            pairing = harness.command([str(harness.binary), "pair", "--port", harness.endpoint.rsplit(":", 1)[1]])
            pairing_code = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing).group()
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1000})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda _: errors.append("pageerror"))
                response = {"receipts": [skill], "verified": True}
                page.route("**/v1/receipts?*", lambda route: route.fulfill(json=response))
                page.goto(harness.endpoint + "/receipts")
                page.get_by_text("手动配对 / 旧版本连接", exact=True).click()
                page.get_by_label("配对码", exact=True).fill(pairing_code)
                page.get_by_role("button", name="建立管理会话", exact=True).click()

                def check(name, row, verified, text, trusted):
                    response.update(receipts=[row], verified=verified)
                    with page.expect_response(lambda r: r.url.split("?", 1)[0].endswith("/v1/receipts")):
                        page.get_by_role("button", name="验签", exact=True).click()
                    cell = page.locator("tbody tr").first.locator("td").nth(6)
                    expect(cell).to_have_text(text)
                    expect(cell.locator(".tag-allow")).to_have_count(1 if trusted else 0)
                    checks[name] = True

                expect(page.get_by_role("heading", name="回执", exact=True)).to_be_visible()
                check("native_skill", skill, True, "调用级可信 · " + skill["skill_attribution"]["skill_id"], True)
                expect(page.locator("tbody tr").first.locator("td").nth(6).locator("span")).to_have_attribute(
                    "title", re.compile("不证明当前授权仍有效、业务效果或模型指令因果")
                )
                fixture.require(page.locator("tbody tr").first.bounding_box()["height"] < 250, "unreadable receipt row")
                checks["readable_desktop_row"] = True
                page.screenshot(path=str(args.out_dir / "native-skill.png"), full_page=True)
                check("explicit_no_skill", no_skill, True, "无 Skill · Agent 基线", True)
                for label, verified in [("failed_signature", False), ("string_false", "false"), ("string_true", "true")]:
                    check(label, skill, verified, "未验证", False)
                    expect(page.get_by_role("alert").filter(has_text="验签失败")).to_be_visible()
                changed = copy.deepcopy(skill)
                changed["skill_attribution"]["call_binding"] = "f" * 64
                check("mismatched_binding", changed, True, "未验证", False)
                changed = copy.deepcopy(skill)
                changed["schema_version"] = "runtime-receipt/v99"
                check("unknown_version", changed, True, "未验证", False)
                changed = copy.deepcopy(skill)
                changed.pop("native_invocation")
                check("missing_native_proof", changed, True, "未验证", False)
                fixture.require(not errors, "browser page errors")
                checks["no_page_errors"] = True
                browser.close()
        finally:
            harness.stop()
    summary = {"scope": "built_ui_http_fixture_only", "native_execution": False, "checks": checks}
    (args.out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
