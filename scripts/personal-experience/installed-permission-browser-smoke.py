#!/usr/bin/env python3
"""Exercise installed Skill permission preparation and instance handoff in temporary synthetic profiles."""

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
    with tempfile.TemporaryDirectory(prefix="siq-install-management-") as temp:
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
            prepared = h.api(
                route + "/patch-desired",
                {
                    "expected_revision": prepared["state_revision"],
                    "actor_id": "fixture-human",
                    "tools": ["read_file"],
                    "filesystem": {"read_only": [str(root)], "read_write": []},
                },
            )
            challenge = h.api(
                route + "/challenge",
                {
                    "expected_revision": prepared["state_revision"],
                    "actor_id": "fixture-human",
                },
            )["challenge"]
            h.api(
                route + "/approve",
                {
                    "expected_revision": prepared["state_revision"],
                    "actor_id": "fixture-human",
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                },
            )
            pairing = h.command(
                [str(h.binary), "pair", "--port", h.endpoint.rsplit(":", 1)[1]]
            )
            code = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing).group()
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1100}, locale="zh-CN"
                )
                errors = []
                page.on("pageerror", lambda _: errors.append("pageerror"))
                page.goto(h.endpoint + "/grants?grant=" + grant_id)
                page.get_by_label("配对码", exact=True).fill(code)
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                expect(page.get_by_label("Skill 安装目录名", exact=True)).to_have_value(
                    "install-fixture"
                )
                page.get_by_label("批准人（人工 actor_id）", exact=True).fill(
                    "fixture-human"
                )
                checks["approved_grant_prefills_portable_skill_directory"] = True
                writes = []
                button = page.get_by_role("button", name="生成安装预览", exact=True)
                button.click()
                expect(page.locator(".install-plan-result")).to_contain_text(
                    "预览已核验，尚未安装。"
                )
                plan_id = parse_qs(urlparse(page.url).query)["install_plan"][0]
                plan = h.api("/v1/skill-installations/plans/" + plan_id)
                install_id = plan_id.replace("sip-", "sin-", 1)
                operation_route = "/v1/skill-installations/operations/" + install_id
                install = page.get_by_role("button", name="确认安装 Skill", exact=True)
                expect(install).to_be_disabled()
                page.get_by_label(
                    "我已核对安装位置、内容和权限，确认安装", exact=True
                ).check()
                expect(install).to_be_enabled()
                page.set_viewport_size({"width": 390, "height": 844})
                expect(page.locator(".sidebar")).to_be_hidden()
                install.scroll_into_view_if_needed()
                expect(install).to_be_in_viewport()
                checkbox = page.get_by_label(
                    "我已核对安装位置、内容和权限，确认安装", exact=True
                )
                fixture.require(
                    checkbox.bounding_box()["width"] < 30,
                    "confirmation checkbox stretched",
                )
                page.screenshot(
                    path=str(args.out_dir / "confirm-mobile.png"), animations="disabled"
                )
                page.set_viewport_size({"width": 1440, "height": 1100})
                checks["explicit_confirmation_required"] = True

                def lose_apply_response(intercept):
                    writes.append(intercept.request.post_data_json)
                    response = intercept.fetch()
                    fixture.require(
                        response.status == 200, "installation did not commit"
                    )
                    fixture.require(
                        response.json()["status"] == "installed_unverified",
                        "unexpected installation status",
                    )
                    intercept.abort("connectionfailed")

                page.route("**/v1/skill-installations/apply", lose_apply_response)
                install.evaluate("button => { button.click(); button.click(); }")
                panel = page.locator(
                    'section[aria-labelledby="installation-result-heading"]'
                )
                expect(panel).to_contain_text(
                    "Skill 文件已安装并完成内容核验，尚未验证运行保护。"
                )
                fixture.require(
                    len(writes) == 1, "duplicate confirmation sent multiple writes"
                )
                fixture.require(
                    writes[0]["plan_signature"] == plan["signature"],
                    "confirmation changed plan",
                )
                fixture.require(
                    "install_plan" not in parse_qs(urlparse(page.url).query),
                    "installed view reloads obsolete preview",
                )
                checks["committed_response_loss_reads_result_without_second_apply"] = (
                    True
                )
                destination = Path(h.env["HERMES_HOME"]) / "skills" / "install-fixture"
                entry = destination / "SKILL.md"
                original = entry.read_bytes()
                fixture.require(
                    original == (source / "SKILL.md").read_bytes(),
                    "target differs from source",
                )
                view = h.api(operation_route)
                fixture.require(
                    view["plan"]["signature"] == plan["signature"],
                    "result bound another preview",
                )
                fixture.require(
                    view["operation"]["runtime_verified"] is False,
                    "installation claimed runtime protection",
                )
                grant = h.api(route)["grant"]
                fixture.require(
                    grant["status"] == "approved", "installation activated grant"
                )
                fixture.require(
                    not h.api("/v1/runtime-identities")["items"],
                    "installation issued identity",
                )
                page.reload()
                expect(panel).to_contain_text(
                    "Skill 文件已安装并完成内容核验，尚未验证运行保护。"
                )
                fixture.require(len(writes) == 1, "reload reinstalled Skill")
                checks["refresh_reads_existing_target_without_activation"] = True
                protection = page.get_by_role("region", name="安装后的实例权限")
                prepare = page.get_by_role(
                    "button", name="确认并准备实例权限", exact=True
                )
                expect(prepare).to_be_disabled()
                expect(protection).to_contain_text("read_file")
                expect(protection).to_contain_text(str(root))
                fixture.require(
                    h.api(operation_route + "/runtime")["status"] == "not_prepared",
                    "refresh activated authority",
                )
                activation_writes = []

                def lose_activation_response(intercept):
                    activation_writes.append(intercept.request.post_data_json)
                    response = intercept.fetch()
                    fixture.require(response.status == 200, "preparation failed")
                    intercept.abort("connectionfailed")

                page.route(
                    "**/v1/skill-installations/operations/*/activate",
                    lose_activation_response,
                )
                page.get_by_label(
                    "确认以上权限用于此 Hermes 实例的会话", exact=True
                ).check()
                prepare.evaluate("button => { button.click(); button.click(); }")
                manage = page.get_by_role("button", name="管理此实例接入", exact=True)
                expect(manage).to_be_enabled()
                expect(protection).to_contain_text(
                    "实例权限已准备。接入配置和运行保护仍需分别验证。"
                )
                fixture.require(len(activation_writes) == 1, "duplicate activation")
                fixture.require(
                    not h.api("/v1/runtime-identities")["items"],
                    "preparation issued identity",
                )
                fixture.require(
                    config.read_bytes() == config_before, "preparation changed config"
                )
                checks[
                    "explicit_preparation_response_loss_recovers_via_read_only_query"
                ] = True
                page.reload()
                expect(manage).to_be_enabled()
                fixture.require(
                    len(activation_writes) == 1, "refresh retried activation"
                )
                checks["refresh_preserves_prepared_state_without_write"] = True
                page.set_viewport_size({"width": 1440, "height": 1100})
                protection.evaluate("el => el.scrollIntoView({block:'center'})")
                page.screenshot(
                    path=str(args.out_dir / "prepared-desktop.png"),
                    animations="disabled",
                )
                page.set_viewport_size({"width": 390, "height": 844})
                expect(page.locator(".sidebar")).to_be_hidden()
                protection.evaluate("el => el.scrollIntoView({block:'center'})")
                fixture.require(
                    page.locator("main.content").evaluate(
                        "el => el.scrollWidth <= el.clientWidth"
                    ),
                    "mobile overflow",
                )
                page.screenshot(
                    path=str(args.out_dir / "prepared-mobile.png"),
                    animations="disabled",
                )
                checks["mobile_preparation_and_actions_fit"] = True
                # A separate synthetic, non-import Grant models a previously
                # connected instance. The UI must never silently reuse it.
                admission = h.api("/v1/admit", {"path": str(source)})["admission"]
                previous = h.api(
                    "/v1/grants",
                    {
                        "admission_id": admission["admission_id"],
                        "platform": "hermes",
                        "subject_id": target["instance_id"].replace("hi-", "hri-", 1),
                        "redact_secrets": True,
                    },
                )
                previous_path = "/v1/grants/" + previous["grant"]["grant_id"]
                previous = h.api(
                    previous_path + "/patch-desired",
                    {
                        "expected_revision": previous["state_revision"],
                        "actor_id": "fixture-human",
                        "tools": ["read_file"],
                        "filesystem": {"read_only": [str(source)], "read_write": []},
                    },
                )
                approval = h.api(
                    previous_path + "/challenge",
                    {"expected_revision": previous["state_revision"]},
                )["challenge"]
                previous = h.api(
                    previous_path + "/approve",
                    {
                        "expected_revision": previous["state_revision"],
                        "actor_id": "fixture-human",
                        "challenge_id": approval["challenge_id"],
                        "nonce": approval["nonce"],
                    },
                )
                previous = h.api(
                    previous_path + "/deploy",
                    {
                        "expected_revision": previous["state_revision"],
                        "actor_id": "fixture-human",
                    },
                )
                old_identity = h.api(
                    "/v1/runtime-identities",
                    {
                        "schema_version": "local-runtime-identity-create/v1",
                        "instance_id": target["instance_id"],
                        "grant_id": previous["grant"]["grant_id"],
                        "expected_grant_revision": previous["state_revision"],
                        "actor_id": "fixture-human",
                        "session_ttl_seconds": 600,
                    },
                    expected=201,
                )["identity"]
                manage.click()
                expect(
                    page.get_by_label("Hermes 实例 / profile", exact=True)
                ).to_have_value(target["instance_id"])
                expect(
                    page.get_by_label("Hermes 实例 / profile", exact=True)
                ).to_be_disabled()
                expect(page.get_by_label("已有实例授权", exact=True)).to_have_value(
                    grant_id
                )
                expect(page.get_by_label("已有实例授权", exact=True)).to_be_disabled()
                expect(page.get_by_label("接入方式", exact=True)).to_be_disabled()
                issue = page.get_by_role(
                    "button", name="使用此授权并准备接入", exact=True
                )
                expect(issue).to_be_disabled()
                page.get_by_label("本次操作者", exact=True).fill("fixture-human")
                page.get_by_label("我已核对以上权限范围", exact=True).check()
                expect(issue).to_be_disabled()
                expect(
                    page.get_by_role("button", name="确认应用", exact=True)
                ).to_be_disabled()
                page.get_by_label("确认停用，后续工具调用将被阻止", exact=True).check()
                page.get_by_role("button", name="停用此实例权限", exact=True).click()
                expect(
                    page.get_by_role("button", name="停用此实例权限", exact=True)
                ).to_have_count(0)
                page.get_by_label("我已核对以上权限范围", exact=True).check()
                expect(issue).to_be_enabled()
                checks["different_existing_grant_requires_explicit_revocation"] = True
                identity_writes = []

                def track_identity(intercept):
                    if intercept.request.method == "POST":
                        identity_writes.append(intercept.request.post_data_json)
                    intercept.continue_()

                page.route("**/v1/runtime-identities", track_identity)
                issue.evaluate("button => { button.click(); button.click(); }")
                apply = page.get_by_role("button", name="确认应用", exact=True)
                expect(apply).to_be_enabled()
                fixture.require(len(identity_writes) == 1, "duplicate runtime identity")
                fixture.require(
                    identity_writes[0]["grant_id"] == grant_id, "issued wrong grant"
                )
                fixture.require(
                    identity_writes[0]["instance_id"] == target["instance_id"],
                    "issued wrong instance",
                )
                page.screenshot(
                    path=str(args.out_dir / "instance-handoff-mobile.png"),
                    animations="disabled",
                )
                checks["locked_instance_grant_and_explicit_identity_confirmation"] = (
                    True
                )
                apply.click()
                expect(page.get_by_role("dialog")).to_be_hidden()
                expect(manage).to_be_enabled()
                identities = h.api("/v1/runtime-identities")["items"]
                fixture.require(len(identities) == 2, "identity count")
                fixture.require(
                    next(
                        i
                        for i in identities
                        if i["identity_id"] == old_identity["identity_id"]
                    )["status"]
                    == "revoked",
                    "old identity not revoked",
                )
                identities = [i for i in identities if i["status"] != "revoked"]
                fixture.require(
                    identities[0]["grant_ref"]["grant_id"] == grant_id,
                    "configured wrong grant",
                )
                checks["browser_applies_existing_managed_adapter_flow"] = True
                page.get_by_role("button", name="运行此实例自检", exact=True).click()
                expect(
                    page.get_by_label("自检实例 / profile", exact=True)
                ).to_have_value(target["instance_id"])
                expect(
                    page.get_by_label("自检实例 / profile", exact=True)
                ).to_be_disabled()
                page.get_by_role("button", name="关闭", exact=True).click()
                expect(page.get_by_role("dialog")).to_be_hidden()
                checks["selfcheck_targets_same_instance_without_auto_execution"] = True
                entry.write_text("fixture changed target")
                page.get_by_role(
                    "button", name="重新查询权限准备状态", exact=True
                ).click()
                expect(protection).to_contain_text("当前无法确认权限准备状态")
                expect(manage).to_have_count(0)
                checks["target_drift_removes_prepared_actions"] = True
                fixture.require(not errors, "browser page error")
                browser.close()
            result = {
                "generated_at": datetime.now(UTC).isoformat(),
                "status": "passed",
                "checks": checks,
                "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                "scope": (
                    "Isolated real daemon and browser; synthetic operator and profile. Explicit installation, "
                    "permission preparation, runtime identity and adapter configuration. No native host or "
                    "Skill payload execution; separate native harness verifies execution. No cross-OS acceptance."
                ),
            }
            (args.out_dir / "result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n"
            )
            print(json.dumps({"status": "passed", "checks": len(checks)}))
        finally:
            h.stop()


if __name__ == "__main__":
    main()
