#!/usr/bin/env python3
"""R07: full user journey across the local browser console, real daemon and real OpenClaw host.

The journey runs against the real daemon binary, the real OpenClaw host process
and the embedded local console UI (Playwright, headless Chromium):

  1. install/start/pair            — daemon health + admin pairing from the UI
  2. UI, discover agents           — /bindings shows the real OpenClaw instance
  3. confirm access                — /grants shows the deployed V1 grant
  4. real host allowed action      — SEC + native read with verified attribution
  5. overreach; UI consistent      — missing-authority call denied fail-closed,
                                     /receipts renders the same deny decision
  6. approvals into SIQ            — sensitive call held by the grant authority,
                                     approved in the UI, replay resolve rejected
  7. Skill V1→cancel→confirm V2    — the full L2 update leg (r04) re-run on the
                                     same daemon, host and model fixture
  8. interrupt service             — daemon restart; UI session invalidated,
                                     pairing retried and re-paired by keyboard
  9. track tasks/receipts          — /receipts and /activities render post-recovery
 10. raw content default off       — opt-in raw-content store stays off until
                                     explicitly enabled in /settings
 11. responsive widths; uninstall  — 390×844 console usable; adapter uninstalled
                                     via /bindings while host config is preserved
 12. logout                        — 退出管理 returns the console to pairing state

A local deterministic model fixture chooses the tool calls; no external or paid
model is contacted. The automated browser operator is not human acceptance.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location(
    "r07_r04_openclaw_native_update", REPO / "scripts/personal-experience/r04-openclaw-native-update-smoke.py"
)
r04 = importlib.util.module_from_spec(loader)
loader.loader.exec_module(r04)
export_loader = importlib.util.spec_from_file_location(
    "r07_b04_export_review", REPO / "scripts/personal-experience/closure-b04-export-runner.py"
)
export_review = importlib.util.module_from_spec(export_loader)
export_loader.loader.exec_module(export_review)
fixture = r04.fixture
require = fixture.require
canonical_hash = r04.canonical_hash


def failure_diagnostics(error, harness):
    """Keep exception payloads out of public evidence, even when truncated.

    Check IDs/status and wait markers are authored by this harness; exception
    messages may contain HTTP bodies, credentials, paths, or browser content.
    """
    checks = [{"id": item["id"], "status": item["status"]}
              for item in getattr(harness, "journey_results", [])]
    return {"passed": False, "error_type": type(error).__name__,
            "failed_check_ids": [item["id"] for item in checks if item["status"] == "fail"],
            "last_wait": getattr(harness, "current_wait", None), "checks": checks}


class Harness(r04.Harness):
    def setup_authority(self):
        super().setup_authority()
        self.current_install = self.skill_installation["install_id"]
        self.steps = []
        self.calls_issued = []
        self.session_override = None
        self.override_steps = []
        self.model_failures, self.model_requests_seen = [], []
        self._model = None
        self.journey_results = []
        self.current_wait = None

    def mark(self, step, category, state="visible"):
        """Record the fixed wait-point identity for failure diagnostics. Only
        static step IDs and locator categories are allowed here — never input
        values, pairing codes, grant IDs or page text."""
        self.current_wait = {"journey_step": step, "wait_target": {"category": category, "state": state}}

    def verify_native_task_exports(self, task_id):
        """Check the real OpenClaw task's signed exports after native capture."""
        self.mark("step10_native_task_exports", "api:task_export", "verified")
        page = self.api("/v1/task-activities?limit=100")
        items = [item for item in page["items"]
                 if item.get("binding", {}).get("task_id") == task_id
                 and item.get("binding", {}).get("platform") == "openclaw"]
        require(len(items) == 1 and page["next_offset"] is None,
                "native OpenClaw task activity missing or ambiguous")
        item = items[0]
        route = "/v1/task-activities/" + item["activity_id"]
        query = "?snapshot=" + page["snapshot"]
        detail = self.api(route + query)
        expected = [(row["seq"], row["hash"]) for row in detail["receipts"]]
        require(detail["next_offset"] is None and bool(expected),
                "native OpenClaw task activity has no complete receipt slice")
        trusted_key = self.command([str(self.binary), "pubkey"]).strip()
        for kind in ("export", "trace-export"):
            target = route + "/" + kind + query
            document = self.api(target)
            require(
                document["activity_id"] == item["activity_id"]
                and document["snapshot"] == page["snapshot"]
                and [(row["seq"], row["source_hash"]) for row in document["receipts"]] == expected
                and export_review.verify_export(document, trusted_key),
                "native OpenClaw task " + kind + " scope/signature mismatch",
            )
            if kind == "trace-export":
                require(all((row["seq"], row["receipt_hash"]) in expected
                            for row in document["sources"]),
                        "native OpenClaw trace sources crossed the task receipt slice")
            serialized = json.dumps(document, ensure_ascii=False)
            require(
                "raw-task-content" not in serialized
                and '"ciphertext"' not in serialized
                and "fixture-visible-company-a" not in serialized
                and self.admin not in serialized,
                "native OpenClaw task " + kind + " leaked raw store or credential",
            )
            injected = self.api(target + "&task_id=foreign", expected=400)
            require(injected.get("error") == "task_activity_query_invalid",
                    "native OpenClaw task export accepted caller-selected scope")
        return len(expected)

    def verify_two_native_task_exports(self, first_task, second_task, first_session,
                                       second_session, second_raw_count=0):
        """Bind two real OpenClaw tasks to disjoint signed export slices."""
        self.mark("step10_native_two_task_exports", "api:task_export", "verified")
        require(first_task != second_task and first_session != second_session,
                "native OpenClaw tasks reused a task or session identity")
        page = self.api("/v1/task-activities?limit=100")
        require(page["next_offset"] is None, "native OpenClaw activity page truncated")
        trusted_key = self.command([str(self.binary), "pubkey"]).strip()
        groups = []
        for task, other_task, other_session in (
            (first_task, second_task, second_session),
            (second_task, first_task, first_session),
        ):
            matches = [row for row in page["items"]
                       if row.get("binding", {}).get("platform") == "openclaw"
                       and row.get("binding", {}).get("task_id") == task]
            require(len(matches) == 1, "native OpenClaw task activity missing or ambiguous")
            item = matches[0]
            route = "/v1/task-activities/" + item["activity_id"]
            query = "?snapshot=" + page["snapshot"]
            detail = self.api(route + query)
            expected = [(row["seq"], row["hash"]) for row in detail["receipts"]]
            require(detail["next_offset"] is None and bool(expected),
                    "native OpenClaw task receipt slice incomplete")
            groups.append(set(expected))
            for kind in ("export", "trace-export"):
                target = route + "/" + kind + query
                document = self.api(target)
                require(document["activity_id"] == item["activity_id"]
                        and document["snapshot"] == page["snapshot"]
                        and [(row["seq"], row["source_hash"]) for row in document["receipts"]] == expected
                        and export_review.verify_export(document, trusted_key),
                        "native OpenClaw A/B " + kind + " scope/signature mismatch")
                if kind == "trace-export":
                    require(all((row["seq"], row["receipt_hash"]) in groups[-1]
                                for row in document["sources"]),
                            "native OpenClaw A/B trace sources crossed receipt slice")
                serialized = json.dumps(document, ensure_ascii=False)
                require(other_task not in serialized and other_session not in serialized
                        and "native-b-canary" not in serialized
                        and "raw-task-content" not in serialized
                        and '"ciphertext"' not in serialized
                        and self.admin not in serialized,
                        "native OpenClaw A/B export leaked another task or raw content")
                for credential, status in (("", 401),
                                           (Path(self.issued["credential_path"]).read_text().strip(), 401),
                                           ((self.state / "token").read_text().strip(), 403)):
                    denied = self.api(target, token=credential, expected=status)
                    require("receipts" not in denied and "sources" not in denied,
                            "unprivileged native OpenClaw export returned task contents")
                injected = self.api(target + "&task_id=foreign", expected=400)
                require(injected.get("error") == "task_activity_query_invalid",
                        "native OpenClaw export accepted caller-selected task scope")
        require(not groups[0].intersection(groups[1]),
                "native OpenClaw A/B tasks shared a signed receipt")
        first_records = self.api("/v1/raw-task-content/records/search",
                                 {"schema_version": "local-raw-task-content-record-list/v1",
                                  "task_id": first_task})["items"]
        second_records = self.api("/v1/raw-task-content/records/search",
                                  {"schema_version": "local-raw-task-content-record-list/v1",
                                   "task_id": second_task})["items"]
        require(len(first_records) == 2 and len(second_records) == second_raw_count,
                "native OpenClaw task B raw capture count differs from its grant")
        if second_raw_count:
            require({row["kind"] for row in second_records} == {"parameters", "output"},
                    "native OpenClaw task B did not capture both supported kinds")
        denied_read = self.api(
            "/v1/raw-task-content/records/" + first_records[0]["record_id"] + "/read",
            {"schema_version": "local-raw-task-content-record-read/v1", "task_id": second_task},
            expected=503,
        )
        require(denied_read.get("error") == "raw_task_content_unavailable"
                and "fields" not in denied_read,
                "native OpenClaw task B selected A's raw record")
        return [len(group) for group in groups]

    def check_raw_content_default_disabled(self):
        """Store-level default, asserted on the fresh daemon BEFORE the managed
        fixture chain opts the store in (setup_authority activates it for the
        nested L2 leg's per-task native captures). Returns the result dict for
        main() to append after setup_authority resets journey_results."""
        status = self.api("/v1/raw-task-content/status")
        require(
            status["status"] == "disabled" and status["default_capture"] is False,
            "raw-content store default state: " + json.dumps(status, ensure_ascii=False),
        )
        activation = self.api("/v1/raw-task-content/activation", expected=404)
        return {
            "id": "r07_step10a_raw_content_store_default_disabled",
            "expectation": "a fresh daemon keeps the raw-content store disabled until an explicit signed activation: status=disabled, default_capture=false, activation record absent (404)",
            "actual": "status=disabled default_capture=false activation=404 reason="
            + str(activation.get("reason_code", activation.get("error", ""))),
            "status": "pass",
            "evidence_level": "controlled",
        }

    def _start_model(self):
        # update_and_run() rebinds fresh accounting lists on every call. The
        # journey reuses one model server across phases so the request
        # accounting stays global and the final leg's count check holds.
        if self._model is not None:
            return self._model
        self._model = super()._start_model()
        return self._model

    def _reset_model(self):
        # Phase A and the r04 leg must not share one model-server transcript
        # accounting: the r04 V2 leg talks through an explicit fresh OpenClaw
        # session on the same override transcript, and phase A's leftover
        # expected-result entries would skew its counts. Stop the fixture
        # server and clear the turn accounting so phase B is validated on its
        # own, exactly like the standalone r04 run.
        if self._model is not None:
            server, _thread = self._model
            server.shutdown()
            server.server_close()
            self._model = None
        self.override_steps = []
        self.steps = []

    def record(self, check_id, expectation, ok, actual, evidence="controlled"):
        self.journey_results.append({
            "id": check_id, "expectation": expectation, "actual": actual,
            "status": "pass" if ok else "fail", "evidence_level": evidence,
        })
        require(ok, check_id + ": " + actual)

    def pair_code(self):
        pairing = self.command([str(self.binary), "pair", "--port", str(self.endpoint.rsplit(":", 1)[1])])
        match = re.search(r"\b[0-9a-f]{4}(?:-[0-9a-f]{4}){3}\b", pairing)
        require(match is not None, "pair CLI did not return a valid code")
        return match.group(0)

    def grant_action(self, grant_path, name, **body):
        return self.api(
            grant_path + "/" + name,
            {"expected_revision": body.pop("revision"), "actor_id": "automated-fixture-operator", **body},
        )

    def debug_dump(self, page, name, error):
        # Never persist DOM, screenshots, response bodies or daemon output:
        # these can contain pairing codes, bearer credentials and raw content.
        # Only fixed phase/step identifiers and locator categories are recorded.
        dump = getattr(self, "debug_directory", None)
        if dump is None:
            dump = Path(tempfile.mkdtemp(prefix="siq-r07-diagnostics-"))
            self.debug_directory = dump
        target = dump / (name + ".json")
        with target.open("x", encoding="utf-8") as handle:
            target.chmod(0o600)
            diagnostic = {"phase": name, "error_type": type(error).__name__,
                          "checks_completed": len(self.journey_results)}
            if (wait := getattr(self, "current_wait", None)) is not None:
                diagnostic["last_wait"] = wait
            json.dump(diagnostic, handle)
        raise error

    def goto_until(self, page, url, locator, timeout=15000, *, step=None, category=None):
        # One navigation only. A stalled load is a failure, never a retry success.
        if step is not None:
            self.mark(step, category or "locator", "visible")
        page.goto(url)
        locator.wait_for(state="visible", timeout=timeout)

    def guard_reload_regression(self):
        """Delay real responses; never fabricate API payloads or retry navigation."""
        from playwright.sync_api import expect, sync_playwright

        results = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for route in ("grants", "receipts", "findings", "permissions"):
                    context = browser.new_context()
                    context.add_init_script("""
                        window.__guardTarget = """ + json.dumps("/v1/" + route) + """;
                        window.__guardStarted = false;
                        const original = window.fetch;
                        window.fetch = async function(input, options) {
                            const url = new URL(typeof input === 'string' ? input : input.url, location.href);
                            const response = await original.call(this, input, options);
                            if (url.pathname === window.__guardTarget) {
                                window.__guardStarted = true;
                                await new Promise(resolve => setTimeout(resolve, 800));
                            }
                            if (url.pathname === '/v1/status') {
                                const deadline = Date.now() + 2000;
                                while (!window.__guardStarted && Date.now() < deadline)
                                    await new Promise(resolve => setTimeout(resolve, 10));
                            }
                            return response;
                        };
                    """)
                    page = context.new_page()
                    page.goto(self.endpoint + "/" + route)
                    page.get_by_label("配对码", exact=True).fill(self.pair_code())
                    page.get_by_role("button", name="建立管理会话", exact=True).click()
                    expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                    expect(page.locator(".table-empty").first).to_be_visible()
                    expect(page.get_by_text("加载中…", exact=True)).to_have_count(0, timeout=6000)
                    require(page.evaluate("window.__guardStarted"), "delayed real endpoint was not exercised")
                    results.append({"route": route, "passed": True, "navigation_count": 1})
                    context.close()
            finally:
                browser.close()
        return {"passed": True, "results": results,
                "binary_sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest(),
                "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}

    def journey(self):
        from playwright.sync_api import expect, sync_playwright

        # B02 embeds this journey with its own Namespace; the retention seed
        # flag belongs only to the standalone R07 CLI and defaults to off.
        retention_seed_enabled = bool(getattr(self.args, "retain_state_dir", None))

        view = self.api("/v1/skill-installations/operations/" + self.current_install)
        grant_id = view["plan"]["grant_id"]

        # Journey step 1: real daemon serving the console, ready instance state.
        health = self.api("/healthz/instance")
        self.record(
            "r07_step1_daemon_health_paired",
            "real daemon reports the SIQ product identity with a ready local instance",
            health.get("product") == "siq-agent-security" and health.get("status") == "ready"
            and health.get("local_mode") is True
            and health.get("schema_version") == "local-service-instance-health/v1",
            "product=" + str(health.get("product")) + " status=" + str(health.get("status"))
            + " local_mode=" + str(health.get("local_mode")) + " state_directory_id="
            + str(health.get("state_directory_id"))[:16] + "…",
        )

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 1100}, locale="zh-CN")
                # JS-side fetch hook: the Playwright response listener misses
                # responses (run 17 network log), and it cannot record a
                # request that is still pending or a client-side abort — this
                # hook records every fetch outcome as the page sees it.
                context.add_init_script(
                    "window.__fetchLog = [];\n"
                    "const __origFetch = window.fetch;\n"
                    "window.fetch = function() {\n"
                    "  const input = arguments[0];\n"
                    "  const url = typeof input === 'string' ? input : (input && input.url) || String(input);\n"
                    "  const note = (line) => { window.__fetchLog.push(line);\n"
                    "    if (window.__fetchLog.length > 600) window.__fetchLog.shift(); };\n"
                    "  return __origFetch.apply(this, arguments).then(\n"
                    "    (resp) => { note(resp.status + ' ' + url); return resp; },\n"
                    "    (err) => { note('ERR ' + ((err && err.message) || String(err)) + ' ' + url); throw err; });\n"
                    "};\n"
                )
                page = context.new_page()
                page_errors = []
                page.on("pageerror", lambda _: page_errors.append("pageerror"))
                network_log = []
                self._network_log = network_log
                page.on("response", lambda r: network_log.append(str(r.status) + " " + r.url)
                        if "/v1/" in r.url else None)
                page.on("requestfailed", lambda r: network_log.append("FAILED " + r.url + " " + str(r.failure))
                        if "/v1/" in r.url else None)

                # Journey step 2: pair the console from the browser, including a
                # wrong-code retry before the real code.
                page.goto(self.endpoint + "/overview")
                self.mark("step2_pairing_form", "role:heading")
                expect(page.get_by_role("heading", name="连接你的本地管理台")).to_be_visible()
                self.mark("step2_pairing_code_input", "label:textbox", "editable")
                page.get_by_label("配对码", exact=True).fill("wrong")
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                self.mark("step2_wrong_code_alert", "role:alert", "contains_text")
                expect(page.get_by_role("alert")).to_contain_text("配对码无效")
                self.mark("step2_pairing_code_input", "label:textbox", "editable")
                page.get_by_label("配对码", exact=True).fill(self.pair_code())
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                self.mark("step2_session_established", "role:button")
                expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                self.record(
                    "r07_step2_ui_pairing_with_wrong_code_retry",
                    "browser console pairs with a fresh pairing code after an invalid-code retry",
                    not page_errors,
                    "paired=true pageerrors=" + str(len(page_errors)),
                )

                # Journey step 2b: the console discovers the real OpenClaw instance.
                openclaw_row = page.get_by_role("row").filter(has_text="OpenClaw")
                self.goto_until(page, self.endpoint + "/bindings", openclaw_row.first,
                                step="step2b_bindings_openclaw_row", category="role:row")
                expect(openclaw_row.first).to_contain_text("发现安装文件")
                self.record(
                    "r07_step2_ui_bindings_discovers_openclaw",
                    "console /bindings lists the real OpenClaw instance with its discovered adapter files",
                    not page_errors,
                    "row_visible=true adapter_label=发现安装文件",
                )

                # Journey step 3: the deployed V1 grant is visible in the
                # console, using a single navigation after the product load fix.
                grant_row = page.get_by_role("row").filter(has_text=grant_id).first
                self.goto_until(page, self.endpoint + "/grants", grant_row,
                                step="step3_grants_grant_row", category="role:row")
                self.record(
                    "r07_step3_ui_grants_shows_v1_grant",
                    "console /grants shows the deployed V1 grant by its full grant id",
                    not page_errors,
                    "grant_id=" + grant_id,
                )

                # Journey steps 4+5 run on the real host in an explicit journey
                # session so the later r04 leg's default session stays unenrolled.
                self.session_override = "r07-journey-phase-a"
                self._start_model()
                self.native_turn()
                self.native_turn()
                before = len(self.receipts())
                self.native_turn(self.read_call("r07-pre-sec", expect="deny"))
                pre = self.decision_for(before, "r07-pre-sec")
                self.record(
                    "r07_step5_missing_authority_denied_fail_closed",
                    "native read without an issued execution context is denied fail-closed (no silent allow)",
                    pre["action"] == "deny",
                    "action=" + pre["action"] + " reason_code=" + str(pre.get("reason_code")),
                )
                deny_marker = (pre.get("reason") or pre.get("reason_code") or "")[:24]
                require(deny_marker, "deny receipt carries no reason to correlate against the UI")
                deny_row = page.get_by_role("row").filter(has_text=deny_marker)
                self.goto_until(page, self.endpoint + "/receipts", deny_row.first,
                                step="step5_receipts_deny_row", category="role:row")
                expect(deny_row.first).to_contain_text("拒绝")
                self.record(
                    "r07_step5_ui_receipts_consistent_with_deny",
                    "console /receipts shows the same deny decision (action 拒绝 + matching reason) as the API receipt",
                    not page_errors,
                    "reason_prefix=" + deny_marker,
                )

                sec = self.issue_session_context(pre["session_id"])
                self.record(
                    "r07_step4_sec_issued_for_real_session",
                    "admin issues a signed session execution context for the real OpenClaw session",
                    bool(sec.get("context_id")),
                    "context_id=" + str(sec.get("context_id"))[:16] + "…",
                )
                raw_binding = next(item for item in self.api("/v1/intent-bindings")["items"]
                                   if item["session_id"] == pre["session_id"])
                raw_task = raw_binding["task_id"]
                raw_search = {"schema_version": "local-raw-task-content-record-list/v1", "task_id": raw_task}
                require(self.api("/v1/raw-task-content/records/search", raw_search)["items"] == [],
                        "raw capture occurred before explicit task grant")
                raw_grant = self.api("/v1/raw-task-content/grants", {
                    "schema_version": "local-raw-task-content-grant-create/v1", "task_id": raw_task,
                    "kinds": ["parameters", "output"], "actor_id": "automated-fixture-operator",
                    "duration_seconds": 3600, "retention_seconds": 3600, "max_plaintext_bytes": 65536,
                }, expected=201)
                before = len(self.receipts())
                self.native_turn(self.read_call("r07-allow-read", expect="allow"))
                row = self.decision_for(before, "r07-allow-read")
                attribution = row.get("skill_attribution") or {}
                self.record(
                    "r07_step4_allow_read_with_session_attribution",
                    "real-host read allowed with verified controlled_session attribution bound to the issued SEC",
                    row["action"] == "allow" and attribution.get("status") == "verified"
                    and attribution.get("evidence_level") == "controlled_session"
                    and attribution.get("context_id") == sec["context_id"],
                    "action=" + row["action"] + " attribution=" + json.dumps(attribution)[:220],
                )
                self.record(
                    "r07_step4_call_binding_recomputed",
                    "controlled-session call binding matches the canonical hash of the real call",
                    attribution.get("call_binding") == canonical_hash(
                        {"platform": row["platform"], "session_id": row["session_id"],
                         "agent_id": row["agent_id"], "task_id": "-", "tool": row["tool"],
                         "tool_call_id": row["tool_call_id"], "params": self.read_call("r07-allow-read")["params"]}
                    ),
                    "call_binding=" + str(attribution.get("call_binding"))[:16] + "…",
                )
                sec_read = self.api("/v1/skill-contexts/" + sec["context_id"])
                grant_doc = self.api("/v1/grants/" + grant_id)["grant"]
                relations_ok, relations_detail = self.attribution_relations(sec_read, row, grant_doc, view)
                self.record(
                    "r07_step4_attribution_correlates_grant_install_sec",
                    "install record, runtime identity, grant document, SEC and receipt correlate field-by-field: one grant id across all five, SEC pins the install claim signature and the real subject, receipt attribution copies the SEC skill/content hash, SEC authority grant digest recomputes from the live grant document",
                    relations_ok and bool(self.skill_installation["source_digest"]),
                    relations_detail + " matched_grant_id=" + str(row.get("matched_grant_id"))
                    + " content_hash=" + str(attribution.get("content_hash"))[:16] + "…",
                )
                mismatch_ok, mismatch_detail = self.attribution_mismatch_negative(sec_read, row, grant_doc, view)
                self.record(
                    "r07_step4_attribution_digest_mismatch_detected",
                    "tampering any one side's digest (grant document, SEC install pin, install claim signature, receipt content hash) is detected by the relation check",
                    mismatch_ok,
                    mismatch_detail,
                )
                tampered_signature = "0" * 128 if sec_read["signature"] != "0" * 128 else "1" * 128
                tamper_reject = self.api(
                    "/v1/skill-contexts/" + sec["context_id"] + "/revoke",
                    {"schema_version": "local-skill-execution-context-revoke/v1",
                     "expected_context_signature": tampered_signature,
                     "actor_id": "automated-fixture-operator", "confirm_revoke": True},
                    expected=409,
                )
                sec_reread = self.api("/v1/skill-contexts/" + sec["context_id"])
                self.record(
                    "r07_step4_tampered_sec_revoke_rejected",
                    "revoking the SEC with a tampered expected signature is refused 409 skill_context_changed and the signed context is unchanged",
                    tamper_reject.get("error") == "skill_context_changed"
                    and sec_reread.get("signature") == sec_read["signature"],
                    "http=409 error=" + str(tamper_reject.get("error"))
                    + " context_unchanged=" + str(sec_reread.get("signature") == sec_read["signature"]),
                )
                # Journey step 6: a sensitive call is held by the deployed grant
                # authority, approved in the UI, and the replayed resolve is rejected.
                captured = self.api("/v1/raw-task-content/records/search", raw_search)["items"]
                require(len(captured) == 2 and {item["kind"] for item in captured} == {"parameters", "output"},
                        "native capture did not produce the explicitly authorized pair")
                native_export_receipts = self.verify_native_task_exports(raw_task)
                self.record(
                    "r07_step10_native_task_exports_signed_scoped_and_raw_free",
                    "the real OpenClaw task's signed export and trace-export match its receipt slice, exclude raw storage and credentials, and reject caller-selected task scope",
                    native_export_receipts > 0,
                    "signed_exports=2 task_receipts=" + str(native_export_receipts)
                    + " caller_scope_injection=400",
                )
                first_session, first_steps = self.session_override, self.override_steps
                second_session = "r07-journey-phase-b"
                second_path = self.workspace / "company-a/native-task-b.txt"
                second_path.write_text("fixture-visible-company-a native-b-canary\n")
                self.session_override, self.override_steps = second_session, []
                try:
                    self.native_turn()
                    self.native_turn()
                    before = len(self.receipts())
                    self.native_turn(self.read_call("r07-b-pre-sec", expect="deny"))
                    second_pre = self.decision_for(before, "r07-b-pre-sec")
                    require(second_pre["action"] == "deny",
                            "second native task ran before its independent SEC")
                    second_sec = self.issue_session_context(second_pre["session_id"])
                    second_bindings = [item for item in self.api("/v1/intent-bindings")["items"]
                                       if item.get("session_id") == second_pre["session_id"]]
                    require(len(second_bindings) == 1,
                            "second native OpenClaw task binding missing or ambiguous")
                    second_task = second_bindings[0]["task_id"]
                    if retention_seed_enabled:
                        second_raw_grant = self.api("/v1/raw-task-content/grants", {
                            "schema_version": "local-raw-task-content-grant-create/v1",
                            "task_id": second_task, "kinds": ["parameters", "output"],
                            "actor_id": "automated-fixture-operator",
                            "duration_seconds": 86400, "retention_seconds": 86400,
                            "max_plaintext_bytes": 65536,
                        }, expected=201)
                    second_call = {"id": "r07-b-allow", "tool": self.read_tool,
                                   "params": {"path": str(second_path)}, "expect": "allow"}
                    before = len(self.receipts())
                    self.native_turn(second_call)
                    second_row = self.decision_for(before, second_call["id"])
                    require(second_row["action"] == "allow"
                            and second_row.get("skill_attribution", {}).get("status") == "verified"
                            and second_row["skill_attribution"]["context_id"] == second_sec["context_id"],
                            "second native OpenClaw task did not run with independent SEC")
                    expires_at = datetime.fromisoformat(raw_grant["expires_at"].replace("Z", "+00:00"))
                    require(datetime.now(UTC) < expires_at,
                            "first task raw Grant expired before second native task completed")
                    joint_counts = self.verify_two_native_task_exports(
                        raw_task, second_task, pre["session_id"], second_pre["session_id"],
                        second_raw_count=2 if retention_seed_enabled else 0)
                    self.record(
                        "r07_step10_two_native_tasks_signed_exports_and_raw_isolation",
                        "while A's raw Grant is live, independent OpenClaw task B reads under its own SEC; A/B signed exports have disjoint receipt slices, cross-task raw read and unprivileged export are denied; B raw capture follows its own opt-in only",
                        all(joint_counts),
                        "native_tasks=2 signed_exports=4 receipt_counts=" + str(joint_counts)
                        + " A_grant_live_at_B_completion=true A_raw_records=2 B_raw_records="
                        + str(2 if retention_seed_enabled else 0)
                        + " cross_task_read=503",
                    )
                finally:
                    self.session_override, self.override_steps = first_session, first_steps
                self.api("/v1/raw-task-content/grants/" + raw_grant["grant_id"] + "/revoke", {
                    "schema_version": "local-raw-task-content-revoke/v1",
                    "expected_grant_signature": raw_grant["signature"], "actor_id": "automated-fixture-operator",
                })
                self.native_turn(self.read_call("r07-after-raw-revoke", expect="allow"))
                self.record("r07_step10_native_capture_opt_in_and_revoke",
                            "real host capture starts only after task opt-in; revocation stops additional capture while ordinary authorized reads continue",
                            self.api("/v1/raw-task-content/records/search", raw_search)["items"] == captured,
                            "before_grant_records=0 authorized_records=2 after_revocation_records=2")

                if retention_seed_enabled:
                    # A1 is the genuine 1h native capture above. A separate
                    # post-revocation grant creates A2 with 24h retention on
                    # the same real task; B1 has its own native task and 24h
                    # grant. This lets the later wall-clock verifier prove
                    # deletion and byte-for-byte survivor isolation together.
                    keep_grant = self.api("/v1/raw-task-content/grants", {
                        "schema_version": "local-raw-task-content-grant-create/v1",
                        "task_id": raw_task, "kinds": ["parameters", "output"],
                        "actor_id": "automated-fixture-operator",
                        "duration_seconds": 86400, "retention_seconds": 86400,
                        "max_plaintext_bytes": 65536,
                    }, expected=201)
                    keep_path = self.workspace / "company-a/native-a-keep.txt"
                    keep_path.write_text("fixture-visible-company-a native-a-keep\n")
                    keep_call = {"id": "r07-a-keep", "tool": self.read_tool,
                                 "params": {"path": str(keep_path)}, "expect": "allow"}
                    before = len(self.receipts())
                    self.native_turn(keep_call)
                    keep_row = self.decision_for(before, keep_call["id"])
                    all_a = self.api("/v1/raw-task-content/records/search", raw_search)["items"]
                    b_search = {"schema_version": "local-raw-task-content-record-list/v1",
                                "task_id": second_task}
                    all_b = self.api("/v1/raw-task-content/records/search", b_search)["items"]
                    old_ids = {row["record_id"] for row in captured}
                    keep_a = [row for row in all_a if row["record_id"] not in old_ids]
                    require(keep_row["action"] == "allow" and len(keep_a) == 2
                            and len(all_b) == 2
                            and {row["kind"] for row in keep_a} == {"parameters", "output"}
                            and {row["kind"] for row in all_b} == {"parameters", "output"},
                            "native A2/B1 24h retention captures incomplete")
                    self.retention_seed_rows = [
                        {"label": label, "task_id": task, "record": row,
                         "expect": expectation, "grant_id": grant_id}
                        for label, task, rows, expectation, grant_id in (
                            ("A1", raw_task, captured, "expires", raw_grant["grant_id"]),
                            ("A2", raw_task, keep_a, "survives", keep_grant["grant_id"]),
                            ("B1", second_task, all_b, "survives", second_raw_grant["grant_id"]),
                        ) for row in rows
                    ]
                    self.record(
                        "r07_step10_native_retention_seed_three_groups",
                        "real OpenClaw tasks A/B produce A1 1h and A2/B1 24h parameter/output ciphertext groups without changing the normal journey",
                        len(self.retention_seed_rows) == 6,
                        "native_tasks=2 A1=2 A2=2 B1=2; natural purge pending",
                    )

                self.session_override = None
                decision_token = (self.state / "token").read_text().strip()
                # A synthetic non-adapter subject: hri-/rca- subjects require a
                # scoped runtime credential for /v1/decide, and this leg exists
                # to exercise the approval flow, not adapter identity.
                subject = "r07-approval-agent"
                approval_grant = self.api(
                    "/v1/grants",
                    {
                        "admission_id": self.api(
                            "/v1/admit",
                            {"path": str(REPO / "apps/agentshield/internal/admission/testdata/skills/benign/official-like")},
                        )["admission"]["admission_id"],
                        "platform": "openclaw",
                        "subject_id": subject,
                        "subject_type": "agent_instance",
                        "redact_secrets": True,
                    },
                )
                approval_path = "/v1/grants/" + approval_grant["grant"]["grant_id"]
                # Required intent enforcement means an unbound decide denies
                # fail-closed, and exec effects are never intent-compatible
                # (shell always carries an unknown effect). The hold leg
                # therefore marks the intent-compatible web_extract tool as
                # requiring human approval on the grant, then binds a task
                # intent to this session through the grant selection.
                approval = self.grant_action(
                    approval_path, "require-approval", revision=approval_grant["state_revision"],
                    schema_version="grant-tool-approval/v1", tools=["web_extract"],
                )
                approval = self.grant_action(approval_path, "challenge", revision=approval["state_revision"])
                approval = self.grant_action(
                    approval_path, "approve", revision=approval["state_revision"],
                    challenge_id=approval["challenge"]["challenge_id"], nonce=approval["challenge"]["nonce"],
                )
                deployed = self.grant_action(approval_path, "deploy", revision=approval["state_revision"])
                now = datetime.now(UTC)
                issued = (now - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
                expires = (now + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ")
                approval_intent = self.api("/v1/intents", {
                    "schema_version": "intent/v2", "intent_id": "intent-r07-approval", "task_id": "task-r07-approval",
                    "principal": {"type": "user", "id": "journey-fixture-operator"},
                    "agent": {"id": subject, "platform": "openclaw"},
                    "purpose": "journey hold under required enforcement",
                    "allowed_tools": ["web_extract"], "allowed_effects": ["network.request"],
                    "resource_constraints": [], "parameter_constraints": [],
                    "issued_at": issued, "valid_from": issued, "expires_at": expires,
                    "authority": {"issuer": "local-admin", "revision": "1", "evidence_ids": []},
                }, expected=201)
                self.api("/v1/intent-bindings", {
                    "schema_version": "intent-grant-bind/v1", "grant_id": approval_grant["grant"]["grant_id"],
                    "expected_grant_revision": deployed["state_revision"],
                    "platform": "openclaw", "session_id": "session-r07-approval",
                    "agent_id": subject, "intent_id": approval_intent["intent_id"],
                }, expected=201)
                decide_request = {
                    "platform": "openclaw", "agent_id": subject, "session_id": "session-r07-approval",
                    "tool_call_id": "call-r07-approval", "tool": "web_extract",
                    "params": {"url": "https://api.github.com/repos/example/example"},
                }
                decision = self.api("/v1/decide", decide_request, token=decision_token)
                require(decision["action"] == "hold", "expected the sensitive call to be held, got " + decision["action"])
                item = next(
                    i for i in self.api("/v1/confirmations")["items"]
                    if i["decision_receipt_id"] == decision["receipt_id"]
                )
                self.record(
                    "r07_step6_hold_lands_in_siq_confirmations",
                    "held sensitive call becomes a pending confirmation inside SIQ",
                    item["status"] == "pending",
                    "action_id=" + item["action_id"] + " status=" + item["status"],
                )
                confirmation_heading = page.get_by_role("heading", name="确认操作：web_extract")
                self.goto_until(page, self.endpoint + "/confirmations?request=" + item["action_id"],
                                confirmation_heading,
                                step="step6_confirmation_detail", category="role:heading")
                self.mark("step6_confirmation_form", "label:textbox+role:checkbox", "editable")
                page.get_by_label("确认人", exact=True).fill("journey-fixture-operator")
                page.get_by_text("我已核对本次操作和参数摘要").check()
                page.get_by_role("button", name="批准本次请求", exact=True).click()
                self.mark("step6_approval_recorded", "text:confirmation_receipt")
                expect(page.get_by_text("已批准本次请求。确认记录：" + decision["receipt_id"])).to_be_visible()
                self.record(
                    "r07_step6_ui_approval_records_confirmation",
                    "operator approves the held call in the console; SIQ records the confirmation receipt",
                    not page_errors,
                    "receipt_id=" + decision["receipt_id"],
                )
                try:
                    self.api(
                        "/v1/confirmations/" + item["action_id"] + "/resolve",
                        {
                            "schema_version": "local-confirmation-resolve/v1",
                            "decision_receipt_id": item["decision_receipt_id"],
                            "decision_hash": item["decision_hash"],
                            "params_digest": item["params_digest"],
                            "approve": True,
                            "actor_id": "journey-fixture-operator",
                        },
                    )
                    replay_rejected = False
                except RuntimeError as exc:
                    replay_rejected = "got 409;" in str(exc)
                self.record(
                    "r07_step6_replayed_approval_rejected",
                    "replaying the same approval through the API after the UI decision is rejected (409)",
                    replay_rejected,
                    "replay_rejected=" + str(replay_rejected),
                )

                # Journey step 7: the full L2 update leg on the same daemon+host.
                self._reset_model()
                phase_b = self.update_and_run()
                self.record(
                    "r07_step7_update_leg_v1_cancel_confirm_v2_remove",
                    "reused L2 leg passes end to end: V1 → cancel-before-confirm → confirm update V2 → re-authorize → safe removal",
                    phase_b["passed"] and bool(phase_b["results"]),
                    "passed=" + str(phase_b["passed"]) + " checks=" + str(len(phase_b["results"])),
                )
            except Exception as error:  # noqa: BLE001 -- record category, then re-raise unchanged
                self.debug_dump(page, "phase-a", error)
            finally:
                browser.close()

        # Journey step 8: interrupt the service and recover; the browser session
        # is invalidated and re-paired by keyboard after a wrong-code retry.
        self.restart()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": 1440, "height": 1100}, locale="zh-CN")
                # JS-side fetch hook: the Playwright response listener misses
                # responses (run 17 network log), and it cannot record a
                # request that is still pending or a client-side abort — this
                # hook records every fetch outcome as the page sees it.
                context.add_init_script(
                    "window.__fetchLog = [];\n"
                    "const __origFetch = window.fetch;\n"
                    "window.fetch = function() {\n"
                    "  const input = arguments[0];\n"
                    "  const url = typeof input === 'string' ? input : (input && input.url) || String(input);\n"
                    "  const note = (line) => { window.__fetchLog.push(line);\n"
                    "    if (window.__fetchLog.length > 600) window.__fetchLog.shift(); };\n"
                    "  return __origFetch.apply(this, arguments).then(\n"
                    "    (resp) => { note(resp.status + ' ' + url); return resp; },\n"
                    "    (err) => { note('ERR ' + ((err && err.message) || String(err)) + ' ' + url); throw err; });\n"
                    "};\n"
                )
                page = context.new_page()
                page_errors = []
                page.on("pageerror", lambda _: page_errors.append("pageerror"))
                page.goto(self.endpoint + "/overview")
                self.mark("step8_pairing_form_fresh_daemon", "role:heading")
                expect(page.get_by_role("heading", name="连接你的本地管理台")).to_be_visible()
                self.mark("step8_pairing_code_input", "label:textbox", "editable")
                page.get_by_label("配对码", exact=True).fill(self.pair_code())
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                self.mark("step8_session_established", "role:button")
                expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                # Keep this exact document and its in-memory session alive.
                old_admin = self.admin
                history_before = self.receipts()
                identities_before = self.api("/v1/runtime-identities")
                self.restart()
                self.api("/v1/status", token=old_admin, expected=401)
                # A real UI request must hit the restarted daemon with its old
                # browser credential; no page.goto/reload or new context here.
                page.get_by_role("link", name="签发", exact=True).click()
                self.mark("step8_session_invalidated_notice", "text:session_expired")
                expect(page.get_by_text(re.compile("管理会话已失效"))).to_be_visible()
                self.mark("step8_pairing_form_after_invalidation", "role:heading")
                expect(page.get_by_role("heading", name="连接你的本地管理台")).to_be_visible()
                self.record(
                    "r07_step8_interrupt_invalidates_ui_session",
                    "same browser document loses its session after daemon restart; old admin receives 401; durable receipts and identities are preserved",
                    not page_errors and self.receipts() == history_before
                    and self.api("/v1/runtime-identities") == identities_before,
                    "same_document=true old_admin_http=401 receipts_unchanged=true identities_unchanged=true",
                )
                self.mark("step8_retry_code_input", "label:textbox", "editable")
                page.get_by_label("配对码", exact=True).fill("wrong")
                page.get_by_role("button", name="建立管理会话", exact=True).click()
                self.mark("step8_wrong_code_alert", "role:alert", "contains_text")
                expect(page.get_by_role("alert")).to_contain_text("配对码无效")
                code_input = page.get_by_label("配对码", exact=True)
                code_input.fill("")  # the failed attempt leaves "wrong" in the field
                code_input.click()
                page.keyboard.type(self.pair_code())
                page.keyboard.press("Enter")
                self.mark("step8_keyboard_repair_established", "role:button")
                expect(page.get_by_role("button", name="退出管理", exact=True)).to_be_visible()
                self.record(
                    "r07_step8_retry_and_keyboard_repair",
                    "pairing succeeds after retry using keyboard-only input (type + Enter)",
                    not page_errors,
                    "repaired=true keyboard_only=true",
                )

                # Journey step 9: receipts and activities render post-recovery.
                self.goto_until(page, self.endpoint + "/receipts", page.get_by_role("table").first,
                                step="step9_receipts_table", category="role:table")
                self.goto_until(page, self.endpoint + "/activities", page.get_by_role("table").first,
                                step="step9_activities_table", category="role:table")
                self.record(
                    "r07_step9_receipts_activities_render_after_recovery",
                    "console /receipts and /activities render the recovered history without script errors",
                    not page_errors,
                    "pageerrors=" + str(len(page_errors)),
                )

                # Journey step 10: the store was explicitly opted in before the
                # browser journey by the managed fixture setup (actor
                # automated-fixture-operator, retention 1h by default or 24h
                # for the opt-in native retention seed, budget 16 MiB)
                # because the nested L2 leg records per-task native captures;
                # the store-level default-off is asserted pre-activation as
                # r07_step10a_raw_content_store_default_disabled in main().
                # Here the console must show the opted-in state honestly: ready,
                # default capture still off, the signed record's immutable
                # limits, per-task authorization in the topbar, and a purge
                # path that only removes expired ciphertext.
                self.goto_until(page, self.endpoint + "/settings", page.get_by_text("原文仓已启用，默认采集仍为关闭。"),
                                step="step10_settings_raw_store_status", category="text:raw_store_banner")
                expect(page.get_by_text("原文仓已启用 · 按任务授权")).to_be_visible()
                expect(page.get_by_text("1 天" if retention_seed_enabled
                                        else "1 小时")).to_be_visible()
                expect(page.get_by_text("16 MiB")).to_be_visible()
                self.record(
                    "r07_step10_raw_content_opt_in_ui_and_per_task_gating",
                    "after the explicit signed opt-in the console shows the store ready with default capture still off, the activation record's limits, and per-task authorization in the topbar",
                    not page_errors,
                    "ready=true default_capture=false topbar=按任务授权 limits_visible=true",
                )
                receipts_before_purge = self.receipts()
                ciphertext_before = {
                    item.name: hashlib.sha256(item.read_bytes()).hexdigest()
                    for item in (self.state / "raw-task-content").glob("*.json")
                }
                require(bool(ciphertext_before), "native leg must produce real ciphertext before purge")
                self.mark("step10_purge_controls", "text:checkbox+role:button", "editable")
                page.get_by_text("仅删除已达到保留期限的独立密文").check()
                page.get_by_role("button", name="清理到期原文", exact=True).click()
                self.mark("step10_purge_result", "text:purge_summary")
                expect(page.get_by_text(re.compile(r"已清理 \d+ 条到期密文，释放 .+。任务回执和追溯记录未改动。"))).to_be_visible()
                self.record(
                    "r07_step10_purge_preserves_unexpired_records_and_receipts",
                    "purge on this fresh fixture preserves real unexpired ciphertext byte-for-byte and the signed receipt history; deletion of expired records is component-tested separately",
                    not page_errors and self.receipts() == receipts_before_purge
                    and ciphertext_before == {
                        item.name: hashlib.sha256(item.read_bytes()).hexdigest()
                        for item in (self.state / "raw-task-content").glob("*.json")
                    },
                    "unexpired_ciphertexts_preserved=" + str(len(ciphertext_before)) + " receipts_unchanged=true expired_deletion=not_exercised",
                )

                export_document = self.api("/v1/export")
                export_bytes = json.dumps(export_document, sort_keys=True)
                self.record("r07_step10_default_export_excludes_raw_store",
                            "default export excludes ciphertext store and bearer credentials and leaves original records unchanged",
                            export_document.get("format") == "agentshield.export.v1"
                            and "raw-task-content" not in export_bytes and '"ciphertext"' not in export_bytes
                            and self.admin not in export_bytes and decision_token not in export_bytes
                            and self.receipts() == receipts_before_purge
                            and ciphertext_before == {
                                item.name: hashlib.sha256(item.read_bytes()).hexdigest()
                                for item in (self.state / "raw-task-content").glob("*.json")
                            }, "default_export_isolated=true ciphertext_and_receipts_unchanged=true")

                # Journey step 11a: the console stays usable at a phone viewport.
                mobile = context.new_page()
                mobile.set_viewport_size({"width": 390, "height": 844})
                mobile_errors = []
                mobile.on("pageerror", lambda _: mobile_errors.append("pageerror"))
                self.goto_until(mobile, self.endpoint + "/confirmations",
                                mobile.get_by_role("heading", name=re.compile(r"^运行操作")),
                                step="step11_mobile_confirmations_heading", category="role:heading")
                self.record(
                    "r07_step11_mobile_confirmations_usable",
                    "390×844 viewport renders the confirmation inbox usable (heading + no script errors)",
                    not mobile_errors,
                    "pageerrors=" + str(len(mobile_errors)),
                )

                # Journey step 11b: uninstall the adapter from the console; the
                # user-owned host config must survive.
                openclaw_row = page.get_by_role("row").filter(has_text="OpenClaw")
                self.goto_until(page, self.endpoint + "/bindings", openclaw_row.first,
                                step="step11_bindings_openclaw_row", category="role:row")
                self.mark("step11_uninstall_button", "role:button", "enabled")
                openclaw_row.first.get_by_role("button", name="卸载", exact=True).click()
                dialog = page.get_by_role("dialog")
                action_select = dialog.get_by_label("操作", exact=True)
                apply_button = dialog.get_by_role("button", name="确认应用", exact=True)
                self.mark("step11_uninstall_preview_ready", "role:button", "enabled")
                expect(apply_button).to_be_enabled(timeout=60000)
                # Same-value change must not discard a valid preview forever.
                action_select.select_option("uninstall")
                expect(apply_button).to_be_enabled()
                apply_button.click()
                self.mark("step11_uninstall_dialog_closed", "role:dialog", "count=0")
                expect(dialog).to_have_count(0)
                adapter_state_gone = not (self.oc / "siq-agent-security.json").exists()
                host_config_kept = (self.oc / "openclaw.json").is_file()
                self.record(
                    "r07_step11_adapter_uninstall_preserves_host_config",
                    "console-driven adapter uninstall removes the SIQ adapter state while the user's openclaw.json survives",
                    adapter_state_gone and host_config_kept,
                    "adapter_state_removed=" + str(adapter_state_gone)
                    + " openclaw_json_kept=" + str(host_config_kept),
                )

                # Journey step 12: logout returns the console to pairing state.
                self.mark("step12_logout_button", "role:button", "enabled")
                page.get_by_role("button", name="退出管理", exact=True).click()
                self.mark("step12_pairing_form_restored", "role:heading")
                expect(page.get_by_role("heading", name="连接你的本地管理台")).to_be_visible()
                self.record(
                    "r07_step12_logout_ends_session",
                    "退出管理 ends the browser admin session and restores the pairing screen",
                    not page_errors,
                    "logged_out=true",
                )
            except Exception as error:  # noqa: BLE001 -- record category, then re-raise unchanged
                self.debug_dump(page, "phase-c", error)
            finally:
                browser.close()

        # The task export is redacted and signed, and its authorization is the
        # administrator session. Revoke this runner's independent session only
        # after every other journey API check has finished; the browser's UI
        # logout above revoked its own separate session.
        activity_page = self.api("/v1/task-activities?limit=100")
        activity = next((item for item in activity_page["items"]
                         if item.get("binding", {}).get("platform") == "openclaw"), None)
        require(activity is not None, "no real OpenClaw task activity for export logout check")
        export_route = ("/v1/task-activities/" + activity["activity_id"]
                        + "/export?snapshot=" + activity_page["snapshot"])
        signed_before_logout = self.api(export_route)
        trusted_key = self.command([str(self.binary), "pubkey"]).strip()
        require(export_review.verify_export(signed_before_logout, trusted_key),
                "task export signature invalid before administrator logout")
        old_admin = self.admin
        logout = self.api("/v1/session/logout", {})
        denied_export = self.api(export_route, token=old_admin, expected=401)
        self.record(
            "r07_step12_task_export_rejected_after_admin_logout",
            "signed redacted task export succeeds with an active admin session; after explicit logout the same bearer cannot obtain a new export",
            logout.get("signed_out") is True
            and "receipts" not in denied_export and "sources" not in denied_export,
            "before_logout_signed=true after_logout_http=401 export_payload_absent=true",
        )

        results = self.journey_results
        return {
            "schema_version": "personal-r07-linux-user-journey/v1",
            "recorded_at": datetime.now(UTC).isoformat(),
            "passed": all(item["status"] == "pass" for item in results),
            "binary_sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest(),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "openclaw_version": json.loads((self.args.openclaw_root / "package.json").read_text())["version"],
            "results": results,
            "checks": [item["id"] for item in results],
            "nested_legs": [{
                "leg": "r04-openclaw-native-update",
                "schema_version": phase_b["schema_version"],
                "passed": phase_b["passed"],
                "checks": len(phase_b["results"]),
                "results": phase_b["results"],
                "up_coverage": phase_b["up_coverage"],
            }],
            "limitations": [
                "browser operator is automated (Playwright); UI journeys here are not human acceptance",
                "step 1 starts a fixture-copied binary, not the R06 installed systemd service; the combined installation-to-journey gate remains open",
                "step 6 is an HTTP decision plus browser approval test, not native host hold consumption or exactly-once execution",
                "step 10 checks unexpired ciphertext preservation; expired deletion uses component clock fixtures, not elapsed real retention time",
                "UP07 legacy/future signed state rejection is not covered by the stale source digest check",
                "J11 default export exclusion, two native tasks' disjoint signed exports and administrator logout revocation are exercised; the 12-hour session natural expiry and elapsed-time native ciphertext expiry remain open; no plaintext export route exists in this product version",
                "OS desktop notifications are not exercised in this headless journey; browser/OS notification layers are covered by the dedicated notification smokes",
                "step 5 exercises missing-authority (no SEC) overreach; permission-scope overreach inside the granted read scope is not constructible at this fixture level because the host config restricts OpenClaw to the read tool",
                "session-level attribution only (controlled_session), inherited from the L2 leg",
                "local deterministic model and synthetic operator; no external or paid model",
            ],
        }


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--guard-only", action="store_true")
    parser.add_argument("--retain-state-dir", type=Path,
                        help="opt-in private run root retained for real 1h native ciphertext expiry verification")
    parser.add_argument("--retention-seed", type=Path,
                        help="exclusive private seed manifest for --retain-state-dir")
    args = parser.parse_args()
    require(not args.out.exists() and not args.out.with_suffix(".failure.json").exists(),
            "refusing to overwrite a previous run report")
    args.openclaw_root, args.node, args.binary = (
        args.openclaw_root.resolve(), args.node.resolve(), args.binary.resolve()
    )
    require(args.node.is_file(), "Node executable not found")
    require((args.openclaw_root / "openclaw.mjs").is_file(), "OpenClaw entrypoint not found")
    require(bool(args.retain_state_dir) == bool(args.retention_seed),
            "--retain-state-dir and --retention-seed must be provided together")
    require(not args.guard_only or not args.retain_state_dir,
            "retention seed requires the full native journey")
    if args.retain_state_dir:
        args.retain_state_dir = args.retain_state_dir.resolve()
        args.retention_seed = args.retention_seed.resolve()
        require(args.retain_state_dir.parent.name.endswith("-private")
                and not args.retain_state_dir.exists()
                and args.out.parent.resolve().name.endswith("-private")
                and args.retention_seed.parent.name.endswith("-private")
                and not args.retention_seed.exists(),
                "retention state and reports require fresh paths under *-private/")
        args.retain_state_dir.mkdir(mode=0o700)
    args.raw_activation_retention_seconds = 86400 if args.retain_state_dir else 3600
    harness = None
    context = (contextlib.nullcontext(str(args.retain_state_dir)) if args.retain_state_dir
               else tempfile.TemporaryDirectory(prefix="siq-r07-user-journey-"))
    with context as temporary:
        try:
            harness = Harness(Path(temporary), args)
            shutil.copy2(args.binary, harness.binary)
            harness.start()
            if args.guard_only:
                report = harness.guard_reload_regression()
            else:
                pre_activation = harness.check_raw_content_default_disabled()
                harness.setup_authority()
                harness.journey_results.append(pre_activation)
                report = harness.journey()
        except Exception as exc:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            failure = args.out.with_suffix(".failure.json")
            with failure.open("x", encoding="utf-8") as handle:
                failure.chmod(0o600)
                json.dump({**failure_diagnostics(exc, harness),
                           "binary_sha256": hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                           "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
}, handle, indent=2)
            raise
        finally:
            if harness is not None:
                harness.stop()
        if args.retain_state_dir:
            require(len(harness.retention_seed_rows) == 6,
                    "real native retention seed did not create A1/A2/B1 pairs")
            entries = []
            for item in harness.retention_seed_rows:
                record = item["record"]
                record_id = record["record_id"]
                envelope_path = harness.state / "raw-task-content" / (record_id + ".json")
                require(envelope_path.is_file(), "native ciphertext vanished before seed handoff")
                envelope = json.loads(envelope_path.read_text())
                require(envelope["record_id"] == record_id
                        and envelope["expires_at"] == record["expires_at"],
                        "native ciphertext metadata differs from the public API")
                entries.append({
                    "label": item["label"], "task_id": item["task_id"],
                    "record_id": record_id, "kind": record["kind"],
                    "expect": item["expect"], "grant_id": item["grant_id"],
                    "expires_at": record["expires_at"],
                    "plaintext_sha256": record["plaintext_sha256"],
                    "ciphertext_sha256": hashlib.sha256(envelope_path.read_bytes()).hexdigest(),
                })
            seed = {
                "schema_version": "linux-native-openclaw-raw-retention-seed/v1",
                "recorded_at": datetime.now(UTC).isoformat(),
                "candidate_sha256": report["binary_sha256"],
                "driver_sha256": report["harness_sha256"],
                "root": str(harness.root), "state_dir": str(harness.state),
                "port": int(harness.endpoint.rsplit(":", 1)[1]),
                "native_host": "openclaw", "native_host_version": report["openclaw_version"],
                "records": entries,
                "earliest_expiry": min(item["expires_at"] for item in entries
                                       if item["expect"] == "expires"),
                "verification_status": "pending_real_wall_clock_expiry",
            }
            args.retention_seed.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            with args.retention_seed.open("x", encoding="utf-8") as handle:
                json.dump(seed, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"passed": report["passed"], "checks": len(report["results"])}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 -- report category only, exit nonzero
        print(json.dumps({"passed": False, "error_type": type(exc).__name__,
                          "frames": [{"file": Path(frame.filename).name, "line": frame.lineno}
                                     for frame in traceback.extract_tb(exc.__traceback__)[-4:]]}), file=sys.stderr)
        sys.exit(1)
