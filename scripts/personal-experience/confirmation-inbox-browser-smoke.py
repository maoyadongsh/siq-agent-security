#!/usr/bin/env python3
"""Verify the confirmation inbox against an isolated daemon; calls are synthetic HTTP, not native execution."""

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import tempfile
from datetime import UTC, datetime
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
    checks = {}
    with tempfile.TemporaryDirectory(prefix="siq-confirmation-browser-") as temp:
        args.installer_managed_profile = True
        args.hermes_cli = Path(temp) / "unavailable-hermes-cli"
        h = fixture.Harness(Path(temp), args)
        h.config("optional")  # Explicit legacy HTTP fixture; managed/required authority has separate Go tests.
        shutil.copy2(args.binary, h.binary)
        try:
            h.start()
            decision_token = (h.state / "token").read_text().strip()
            skill = REPO / "apps/agentshield/internal/admission/testdata/skills/benign/official-like"
            admission = h.api("/v1/admit", {"path": str(skill)})["admission"]
            created = h.api(
                "/v1/grants",
                {"admission_id": admission["admission_id"], "platform": "openclaw", "subject_id": "inbox-fixture"},
            )
            grant_id = created["grant"]["grant_id"]
            route = "/v1/grants/" + grant_id
            challenge = h.api(route + "/challenge", {"expected_revision": created["state_revision"]})["challenge"]
            approved = h.api(
                route + "/approve",
                {
                    "expected_revision": created["state_revision"],
                    "actor_id": "fixture-human",
                    "challenge_id": challenge["challenge_id"],
                    "nonce": challenge["nonce"],
                },
            )
            h.api(route + "/deploy", {"expected_revision": approved["state_revision"], "actor_id": "fixture-human"})
            pending = h.api(
                "/v1/grants",
                {
                    "admission_id": admission["admission_id"],
                    "platform": "hermes",
                    "subject_id": "pending-permissions-fixture",
                },
            )["grant"]

            def held(name):
                request = {
                    "platform": "openclaw",
                    "agent_id": "inbox-fixture",
                    "session_id": "session-" + name,
                    "tool_call_id": "call-" + name,
                    "tool": "exec",
                    "params": {"command": "printf synthetic-" + name},
                }
                decision = h.api("/v1/decide", request, token=decision_token)
                fixture.require(decision["action"] == "hold", "expected synthetic held call")
                item = next(
                    i for i in h.api("/v1/confirmations")["items"] if i["decision_receipt_id"] == decision["receipt_id"]
                )
                return request, item

            def resolve(item, approve, expected=200):
                return h.api(
                    "/v1/confirmations/" + item["action_id"] + "/resolve",
                    {
                        "schema_version": "local-confirmation-resolve/v1",
                        "decision_receipt_id": item["decision_receipt_id"],
                        "decision_hash": item["decision_hash"],
                        "params_digest": item["params_digest"],
                        "approve": approve,
                        "actor_id": "second-fixture-human",
                    },
                    expected=expected,
                )

            first_request, first = held("approve")
            deny_request, deny = held("deny")
            _, stale = held("stale")
            _, offline = held("offline")
            pairing = h.command([str(h.binary), "pair", "--port", h.endpoint.rsplit(":", 1)[1]])
            pairing_code = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing).group()
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1100})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda _: errors.append("pageerror"))
                cdp = context.new_cdp_session(page)
                cdp.send(
                    "Browser.setPermission",
                    {"permission": {"name": "notifications"}, "setting": "denied", "origin": h.endpoint},
                )
                page.goto(h.endpoint + "/confirmations")
                fixture.require(
                    page.evaluate("Notification.permission") == "denied", "notification permission fixture failed"
                )
                page.get_by_label("配对码", exact=True).fill(pairing_code)
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                expect(page.get_by_role("heading", name="运行操作 · 4 项待确认", exact=True)).to_be_visible()
                fixture.require(
                    all(i["status"] == "pending" for i in h.api("/v1/confirmations")["items"]),
                    "opening inbox approved calls",
                )
                checks["opening_inbox_does_not_approve"] = True

                def open_item(item):
                    page.goto(h.endpoint + "/confirmations?request=" + item["action_id"])
                    expect(page.get_by_role("heading", name="确认操作：exec", exact=True)).to_be_visible()
                    expect(page.get_by_text(item["session_id"], exact=True)).to_be_visible()

                open_item(first)
                approve_button = page.get_by_role("button", name="批准本次请求", exact=True)
                expect(approve_button).to_be_disabled()
                page.get_by_label("我已核对本次操作和参数摘要", exact=True).check()
                approve_button.click()
                expect(page.get_by_role("status").filter(has_text="已批准本次请求")).to_be_visible()
                expect(approve_button).to_have_count(0)
                resolve(first, True, expected=409)
                status = h.api(
                    "/v1/hold-status",
                    {
                        **first_request,
                        "action_id": first["action_id"],
                        "decision_receipt_id": first["decision_receipt_id"],
                    },
                    token=decision_token,
                )
                fixture.require(status["status"] == "approved", "UI approval absent from execution status")
                checks["explicit_review_records_one_approval_and_hides_controls"] = True
                checks["approval_replay_conflicts"] = True

                open_item(deny)
                page.get_by_role("button", name="拒绝本次请求", exact=True).click()
                expect(page.get_by_role("status").filter(has_text="已拒绝本次请求")).to_be_visible()
                expect(page.get_by_role("button", name="批准本次请求", exact=True)).to_have_count(0)
                status = h.api(
                    "/v1/hold-status",
                    {
                        **deny_request,
                        "action_id": deny["action_id"],
                        "decision_receipt_id": deny["decision_receipt_id"],
                    },
                    token=decision_token,
                )
                fixture.require(status["status"] == "denied", "denial not reflected")
                checks["denial_visible_to_runtime_and_no_approve_control"] = True

                open_item(stale)
                page.get_by_label("我已核对本次操作和参数摘要", exact=True).check()

                # Resolve during the browser POST to deterministically exercise its 409 readback.
                def concurrent_resolution(route):
                    resolve(stale, False)
                    route.continue_()

                pattern = "**/v1/confirmations/" + stale["action_id"] + "/resolve"
                page.route(pattern, concurrent_resolution)
                page.get_by_role("button", name="批准本次请求", exact=True).click()
                expect(page.get_by_role("status").filter(has_text="没有重复批准")).to_be_visible()
                expect(page.get_by_role("button", name="批准本次请求", exact=True)).to_have_count(0)
                page.unroute(pattern, concurrent_resolution)
                checks["concurrent_resolution_conflict_refreshes_state"] = True

                open_item(offline)
                pattern = "**/v1/confirmations"

                def disconnected(route):
                    route.fulfill(status=503, content_type="application/json", body='{"error":"fixture_unavailable"}')

                page.route(pattern, disconnected)
                page.get_by_role("button", name="刷新待办", exact=True).click()
                expect(page.get_by_role("alert").filter(has_text="连接恢复前暂停确认")).to_be_visible()
                expect(page.get_by_role("button", name="批准本次请求", exact=True)).to_have_count(0)
                page.unroute(pattern, disconnected)
                page.get_by_role("button", name="刷新待办", exact=True).click()
                expect(page.get_by_role("button", name="批准本次请求", exact=True)).to_be_visible()
                checks["disconnect_disables_actions_and_refresh_recovers"] = True

                page.set_viewport_size({"width": 390, "height": 844})
                page.get_by_label("我已核对本次操作和参数摘要", exact=True).check()
                approve_button = page.get_by_role("button", name="批准本次请求", exact=True)
                approve_button.scroll_into_view_if_needed()
                box = approve_button.bounding_box()
                fixture.require(
                    box and box["x"] >= 0 and box["x"] + box["width"] <= 390, "mobile action outside viewport"
                )
                fixture.require(
                    page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"),
                    "mobile horizontal overflow",
                )
                page.screenshot(path=str(args.out_dir / "inbox-mobile.png"))
                checks["mobile_details_and_actions_fit_viewport"] = True

                page.set_viewport_size({"width": 1440, "height": 1100})
                page.get_by_role("link", name="Hermes · pending-permissions-fixture · 审阅权限", exact=True).click()
                expect(page.get_by_role("heading").filter(has_text=pending["grant_id"])).to_be_visible()
                fixture.require(
                    h.api("/v1/grants/" + pending["grant_id"])["grant"]["status"] == "pending_approval",
                    "deep link approved permissions",
                )
                checks["long_term_permissions_open_exact_unapproved_grant"] = True
                page.goto(h.endpoint + "/receipts")
                page.get_by_role("link", name="查看确认状态", exact=True).first.click()
                expect(page.get_by_role("heading", name="确认操作：exec", exact=True)).to_be_visible()
                checks["receipt_history_links_to_confirmation_details"] = True
                page.get_by_label("同时显示近期已处理和过期请求", exact=True).check()
                page.screenshot(path=str(args.out_dir / "inbox-desktop.png"), full_page=True)
                fixture.require(not errors, "browser runtime errors")
                checks["no_browser_runtime_errors"] = True
                all_receipts = h.receipts()
                fixture.require(
                    sum(r.get("record_type") == "hold_resolution" for r in all_receipts) == 3,
                    "unexpected extra resolutions",
                )
                checks["only_three_expected_signed_resolution_receipts"] = True
                checks["notification_permission_denial_does_not_block_inbox"] = True
                open_item(offline)
                page.clock.install()
                page.clock.fast_forward(120000)
                expect(page.get_by_role("button", name="批准本次请求", exact=True)).to_have_count(0)
                checks["client_deadline_disables_stale_approval_without_waiting_for_poll"] = True
                browser.close()
        finally:
            h.stop()
    report = {
        "schema_version": "personal-confirmation-inbox-browser/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "passed": True,
        "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "checks": checks,
        "scope": (
            "Linux Chromium with isolated real daemon; synthetic legacy optional-Intent OpenClaw HTTP calls, "
            "no native agent/tool execution or system notification validation"
        ),
    }
    (args.out_dir / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
