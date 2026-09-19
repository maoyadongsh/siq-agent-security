#!/usr/bin/env python3
"""Exercise denial of an installed Skill hold in one real Hermes CLI task.

The installed Skill, runtime credential, Intent and SEC use the shipping SIQ
flow. The model and console operator are deterministic local fixtures.
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
    def deny_in_native_task(self) -> dict:
        target = self.workspace / "company-a/denied-write-target.txt"
        params = {"path": str(target), "content": "fixture-denied-content"}
        first_call = "installed-denied-write"
        retry_call = "installed-denied-retry"
        calls = [
            {"id": first_call, "tool": self.write_tool, "params": params, "outcome": "deny"},
            {"id": retry_call, "tool": self.write_tool, "params": params, "outcome": "deny"},
        ]
        controller, thread, subjects, failures = self._start_context_controller()
        denied_action = None

        def after_tool_result(index: int) -> None:
            nonlocal denied_action
            if index != 1:
                return
            decisions = [
                row for row in self.receipts()
                if row.get("record_type") == "decision" and row.get("tool_call_id") == first_call
            ]
            fixture.require(len(decisions) == 1 and decisions[0]["action"] == "hold",
                            "installed Skill native call did not hold")
            attribution = decisions[0].get("skill_attribution") or {}
            fixture.require(attribution.get("status") == "verified"
                            and attribution.get("evidence_level") == "controlled_task",
                            "installed Skill hold lacks task attribution")
            fixture.require(not target.exists(), "held native call wrote before review")
            items = [
                item for item in self.api("/v1/confirmations")["items"]
                if item.get("tool_call_id") == first_call
            ]
            fixture.require(len(items) == 1 and items[0]["status"] == "pending",
                            "installed Skill hold is not pending in the inbox")
            item = items[0]
            request = {
                "schema_version": "local-confirmation-resolve/v1",
                "decision_receipt_id": item["decision_receipt_id"],
                "decision_hash": item["decision_hash"],
                "params_digest": item["params_digest"],
                "approve": False,
                "actor_id": "fixture-console-reviewer",
            }
            route = "/v1/confirmations/" + item["action_id"] + "/resolve"
            resolution = self.api(route, request)
            fixture.require(resolution["action"] == "deny", "console denial not signed")
            self.api(route, request, expected=409)
            denied = [
                current for current in self.api("/v1/confirmations")["items"]
                if current.get("action_id") == item["action_id"]
            ]
            fixture.require(len(denied) == 1 and denied[0]["status"] == "denied",
                            "denied hold remained actionable")
            # Task-scoped decision capability, not the console/admin token.
            decision_token = Path(self.issued["credential_path"]).read_text().strip()
            status = self.api(
                "/v1/hold-status",
                {
                    "platform": "hermes", "session_id": item["session_id"],
                    "agent_id": item["agent_id"], "task_id": item.get("task_id", ""),
                    "runtime_task_id": item.get("runtime_task_id", ""),
                    "tool": self.write_tool, "tool_call_id": first_call,
                    "action_id": item["action_id"],
                    "decision_receipt_id": item["decision_receipt_id"],
                    "params": params,
                },
                token=decision_token,
            )
            fixture.require(status["status"] == "denied" and status["reason_code"] == "hold_denied",
                            "denied hold became executable")
            denied_action = item["action_id"]

        self._native_step_callback = after_tool_result
        try:
            self._run_native(
                calls,
                "Use the installed intent-fixture Skill to write a synthetic report.",
                expected_prompt_text="intent-fixture",
                skills=("intent-fixture",),
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
        fixture.require(denied_action is not None, "denial was not completed between native calls")
        fixture.require(not target.exists(), "denied or retried write reached the file tool")
        rows = self.receipts()
        retry_decisions = [row for row in rows if row.get("record_type") == "decision"
                           and row.get("tool_call_id") == retry_call]
        fixture.require(len(retry_decisions) == 1 and retry_decisions[0]["action"] == "hold",
                        "new native write did not require fresh review")
        resolutions = [row for row in rows if row.get("record_type") == "hold_resolution"
                       and row.get("action_id") == denied_action]
        fixture.require(len(resolutions) == 1 and resolutions[0]["action"] == "deny",
                        "denial resolution missing or duplicated")
        fixture.require(not any(row.get("record_type") in {"hold_reservation", "observation"}
                                for row in rows), "denied hold was reserved or observed")
        self.stop()
        verified = json.loads(self.command([str(self.binary), "verify"]))
        fixture.require(verified["verified"], "receipt chain invalid")
        checks = [
            "installed_skill_native_task_and_sec", "first_write_held_with_verified_attribution",
            "hold_before_file_effect", "inbox_pending", "console_denial_signed",
            "resolution_replay_409", "inbox_denied", "hold_status_denied",
            "retry_without_file_effect", "one_denial_no_reservation_or_observation",
            "receipt_chain_verified",
        ]
        return {
            "schema_version": "linux-lx03-hermes-installed-hold-denial/v1",
            "recorded_at": datetime.now(UTC).isoformat(),
            "passed": True, "checks": checks,
            "binary_sha256": digest(self.binary),
            "driver_sha256": digest(Path(__file__)),
            "native_cli_sha256": digest(self.args.hermes_cli),
            "signed_receipt_count": len(rows),
            "limitations": [
                "local deterministic model and operator; no human click or external effect",
                "one daemon and one Hermes CLI task; no cross-daemon atomicity claim",
                "the second tool call is a new hold, not replay of the first action",
            ],
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--hermes-cli", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.binary, args.hermes_cli = args.binary.resolve(), args.hermes_cli.resolve()
    args.out = args.out.resolve()
    if not any(part.endswith("-private") for part in args.out.parts):
        parser.error("--out must be inside a *-private directory")
    if args.out.exists() or not args.out.parent.is_dir() or args.out.parent.stat().st_mode & 0o077:
        parser.error("--out parent must exist, be private, and output must be new")
    args.installer_managed_profile = True
    args.remove_installed_skill = False
    args.legacy_binary = None
    args.raw_expiry_seconds = 0
    args.raw_dual_task = False
    with tempfile.TemporaryDirectory(prefix="siq-lx03-held-denial-") as tmp:
        harness = Harness(Path(tmp), args)
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            harness.setup_authority()
            report = harness.deny_in_native_task()
        finally:
            harness.stop()
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
        target.write("\n")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"])}))


if __name__ == "__main__":
    main()
