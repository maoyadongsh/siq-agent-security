#!/usr/bin/env python3
"""Test a native Hermes approved hold after its installed Skill changes.

Only an isolated fixture HOME is modified. The Skill is changed without a
Grant transition so that the installation-content check is isolated.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location(
    "lx03_held_install", REPO / "scripts/personal-experience/lx03-hermes-held-install-update-native.py"
)
held = importlib.util.module_from_spec(loader)
loader.loader.exec_module(held)
fixture = held.fixture


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Harness(held.Harness):
    def content_drift_in_native_task(self) -> dict:
        target = self.workspace / "company-a/stale-approval-target.txt"
        params = {"path": str(target), "content": "fixture-stale-approval-content"}
        first_call = "installed-drift-held-write"
        retry_call = "installed-drift-retry"
        calls = [
            {"id": first_call, "tool": self.write_tool, "params": params, "outcome": "deny"},
            {"id": retry_call, "tool": self.write_tool, "params": params, "outcome": "deny"},
        ]
        controller, thread, subjects, failures = self._start_context_controller()
        drift = None

        def after_tool_result(index: int) -> None:
            nonlocal drift
            if index != 1:
                return
            decisions = [row for row in self.receipts() if row.get("record_type") == "decision"
                         and row.get("tool_call_id") == first_call]
            fixture.require(len(decisions) == 1 and decisions[0]["action"] == "hold",
                            "V1 installed Skill write was not held")
            attr = decisions[0].get("skill_attribution") or {}
            fixture.require(attr.get("status") == "verified"
                            and attr.get("evidence_level") == "controlled_task",
                            "V1 hold lacked installed Skill attribution")
            fixture.require(not target.exists(), "held write had a file effect")
            items = [item for item in self.api("/v1/confirmations")["items"]
                     if item.get("tool_call_id") == first_call]
            fixture.require(len(items) == 1 and items[0]["status"] == "pending",
                            "installed Skill hold was not actionable")
            item = items[0]
            route = "/v1/confirmations/" + item["action_id"] + "/resolve"
            body = {
                "schema_version": "local-confirmation-resolve/v1",
                "decision_receipt_id": item["decision_receipt_id"],
                "decision_hash": item["decision_hash"],
                "params_digest": item["params_digest"],
                "approve": True,
                "actor_id": "fixture-console-reviewer",
            }
            fixture.require(self.api(route, body)["action"] == "allow",
                            "console approval did not produce a signed resolution")
            decision_token = Path(self.issued["credential_path"]).read_text().strip()
            status_body = {
                "platform": "hermes", "session_id": item["session_id"],
                "agent_id": item["agent_id"], "task_id": item.get("task_id", ""),
                "runtime_task_id": item.get("runtime_task_id", ""),
                "tool": self.write_tool, "tool_call_id": first_call,
                "action_id": item["action_id"],
                "decision_receipt_id": item["decision_receipt_id"],
                "params": params,
            }
            before_status = self.api("/v1/hold-status", status_body, token=decision_token)
            fixture.require(before_status["status"] == "approved",
                            "approved hold scoped readback before drift: "
                            + str(before_status.get("status")) + "/" + str(before_status.get("reason_code")))
            install = self.api("/v1/skill-installations/operations/" + self.current_install)
            grant_route = "/v1/grants/" + install["plan"]["grant_id"]
            grant_before = self.api(grant_route)
            fixture.require(grant_before["grant"]["status"] == "approved",
                            "installed Skill Grant was not the expected approved state")
            skill = Path(self.env["HERMES_HOME"]) / "skills/intent-fixture/SKILL.md"
            original = skill.read_bytes()
            skill.write_bytes(original + b"\nTEST_OWNED_CONTENT_DRIFT_MARKER\n")
            fixture.require(skill.read_bytes() != original, "fixture content did not change")
            grant_after = self.api(grant_route)
            fixture.require(grant_after["state_revision"] == grant_before["state_revision"]
                            and grant_after["grant"]["status"] == "approved",
                            "Grant changed along with fixture content")
            # The scoped runtime credential itself is bound to the installed
            # content. A 401 here is stronger than a readable denied status.
            self.api("/v1/hold-status", status_body, token=decision_token, expected=401)
            current = [view for view in self.api("/v1/confirmations")["items"]
                       if view.get("action_id") == item["action_id"]]
            fixture.require(len(current) == 1 and current[0]["status"] == "unavailable",
                            "stale approved hold remained available in inbox")
            drift = {
                "original_content_sha256": hashlib.sha256(original).hexdigest(),
                "changed_content_sha256": digest(skill),
                "held_action_id": item["action_id"],
                "grant_revision": grant_before["state_revision"],
            }

        self._native_step_callback = after_tool_result
        try:
            self._run_native(
                calls,
                "Use the installed intent-fixture Skill to write a synthetic report.",
                expected_prompt_text="intent-fixture", skills=("intent-fixture",),
            )
        finally:
            self._native_step_callback = None
            controller.shutdown()
            controller.server_close()
            thread.join(timeout=2)
            try:
                self.command([str(self.args.hermes_cli), "plugins", "disable", "sec-bootstrap"],
                             cwd=self.workspace, env=self.env)
            finally:
                shutil.rmtree(Path(self.env["HERMES_HOME"]) / "plugins/sec-bootstrap", ignore_errors=True)

        fixture.require(not failures and len(subjects) == 1 and len(self.contexts) == 1,
                        "native task/SEC bootstrap mismatch")
        fixture.require(drift is not None, "content was not changed between native calls")
        fixture.require(not target.exists(), "native retry wrote despite changed Skill content")
        rows = self.receipts()
        retry = [row for row in rows if row.get("record_type") == "decision"
                 and row.get("tool_call_id") == retry_call]
        fixture.require(not retry or (len(retry) == 1 and retry[0]["action"] == "deny"),
                        "native retry was allowed after changed installation")
        fixture.require(not any(row.get("record_type") in {"hold_reservation", "observation"}
                                for row in rows), "stale approval was consumed or observed")
        self.stop()
        fixture.require(json.loads(self.command([str(self.binary), "verify"]))["verified"],
                        "receipt chain invalid")
        checks = [
            "installed_skill_native_task_and_sec", "held_write_verified_attribution",
            "hold_zero_file_effect", "inbox_pending", "console_approval_signed",
            "test_owned_skill_content_changed", "grant_revision_and_status_unchanged",
            "old_hold_status_approved_before_drift", "old_hold_credential_401_after_drift",
            "old_inbox_entry_unavailable", "native_retry_fail_closed",
            "retry_zero_file_effect",
            "no_reservation_or_observation", "receipt_chain_verified",
        ]
        return {
            "schema_version": "linux-lx03-hermes-installed-hold-content-drift/v1",
            "recorded_at": datetime.now(UTC).isoformat(),
            "passed": True, "checks": checks,
            "binary_sha256": digest(self.binary),
            "driver_sha256": digest(Path(__file__)),
            "native_cli_sha256": digest(self.args.hermes_cli),
            "original_content_sha256": drift["original_content_sha256"],
            "changed_content_sha256": drift["changed_content_sha256"],
            "native_retry_signed_decision": bool(retry),
            "native_retry_reason_code": retry[0]["reason_code"] if retry else None,
            "signed_receipt_count": len(rows),
            "limitations": [
                "Only a test-owned installed Skill file in isolated HOME was changed, without product update protocol.",
                "The second native tool call has a new call ID; old approval was separately queried by hold-status.",
                "Synthetic model/operator and local file effect; no external system or cross-daemon atomicity claim.",
            ],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--hermes-cli", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.binary, args.hermes_cli, args.out = args.binary.resolve(), args.hermes_cli.resolve(), args.out.resolve()
    if not any(part.endswith("-private") for part in args.out.parts):
        parser.error("--out must be inside a *-private directory")
    if args.out.exists() or not args.out.parent.is_dir() or args.out.parent.stat().st_mode & 0o077:
        parser.error("--out parent must exist, be private, and output must be new")
    args.installer_managed_profile = True
    args.remove_installed_skill = False
    args.legacy_binary = None
    args.raw_expiry_seconds = 0
    args.raw_dual_task = False
    with tempfile.TemporaryDirectory(prefix="siq-lx03-held-drift-") as tmp:
        harness = Harness(Path(tmp), args)
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            harness.setup_authority()
            report = harness.content_drift_in_native_task()
        finally:
            harness.stop()
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
        target.write("\n")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"])}))


if __name__ == "__main__":
    main()
