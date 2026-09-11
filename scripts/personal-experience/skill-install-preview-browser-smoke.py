#!/usr/bin/env python3
"""Exercise installation previews against an isolated real daemon; never install a Skill."""

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
loader = importlib.util.spec_from_file_location("daemon_fixture", REPO / "scripts/validate-intent-v2-hermes.py")
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
    with tempfile.TemporaryDirectory(prefix="siq-install-preview-") as temp:
        root = Path(temp)
        args.installer_managed_profile = True
        args.hermes_cli = root / "unavailable-hermes-cli"
        h = fixture.Harness(root, args)
        shutil.copy2(args.binary, h.binary)
        source = root / "skill"
        source.mkdir()
        (source / "SKILL.md").write_text(
            "---\nname: install-fixture\ndescription: Read a synthetic report.\n"
            "allowed-tools: read_file\n---\nRead a report.\n"
        )
        config = Path(h.env["HERMES_HOME"]) / "config.yaml"
        config_before = config.read_bytes()
        try:
            h.start()
            target = next(
                item
                for item in h.api("/v1/adapter/instances?platform=hermes")["instances"]
                if item["active"] and item["detected"]
            )
            imported = h.api(
                "/v1/skill-imports",
                {
                    "schema_version": "local-skill-import-create/v1",
                    "import_id": "si-" + "a" * 32,
                    "source_kind": "local_dir",
                    "path": str(source),
                    "actor_id": "fixture-human",
                },
                expected=201,
            )
            rec = imported["import"]
            prepared = h.api(
                "/v1/skill-imports/" + rec["import_id"] + "/permissions",
                {
                    "schema_version": "local-skill-import-permission-create/v1",
                    "request_id": "ip-" + "b" * 32,
                    "artifact_digest": rec["artifact_digest"],
                    "analysis_sha256": rec["analysis_sha256"],
                    "instance_id": target["instance_id"],
                    "actor_id": "fixture-human",
                },
                expected=201,
            )
            grant_id = prepared["grant"]["grant_id"]
            route = "/v1/grants/" + grant_id
            challenge = h.api(
                route + "/challenge",
                {
                    "expected_revision": 0,
                    "actor_id": "fixture-human",
                },
            )["challenge"]
            h.api(
                route + "/approve",
                {
                    "expected_revision": 0,
                    "actor_id": "fixture-human",
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                },
            )
            pairing = h.command([str(h.binary), "pair", "--port", h.endpoint.rsplit(":", 1)[1]])
            code = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing).group()
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1100}, locale="zh-CN")
                errors = []
                page.on("pageerror", lambda _: errors.append("pageerror"))
                page.goto(h.endpoint + "/grants?grant=" + grant_id)
                page.get_by_label("配对码", exact=True).fill(code)
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                expect(page.get_by_label("Skill 安装目录名", exact=True)).to_have_value("install-fixture")
                page.get_by_label("批准人（人工 actor_id）", exact=True).fill("fixture-human")
                checks["approved_grant_prefills_portable_skill_directory"] = True
                bodies = []

                def lose_first_response(intercept):
                    bodies.append(intercept.request.post_data_json)
                    response = intercept.fetch()
                    if len(bodies) == 1:
                        fixture.require(response.status == 201, "plan not committed before response loss")
                        intercept.abort("connectionfailed")
                    else:
                        fixture.require(response.status == 200, "retry did not reuse plan")
                        intercept.fulfill(response=response)

                page.route("**/v1/skill-installations/plans", lose_first_response)
                button = page.get_by_role("button", name="生成安装预览", exact=True)
                button.evaluate("button => { button.click(); button.click(); }")
                expect(page.get_by_role("button", name="重试原预览请求", exact=True)).to_be_visible()
                fixture.require(len(bodies) == 1, "duplicate click sent multiple requests")
                page.get_by_role("button", name="重试原预览请求", exact=True).click()
                expect(page.locator(".install-plan-result")).to_contain_text("预览已核验，尚未安装。")
                fixture.require(len(bodies) == 2 and bodies[0] == bodies[1], "retry changed original body")
                plan_id = parse_qs(urlparse(page.url).query)["install_plan"][0]
                plan = h.api("/v1/skill-installations/plans/" + plan_id)
                fixture.require(
                    plan["instance_id"] == target["instance_id"]
                    and plan["source"]["artifact_digest"] == rec["artifact_digest"],
                    "plan bound another target/content",
                )
                fixture.require(
                    plan["installed"] is False and plan["runtime_verified"] is False, "preview claimed installation"
                )
                checks["committed_response_loss_reuses_exact_request_and_single_plan"] = True
                page.reload()
                expect(page.locator(".install-plan-result")).to_contain_text(plan["source"]["artifact_digest"])
                fixture.require(len(bodies) == 2, "refresh automatically posted a new plan")
                again = h.api("/v1/skill-installations/plans/" + plan_id)
                fixture.require(again["signature"] == plan["signature"], "refresh changed signed plan")
                checks["refresh_revalidates_existing_plan_without_new_write"] = True
                page.locator(".skill-install-preview").evaluate("el => el.scrollIntoView({block: 'start'})")
                page.screenshot(path=str(args.out_dir / "preview-desktop.png"), animations="disabled")
                page.set_viewport_size({"width": 390, "height": 844})
                expect(page.locator(".sidebar")).to_be_hidden()
                page.locator(".skill-install-preview").evaluate("el => el.scrollIntoView({block: 'start'})")
                fixture.require(
                    page.locator("main.content").evaluate("el => el.scrollWidth <= el.clientWidth"),
                    "mobile preview overflows",
                )
                page.screenshot(path=str(args.out_dir / "preview-mobile.png"), animations="disabled")
                page.get_by_role("button", name="重新核验预览", exact=True).scroll_into_view_if_needed()
                expect(page.get_by_role("button", name="重新核验预览", exact=True)).to_be_in_viewport()
                page.screenshot(path=str(args.out_dir / "preview-mobile-actions.png"), animations="disabled")
                checks["mobile_target_and_digest_wrap"] = True
                stage = h.state / "skill-installations" / "stages" / plan_id / "payload" / "SKILL.md"
                original = stage.read_bytes()
                stage.write_text("changed staged content")
                page.get_by_role("button", name="重新核验预览", exact=True).click()
                expect(page.locator(".skill-install-preview [role=alert]")).to_contain_text("已变化")
                expect(page.locator(".install-plan-result")).to_have_count(0)
                checks["tampered_stage_removes_old_verified_preview"] = True
                stage.write_bytes(original)
                page.get_by_role("button", name="重新核验预览", exact=True).click()
                expect(page.locator(".install-plan-result")).to_be_visible()
                h.api(route + "/revoke", {"expected_revision": 1, "actor_id": "fixture-human"})
                page.get_by_role("button", name="重新核验预览", exact=True).click()
                expect(page.locator(".skill-install-preview [role=alert]")).to_contain_text("已变化")
                expect(page.locator(".install-plan-result")).to_have_count(0)
                page.reload()
                expect(page.locator(".import-grant-source")).to_be_visible()
                expect(page.locator(".skill-install-preview")).to_have_count(0)
                checks["revoked_authority_invalidates_preview_and_hides_new_preparation"] = True
                fixture.require(not errors, "browser page errors")
                browser.close()
            fixture.require(config.read_bytes() == config_before, "platform configuration changed")
            destination = Path(h.env["HERMES_HOME"]) / "skills" / "install-fixture"
            fixture.require(not destination.exists(), "preview installed into platform")
            fixture.require(
                len(list((h.state / "skill-installations" / "plans").glob("*.json"))) == 1,
                "retry published another plan",
            )
            fixture.require(not h.api("/v1/runtime-identities")["items"], "preview issued runtime identity")
            checks["no_platform_write_or_runtime_activation"] = True
            result = {
                "generated_at": datetime.now(UTC).isoformat(),
                "status": "passed",
                "checks": checks,
                "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                "scope": ("Real isolated daemon/browser; synthetic human approval via API; "
                          "no native host execution or Skill installation."),
            }
            (args.out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"status": "passed", "checks": len(checks)}))
        finally:
            h.stop()


if __name__ == "__main__":
    main()
