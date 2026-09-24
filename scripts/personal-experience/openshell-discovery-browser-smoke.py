#!/usr/bin/env python3
"""Read an existing OpenShell gateway from real UI/API; never create or execute a sandbox."""

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location(
    "fixture", REPO / "scripts/validate-intent-v2-hermes.py"
)
fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["binary", "hermes-cli", "openshell-cli", "xdg-config", "out-dir"]:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--gateway", required=True)
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    args.binary, args.hermes_cli, args.openshell_cli = (
        args.binary.resolve(),
        args.hermes_cli.resolve(),
        args.openshell_cli.resolve(),
    )
    args.installer_managed_profile = True
    args.out_dir.mkdir(parents=True, exist_ok=True)
    checks, failure = {}, None
    # Only public gateway metadata/configuration hashes, never keys or certs.
    metadata = args.xdg_config / "openshell/gateways" / args.gateway / "metadata.json"
    before_metadata = hashlib.sha256(metadata.read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="siq-openshell-discovery-") as temp:
        harness = fixture.Harness(Path(temp), args)
        shutil.copy2(args.binary, harness.binary)
        fail_flag = Path(temp) / "cli-unavailable"
        delay_flag = Path(temp) / "delay-policy-read"
        wrapper = Path(temp) / "openshell-read-proxy"
        wrapper.write_text(
            f"#!{sys.executable}\nimport os,sys,time\nfrom pathlib import Path\n"
            f"if Path({str(fail_flag)!r}).exists(): sys.exit(7)\n"
            f"if Path({str(delay_flag)!r}).exists() and 'policy' in sys.argv: time.sleep(2)\n"
            f"os.execv({str(args.openshell_cli)!r}, [{str(args.openshell_cli)!r}, *sys.argv[1:]])\n"
        )
        wrapper.chmod(0o700)
        harness.env.update(
            {
                "XDG_CONFIG_HOME": str(args.xdg_config.resolve()),
                "SIQ_AS_OPENSHELL_CLI_BIN": str(wrapper),
                "SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT": args.endpoint,
                "SIQ_AS_OPENSHELL_GATEWAY_NAME": args.gateway,
            }
        )
        try:
            harness.start()
            catalog = harness.api("/v1/openshell/targets")
            fixture.require(
                catalog["state"] == "available"
                and catalog["can_inspect"]
                and catalog["items"],
                "native catalog unavailable",
            )
            item = next(row for row in catalog["items"] if row["phase"] == "Ready")
            checks["native_catalog_available_without_gateway_start"] = (
                catalog["started_gateway"] is False
            )
            pairing = subprocess.run(
                [
                    str(harness.binary),
                    "pair",
                    "--port",
                    str(urlparse(harness.endpoint).port),
                ],
                env=harness.env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            match = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing.stdout)
            fixture.require(match and pairing.returncode == 0, "pairing unavailable")
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1080},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                )
                errors = []
                page.on("pageerror", lambda _: errors.append("pageerror"))
                page.on(
                    "requestfailed",
                    lambda r: print(
                        json.dumps({"inspection_request_failed": True}), flush=True
                    )
                    if r.url.endswith("/v1/openshell/targets/inspect")
                    else None,
                )
                page.on(
                    "response",
                    lambda r: print(
                        json.dumps({"inspection_http_status": r.status}), flush=True
                    )
                    if r.url.endswith("/v1/openshell/targets/inspect")
                    else None,
                )
                page.goto(harness.endpoint + "/overview")
                page.get_by_label("配对码", exact=True).fill(match.group())
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                panel = page.get_by_role("region", name="OpenShell 环境发现")
                select = panel.get_by_label("选择沙箱", exact=True)
                expect(select).to_be_visible(timeout=60000)
                fixture.require(
                    select.locator("option").count() == len(catalog["items"]),
                    "UI catalog differs from API",
                )
                select.select_option(item["sandbox_id"])
                delay_flag.touch()
                expect(
                    page.get_by_role("button", name="重新发现", exact=True)
                ).to_be_enabled(timeout=30000)
                with page.expect_response(
                    lambda r: r.url.endswith("/v1/openshell/targets/inspect"),
                    timeout=60000,
                ) as inspected:
                    with page.expect_request(
                        lambda r: r.url.endswith("/v1/openshell/targets/inspect")
                    ):
                        panel.get_by_role(
                            "button", name="读取当前策略", exact=True
                        ).click()
                    page.get_by_role("button", name="重新发现", exact=True).click()
                    expect(
                        page.get_by_role("button", name="重新发现", exact=True)
                    ).to_be_enabled(timeout=30000)
                response = inspected.value.json()
                delay_flag.unlink()
                checks["first_inspection_http_200"] = inspected.value.status == 200
                fixture.require(
                    inspected.value.status == 200, "inspection not successful"
                )
                fixture.require(
                    response["sandbox_id"] == item["sandbox_id"]
                    and response["name"] == item["name"],
                    "wrong sandbox inspected",
                )
                fixture.require(
                    response["enforcement_verified"] is False,
                    "readback promoted to enforcement",
                )
                expect(
                    panel.get_by_text(f"{item['name']}：当前策略已读回", exact=True)
                ).to_be_visible()
                checks["homepage_select_and_real_policy_readback"] = True
                checks["agent_scan_does_not_cancel_policy_readback"] = True
                page.screenshot(
                    path=str(args.out_dir / "openshell-readback.png"), full_page=True
                )
                expect(
                    panel.get_by_text(f"{item['name']}：上次策略读回已过期", exact=True)
                ).to_be_visible(timeout=20000)
                checks["expired_observation_not_shown_current"] = True
                fail_flag.touch()
                with page.expect_response(
                    lambda r: r.url.endswith("/v1/openshell/targets/inspect"),
                    timeout=60000,
                ) as rejected:
                    panel.get_by_role("button", name="读取当前策略", exact=True).click()
                fixture.require(rejected.value.status == 409, "CLI failure accepted")
                expect(
                    panel.get_by_text(
                        "目标、网关或策略可能已变化。请重新发现后再读取，未修改任何配置。",
                        exact=True,
                    )
                ).to_be_visible()
                checks["cli_failure_clears_success_and_shows_recovery"] = (
                    panel.get_by_text("当前策略已读回", exact=False).count() == 0
                )
                fail_flag.unlink()
                panel.get_by_role(
                    "button", name="重新发现 OpenShell", exact=True
                ).click()
                expect(select).to_be_visible(timeout=60000)
                select.select_option(item["sandbox_id"])
                panel.get_by_role("button", name="读取当前策略", exact=True).click()
                expect(
                    panel.get_by_text(f"{item['name']}：当前策略已读回", exact=True)
                ).to_be_visible(timeout=60000)
                checks["rediscovery_and_readback_recover"] = True
                page.reload()
                expect(select).to_be_visible(timeout=60000)
                expect(panel.get_by_text("当前策略已读回", exact=False)).to_have_count(
                    0
                )
                checks["reload_discovers_without_reusing_stale_readback"] = True
                page.goto(harness.endpoint + "/bindings")
                expect(select).to_be_visible(timeout=60000)
                checks["runtime_environment_page_uses_same_catalog"] = select.locator(
                    "option"
                ).count() == len(catalog["items"])
                page.set_viewport_size({"width": 390, "height": 844})
                page.wait_for_function(
                    "document.querySelector('.sidebar').getBoundingClientRect().right <= 0"
                )
                select.scroll_into_view_if_needed()
                checks["mobile_selection_fits"] = select.evaluate(
                    "el => el.getBoundingClientRect().right <= innerWidth && el.getBoundingClientRect().left >= 0"
                )
                page.screenshot(
                    path=str(args.out_dir / "openshell-mobile.png"), full_page=True
                )
                checks["no_browser_errors"] = not errors
                browser.close()
            body = {
                "schema_version": "local-openshell-target-inspect/v1",
                "sandbox_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
                "name": item["name"],
                "endpoint_fingerprint": catalog["endpoint_fingerprint"],
            }
            harness.api("/v1/openshell/targets/inspect", body, expected=409)
            checks["foreign_uuid_rejected"] = True
            checks["no_authority_created"] = not harness.api("/v1/grants")["grants"]
            after = harness.api("/v1/openshell/targets")
            checks["gateway_catalog_unchanged"] = after["items"] == catalog["items"]
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
    checks["gateway_metadata_unchanged"] = (
        hashlib.sha256(metadata.read_bytes()).hexdigest() == before_metadata
    )
    result = {
        "schema_version": "siq.openshell-discovery-browser-proof/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "passed": failure is None and bool(checks) and all(checks.values()),
        "failure": failure,
        "checks": checks,
        "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        "hermes_cli_sha256": hashlib.sha256(args.hermes_cli.read_bytes()).hexdigest(),
        "openshell_cli_sha256": hashlib.sha256(
            args.openshell_cli.read_bytes()
        ).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "scope": "real existing gateway; read-only native CLI through controlled failure proxy; isolated candidate daemon and real Chromium; no sandbox execution",
    }
    (args.out_dir / "result.sanitized.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
