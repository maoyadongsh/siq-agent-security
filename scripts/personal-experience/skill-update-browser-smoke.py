#!/usr/bin/env python3
"""Exercise Skill update review, confirmation and interrupted recovery in an isolated browser/profile."""
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
    with tempfile.TemporaryDirectory(prefix="siq-update-browser-") as temp:
        root = Path(temp)
        args.installer_managed_profile = True
        args.hermes_cli = root / "unavailable-hermes-cli"
        h = fixture.Harness(root, args)
        shutil.copy2(args.binary, h.binary)
        try:
            h.start()
            target = next(i for i in h.api("/v1/adapter/instances?platform=hermes")["instances"]
                          if i["active"] and i["detected"])
            config = Path(h.env["HERMES_HOME"]) / "config.yaml"
            before_config = config.read_bytes()

            def imported_permission(character, version):
                source = root / ("version-" + character)
                source.mkdir()
                (source / "SKILL.md").write_text(
                    "---\nname: update-fixture\ndescription: Read a synthetic report.\n"
                    "allowed-tools: read_file\n---\n" + version + "\n")
                result = h.api("/v1/skill-imports", {
                    "schema_version": "local-skill-import-create/v1", "import_id": "si-" + character * 32,
                    "source_kind": "local_dir", "path": str(source), "actor_id": "fixture-human"}, expected=201)
                rec = result["import"]
                permission = h.api("/v1/skill-imports/" + rec["import_id"] + "/permissions", {
                    "schema_version": "local-skill-import-permission-create/v1", "request_id": "ip-" + character * 32,
                    "artifact_digest": rec["artifact_digest"], "analysis_sha256": rec["analysis_sha256"],
                    "instance_id": target["instance_id"], "actor_id": "fixture-human"}, expected=201)
                route = "/v1/grants/" + permission["grant"]["grant_id"]
                permission = h.api(route + "/patch-desired", {
                    "expected_revision": permission["state_revision"], "actor_id": "fixture-human",
                    "tools": ["read_file"], "filesystem": {"read_only": [str(source)], "read_write": []}})
                return source, route, permission

            def approve(route, permission):
                revision = permission["state_revision"]
                ch = h.api(route + "/challenge", {"expected_revision": revision, "actor_id": "fixture-human"})["challenge"]
                return h.api(route + "/approve", {"expected_revision": revision, "actor_id": "fixture-human",
                                                   "challenge_id": ch["challenge_id"], "nonce": ch["nonce"]})

            old_source, old_route, old = imported_permission("a", "Original report")
            old = approve(old_route, old)
            staged = h.api("/v1/skill-installations/plans", {
                "schema_version": "local-skill-install-stage-create/v1", "request_id": "is-" + "a" * 32,
                "grant_id": old["grant"]["grant_id"], "expected_revision": old["state_revision"],
                "instance_id": target["instance_id"], "directory_name": "update-fixture", "actor_id": "fixture-human"},
                expected=201)["plan"]
            installed = h.api("/v1/skill-installations/apply", {
                "schema_version": "local-skill-install-apply/v1", "plan_id": staged["plan_id"],
                "plan_signature": staged["signature"], "actor_id": "fixture-human", "confirm_install": True})
            install_id = installed["install_id"]
            new_source, new_route, candidate = imported_permission("b", "Updated report")
            candidate_id = candidate["grant"]["grant_id"]
            destination = Path(h.env["HERMES_HOME"]) / "skills" / "update-fixture"
            pairing = h.command([str(h.binary), "pair", "--port", h.endpoint.rsplit(":", 1)[1]])
            code = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing).group()
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000}, locale="zh-CN")
                errors, writes = [], []
                page.on("pageerror", lambda _: errors.append("pageerror"))
                page.on("request", lambda req: writes.append((req.url, req.post_data_json))
                        if req.method == "POST" and "/v1/skill-installations/" in req.url else None)
                page.goto(h.endpoint + "/installed-skills?install_id=" + install_id)
                page.get_by_label("配对码", exact=True).fill(code)
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                page.get_by_role("link", name="审阅候选并更新", exact=True).click()
                expect(page.get_by_role("heading", name="选择已导入的候选版本", exact=True)).to_be_visible()
                page.get_by_label("候选权限", exact=True).select_option(candidate_id)
                page.get_by_role("button", name="比较候选变化", exact=True).click()
                comparison = page.get_by_role("region", name="内容与权限差异", exact=True)
                expect(comparison).to_contain_text("SKILL.md")
                expect(comparison).to_contain_text("新增规则")
                expect(page.get_by_role("button", name="准备更新副本", exact=True)).to_be_disabled()
                fixture.require((destination / "SKILL.md").read_bytes() == (old_source / "SKILL.md").read_bytes(),
                                "review changed original files")
                checks["unapproved_candidate_is_review_only_with_content_and_permission_diff"] = True
                candidate = approve(new_route, candidate)
                page.get_by_role("button", name="比较候选变化", exact=True).click()
                prepare = page.get_by_role("button", name="准备更新副本", exact=True)
                expect(prepare).to_be_enabled()
                prepare.click()
                expect(page.get_by_role("heading", name="更新副本已准备", exact=True)).to_be_visible()
                update_id = parse_qs(urlparse(page.url).query)["update_id"][0]
                commit = page.get_by_role("button", name="确认更新 Skill", exact=True)
                expect(commit).to_be_disabled()
                checkbox = page.get_by_label("我已核对更新范围，确认按原计划执行", exact=True)
                expect(checkbox).to_be_enabled()
                checkbox.check()
                expect(commit).to_be_enabled()
                before_reload = len(writes)
                page.reload()
                expect(page.get_by_role("heading", name="更新副本已准备", exact=True)).to_be_visible()
                expect(checkbox).to_be_disabled()
                fixture.require(len(writes) == before_reload, "refresh performed an automatic write")
                checks["prepared_refresh_is_read_only_and_requires_review_again"] = True
                page.get_by_role("button", name="重新核对计划差异", exact=True).click()
                expect(comparison).to_contain_text("SKILL.md")
                expect(checkbox).to_be_enabled()
                page.screenshot(path=str(args.out_dir / "review-desktop.png"), full_page=True, animations="disabled")
                page.set_viewport_size({"width": 390, "height": 844})
                commit.scroll_into_view_if_needed()
                fixture.require(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "mobile overflow")
                expect(commit).to_be_in_viewport()
                page.screenshot(path=str(args.out_dir / "confirm-mobile.png"), animations="disabled")
                checks["desktop_and_mobile_review_keep_confirmation_visible"] = True
                page.set_viewport_size({"width": 1440, "height": 1000})
                posts = []

                def commit_and_lose(intercept):
                    posts.append(intercept.request.post_data_json)
                    response = intercept.fetch()
                    fixture.require(response.status == 200, "update failed")
                    fixture.require(response.json()["status"] == "updated_unverified", "update did not finish")
                    intercept.abort("connectionfailed")

                read_route = "**/v1/skill-installations/updates/" + update_id
                page.route("**/v1/skill-installations/updates", commit_and_lose)
                page.route(read_route, lambda intercept: intercept.fulfill(status=503, json={"error": "fixture_unavailable"}))
                checkbox.check()
                commit.evaluate("button => { button.click(); button.click(); }")
                expect(page.get_by_role("alert")).to_contain_text("当前结果无法确认")
                expect(page.get_by_role("button", name="确认更新 Skill", exact=True)).to_have_count(0)
                fixture.require(len(posts) == 1, "double click sent duplicate commit")
                checks["lost_commit_and_read_responses_clear_execution_without_replay"] = True
                page.unroute(read_route)
                page.get_by_role("button", name="重新查询原更新", exact=True).click()
                expect(page.get_by_role("heading", name="已记录新版文件发布完成", exact=True)).to_be_visible()
                fixture.require(len(posts) == 1, "query retried update")
                fixture.require((destination / "SKILL.md").read_bytes() == (new_source / "SKILL.md").read_bytes(),
                                "updated bytes mismatch")
                fixture.require(h.api(old_route)["grant"]["status"] == "revoked", "old authority remains")
                fixture.require(h.api(new_route)["grant"]["status"] == "approved", "new authority auto activated")
                fixture.require(not h.api("/v1/runtime-identities")["items"], "identity unexpectedly issued")
                checks["query_recovers_success_with_old_revoked_and_new_not_activated"] = True
                operation = h.api("/v1/skill-installations/updates/" + update_id)
                expected_link = "/grants?grant=" + candidate_id + "&install_id=" + operation["installation"]["install_id"]
                expect(page.get_by_role("link", name="查看新版并准备实例权限", exact=True)).to_have_attribute("href", expected_link)
                before_reload = len(writes)
                page.reload()
                expect(page.get_by_role("heading", name="已记录新版文件发布完成", exact=True)).to_be_visible()
                fixture.require(len(writes) == before_reload, "completed history repeated write")
                checks["completed_refresh_and_new_permission_link_are_correct"] = True
                page.unroute("**/v1/skill-installations/updates")
                # Prepare a second update, then exhaust private capacity after
                # declaration so the public recovery UI can abort before removal.
                _, third_route, third = imported_permission("c", "Third synthetic report")
                third = approve(third_route, third)
                next_install = operation["installation"]["install_id"]
                page.goto(h.endpoint + "/skill-updates?install_id=" + next_install)
                page.get_by_label("候选权限", exact=True).select_option(third["grant"]["grant_id"])
                page.get_by_role("button", name="比较候选变化", exact=True).click()
                page.get_by_role("button", name="准备更新副本", exact=True).click()
                expect(page.get_by_role("heading", name="更新副本已准备", exact=True)).to_be_visible()
                next_update = parse_qs(urlparse(page.url).query)["update_id"][0]
                stages = Path(h.env["SIQ_AGENT_SECURITY_STATE_DIR"]) / "skill-installations" / "stages"
                count = len(list(stages.iterdir()))
                for i in range(64 - count):
                    (stages / ("sip-" + f"{i:064x}")).mkdir()
                checkbox.check()
                page.get_by_role("button", name="确认更新 Skill", exact=True).click()
                expect(page.get_by_role("heading", name="已记录确认，等待准备新版", exact=True)).to_be_visible()
                before_reload = len(writes)
                page.reload()
                expect(page.get_by_role("heading", name="已记录确认，等待准备新版", exact=True)).to_be_visible()
                fixture.require(len(writes) == before_reload, "pending reload performed write")
                recovery = page.get_by_role("button", name="恢复未完成的更新", exact=True)
                expect(recovery).to_be_disabled()
                page.get_by_label("我已核对现场，确认恢复未完成操作", exact=True).check()
                recovery.click()
                expect(page.get_by_role("heading", name="已记录更新终止", exact=True)).to_be_visible()
                terminal = h.api("/v1/skill-installations/updates/" + next_update)
                fixture.require(terminal["status"] == "aborted" and terminal["removal"] is None, "unexpected abort scope")
                fixture.require((destination / "SKILL.md").read_bytes() == (new_source / "SKILL.md").read_bytes(),
                                "abort changed previous installation")
                fixture.require(h.api(new_route)["grant"]["status"] == "approved", "abort revoked previous permission")
                expect(recovery).to_have_count(0)
                checks["pending_refresh_and_explicit_recovery_preserve_previous_version"] = True
                fixture.require(not errors, "browser page error")
                browser.close()
            fixture.require(config.read_bytes() == before_config, "update changed host configuration")
            result = {"generated_at": datetime.now(UTC).isoformat(), "status": "passed", "checks": checks,
                      "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                      "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      "scope": "Real Chromium and isolated daemon/profile with synthetic Skills. Update review, explicit commit, lost response and abort recovery. No native platform update execution or cross-OS acceptance."}
            (args.out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"status": "passed", "checks": len(checks)}))
        finally:
            h.stop()


if __name__ == "__main__":
    main()
