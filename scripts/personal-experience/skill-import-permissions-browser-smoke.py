#!/usr/bin/env python3
"""Exercise real import -> permission draft -> approval, with response loss and pre-approval tamper injections."""

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location(
    "daemon_fixture", REPO / "scripts/validate-intent-v2-hermes.py"
)
fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    args.binary = args.binary.resolve()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    checks = {}
    with tempfile.TemporaryDirectory(prefix="siq-import-permission-") as temp:
        root = Path(temp)
        args.installer_managed_profile = True
        args.hermes_cli = root / "unavailable-hermes-cli"
        h = fixture.Harness(root, args)
        shutil.copy2(args.binary, h.binary)
        source = root / "skill"
        source.mkdir()
        (source / "SKILL.md").write_text(
            "---\nname: permission-fixture\ndescription: Read a synthetic report.\n"
            "allowed-tools: read_file\n---\nRead a report.\n"
        )
        config_path = Path(h.env["HERMES_HOME"]) / "config.yaml"
        original_config = config_path.read_bytes()
        try:
            h.start()
            pairing = h.command(
                [str(h.binary), "pair", "--port", h.endpoint.rsplit(":", 1)[1]]
            )
            code = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing).group()
            instances = h.api("/v1/adapter/instances?platform=hermes")["instances"]
            target = next(
                item for item in instances if item["active"] and item["detected"]
            )
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1100}, locale="zh-CN"
                )
                errors = []
                page.on("pageerror", lambda _: errors.append("pageerror"))
                page.goto(h.endpoint + "/skill-imports")
                page.get_by_label("配对码", exact=True).fill(code)
                page.get_by_role("button", name="建立管理会话", exact=True).click()

                def import_candidate():
                    page.goto(h.endpoint + "/skill-imports")
                    expect(
                        page.get_by_label("本机绝对路径", exact=True)
                    ).to_be_editable()
                    page.get_by_label("本机绝对路径", exact=True).fill(str(source))
                    page.get_by_label("操作者", exact=True).fill("fixture-human")
                    page.get_by_role("button", name="导入并检查", exact=True).click()
                    expect(
                        page.get_by_role(
                            "heading", name="检查结果：permission-fixture", exact=True
                        )
                    ).to_be_visible()
                    candidate = parse_qs(urlparse(page.url).query)["import"][0]
                    expect(
                        page.get_by_label("目标 Hermes 实例", exact=True)
                    ).to_be_enabled()
                    page.get_by_label("目标 Hermes 实例", exact=True).select_option(
                        target["instance_id"]
                    )
                    return candidate

                first = import_candidate()
                fixture.require(
                    not h.api("/v1/grants")["grants"], "import itself created authority"
                )
                checks["import_stays_unapproved_until_explicit_preparation"] = True
                bodies = []

                def lose_response(route):
                    bodies.append(route.request.post_data_json)
                    response = route.fetch()
                    if len(bodies) == 1:
                        fixture.require(
                            response.status == 201,
                            "preparation not actually committed before loss",
                        )
                        route.abort("connectionfailed")
                    else:
                        route.fulfill(response=response)

                page.route("**/v1/skill-imports/*/permissions", lose_response)
                page.get_by_role("button", name="准备并审阅权限", exact=True).click()
                expect(
                    page.get_by_role("button", name="查询或重试原权限请求", exact=True)
                ).to_be_enabled()
                page.get_by_role(
                    "button", name="查询或重试原权限请求", exact=True
                ).click()
                expect(page).to_have_url(
                    re.compile(r"/grants\?grant=grt-si-[a-f0-9]{64}$")
                )
                page.unroute("**/v1/skill-imports/*/permissions", lose_response)
                fixture.require(
                    len(bodies) == 2 and bodies[0] == bodies[1],
                    "retry changed permission request",
                )
                grants = h.api("/v1/grants")["grants"]
                fixture.require(
                    len(grants) == 1 and grants[0]["status"] == "pending_approval",
                    "duplicate/approved draft",
                )
                grant_id = grants[0]["grant_id"]
                fixture.require(
                    grants[0]["subject"]["id"]
                    == target["instance_id"].replace("hi-", "hri-", 1),
                    "wrong runtime instance binding",
                )
                checks["lost_response_reuses_one_real_draft_and_exact_target"] = True
                expect(
                    page.get_by_role("link", name="查看绑定的 Skill 候选", exact=True)
                ).to_have_attribute("href", "/skill-imports?import=" + first)
                detail = h.api("/v1/skill-imports/" + first)
                expect(page.locator(".import-grant-source")).to_contain_text(
                    detail["import"]["artifact_digest"]
                )
                checks["grant_review_shows_full_immutable_source"] = True
                page.get_by_role("button", name="批准", exact=True).click()
                expect(
                    page.get_by_role("button", name="批准", exact=True)
                ).to_be_disabled()
                expect(page.locator(".sync-ok")).to_contain_text("已批准")
                current = h.api("/v1/grants/" + grant_id)
                fixture.require(
                    current["grant"]["status"] == "approved", "approval not persisted"
                )
                expect(
                    page.get_by_role("button", name="标记已部署", exact=True)
                ).to_be_disabled()
                denied = h.api(
                    "/v1/grants/" + grant_id + "/deploy",
                    body={
                        "expected_revision": current["state_revision"],
                        "actor_id": "fixture-human",
                    },
                    expected=400,
                )
                fixture.require(
                    denied["error"] == "grant_import_installation_required",
                    "API allowed early activation",
                )
                checks["human_approval_cannot_activate_before_installation"] = True
                page.screenshot(
                    path=str(args.out_dir / "permission-approved-desktop.png"),
                    full_page=True,
                )
                page.set_viewport_size({"width": 390, "height": 844})
                expect(page.locator(".sidebar")).to_be_hidden()
                page.locator(".import-grant-source").scroll_into_view_if_needed()
                fixture.require(
                    page.locator("main.content").evaluate(
                        "el => el.scrollWidth <= el.clientWidth"
                    ),
                    "permission detail overflow",
                )
                page.screenshot(
                    path=str(args.out_dir / "permission-source-mobile.png"),
                    full_page=True,
                    animations="disabled",
                )
                checks["mobile_source_digest_wraps"] = True
                page.set_viewport_size({"width": 1440, "height": 1100})
                second = import_candidate()
                page.get_by_role("button", name="准备并审阅权限", exact=True).click()
                expect(page).to_have_url(
                    re.compile(r"/grants\?grant=grt-si-[a-f0-9]{64}$")
                )
                second_grant = parse_qs(urlparse(page.url).query)["grant"][0]
                expect(
                    page.get_by_role("button", name="批准", exact=True)
                ).to_be_enabled()

                def replace_before_approve(route):
                    (
                        h.state / "skill-imports/blobs" / second / "payload/SKILL.md"
                    ).write_text("changed after challenge")
                    route.continue_()

                page.route("**/v1/grants/*/approve", replace_before_approve)
                page.get_by_role("button", name="批准", exact=True).click()
                expect(page.get_by_role("alert")).to_contain_text("记录或副本发生变化")
                fixture.require(
                    h.api("/v1/grants/" + second_grant)["grant"]["status"]
                    == "pending_approval",
                    "changed candidate approved",
                )
                page.unroute("**/v1/grants/*/approve", replace_before_approve)
                checks["content_changed_after_challenge_blocks_browser_approval"] = True
                page.get_by_role("button", name="吊销", exact=True).click()
                expect(page.locator(".sync-ok")).to_contain_text("已吊销")
                fixture.require(
                    h.api("/v1/grants/" + second_grant)["grant"]["status"] == "revoked",
                    "damaged source prevented revoke",
                )
                checks["damaged_source_can_still_be_revoked"] = True
                events = h.api("/v1/audit")["events"]
                fixture.require(
                    len(
                        [
                            e
                            for e in events
                            if e["event"] == "skill_import_permission_prepare"
                        ]
                    )
                    == 2,
                    "preparation audit duplicated",
                )
                fixture.require(
                    config_path.read_bytes() == original_config,
                    "permission flow modified platform config",
                )
                fixture.require(
                    not h.api("/v1/runtime-identities")["items"],
                    "permission flow issued runtime credential",
                )
                fixture.require(not errors, "browser raised script error")
                checks[
                    "single_audit_per_draft_no_platform_change_or_runtime_identity"
                ] = True
                browser.close()
        finally:
            h.stop()
    report = {
        "schema_version": "personal-import-permission-browser/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "candidate_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "checks": checks,
        "passed": all(checks.values()),
        "method": "real_isolated_linux_daemon_and_chromium; response_loss_and_tamper_injections",
        "limitations": [
            "Hermes target is an isolated configuration fixture, no host runtime is executed",
            "No platform installation or deployed/effective permission",
            "No Windows/macOS/WorkBuddy acceptance",
        ],
    }
    (args.out_dir / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "checks": len(checks)}))


if __name__ == "__main__":
    main()
