#!/usr/bin/env python3
"""Exercise SIQ browser approval through a pinned, isolated OpenClaw host copy.

The installed OpenClaw package and the user's HOME are never modified. The
fixture's native gateway and tool wrapper are real; the tool effect, model and
browser operator are local test fixtures. This does not attest stock OpenClaw.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
PATCH_DIR = ROOT / "patches/openclaw"
PROFILE = PATCH_DIR / "2026.5.12-approval-execution-recheck-v2.json"
PATCH = PATCH_DIR / "2026.5.12-approval-execution-recheck-v2.patch"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def approval_module():
    path = ROOT / "scripts/validate-intent-v2-openclaw-approval-gate.py"
    spec = importlib.util.spec_from_file_location("lx03_openclaw_approval", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.openclaw_root = args.openclaw_root.resolve(strict=True)
    args.node = args.node.resolve(strict=True)
    args.binary = args.binary.resolve(strict=True)
    require(args.out.parent.name.endswith("-private"), "output must be private")
    require(not args.out.exists(), "refusing to overwrite evidence")
    profile = json.loads(PROFILE.read_text())
    package = json.loads((args.openclaw_root / "package.json").read_text())
    require(
        package.get("name") == profile["package"]
        and package.get("version") == profile["version"],
        "unsupported OpenClaw package/version",
    )
    original = args.openclaw_root / profile["target"]
    require(original.is_file() and not original.is_symlink(), "unsafe host target")
    require(sha256(original) == profile["before_sha256"], "host fingerprint changed")
    require(sha256(PATCH) == profile["patch_sha256"], "patch fingerprint changed")
    adapter = ROOT / profile["adapter_source"]
    embedded = ROOT / "apps/agentshield/internal/adapterinstall/assets/openclaw/index.ts"
    require(
        sha256(adapter) == sha256(embedded) == profile["adapter_sha256"],
        "shipping adapter differs from pinned host profile",
    )
    native = approval_module()

    class BrowserApprovalHarness(native.ApprovalHarness):
        browser_actions: list[dict[str, str]]

        def __init__(self, root, options):
            super().__init__(root, options)
            self.browser_actions = []

        def api(self, path, body=None, *, token=None, expected=200):
            if path.startswith("/v1/hold/") and isinstance(body, dict) and "approve" in body:
                receipt_id = path.removeprefix("/v1/hold/")
                approved = body["approve"] is True
                self.approve_in_browser(receipt_id, approved)
                return {}
            return super().api(path, body, token=token, expected=expected)

        def approve_in_browser(self, receipt_id: str, approved: bool) -> None:
            pair_output = self.command(
                [str(self.binary), "pair", "--port", self.endpoint.rsplit(":", 1)[1]]
            )
            match = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pair_output)
            require(match is not None, "pairing code unavailable")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    context = browser.new_context(locale="zh-CN")
                    page = context.new_page()
                    page_errors: list[str] = []
                    page.on("pageerror", lambda _: page_errors.append("pageerror"))
                    page.goto(self.endpoint + "/confirmations?request=" + quote(receipt_id))
                    page.get_by_label("配对码", exact=True).fill(match.group(0))
                    page.get_by_role("button", name="建立管理会话", exact=True).click()
                    expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                    page.goto(self.endpoint + "/confirmations?request=" + quote(receipt_id))
                    expect(page.get_by_role("heading", name="确认操作：exec")).to_be_visible()
                    page.get_by_label("确认人", exact=True).fill("automated-browser-operator")
                    page.get_by_text("我已核对本次操作和参数摘要").check()
                    action = "批准本次请求" if approved else "拒绝本次请求"
                    page.get_by_role("button", name=action, exact=True).click()
                    outcome = "已批准本次请求。确认记录：" if approved else "已拒绝本次请求。确认记录："
                    expect(page.get_by_text(re.compile(re.escape(outcome)))).to_be_visible()
                    require(not page_errors, "browser script error")
                    self.browser_actions.append(
                        {"decision_receipt_id": receipt_id, "action": "approve" if approved else "deny"}
                    )
                finally:
                    browser.close()

    with tempfile.TemporaryDirectory(prefix="siq-lx03-openclaw-controlled-ui-") as temporary:
        root = Path(temporary)
        copy = root / "runtime"
        controlled_start = ROOT / "scripts/openclaw-controlled-start.py"
        subprocess.run(
            [
                sys.executable, str(controlled_start), "prepare",
                "--source", str(args.openclaw_root),
                "--destination", str(copy),
                "--node", str(args.node),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        subprocess.run(
            [sys.executable, str(controlled_start), "inspect", "--runtime", str(copy)],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
        target = copy / profile["target"]
        require(sha256(target) == profile["after_sha256"], "controlled host patch changed")
        args.openclaw_root = copy
        (root / "cases").mkdir(mode=0o700)
        harness = BrowserApprovalHarness(root / "cases", args)
        try:
            result = harness.run(
                cases=[
                    {"id": "ui-approved-native-once", "platform": "allow-once", "local": True},
                    {"id": "ui-denied-native-zero", "platform": "allow-once", "local": False},
                ]
            )
            require(result["passed"] and result["receipt_chain_verified"], "native/UI result failed")
            require(
                len(harness.browser_actions) == 2
                and [item["action"] for item in harness.browser_actions] == ["approve", "deny"],
                "UI resolution actions incomplete",
            )
        finally:
            harness.stop()
    require(sha256(original) == profile["before_sha256"], "installed host changed")
    report = {
        "schema": "personal-lx03-openclaw-controlled-ui-hold/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "passed": True,
        "candidate_sha256": sha256(args.binary),
        "host_version": profile["version"],
        "host_runtime": "temporary pinned checkpoint-v2 copy",
        "host_source_before_sha256": profile["before_sha256"],
        "host_source_after_sha256": profile["after_sha256"],
        "adapter_sha256": sha256(adapter),
        "driver_sha256": sha256(Path(__file__)),
        "controlled_start_sha256": sha256(controlled_start),
        "approval_harness_sha256": sha256(ROOT / "scripts/validate-intent-v2-openclaw-approval-gate.py"),
        "browser_actions": harness.browser_actions,
        "native_result": result,
        "limitations": [
            "This is an isolated patched host copy, not the installed stock OpenClaw runtime.",
            "The browser operator, platform approver, model and file-effect tool are local fixtures.",
            "One native effect and its reservation do not prove cross-process external exactly-once.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with args.out.open("x") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"passed": True, "browser_actions": len(harness.browser_actions), "native_cases": len(result["cases"])}))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"controlled UI hold failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
