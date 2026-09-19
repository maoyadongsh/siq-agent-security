#!/usr/bin/env python3
"""Verify natural SEC expiry through an installed OpenClaw native file tool.

Each tool turn uses the public OpenClaw CLI and its installed SIQ plugin in an
isolated HOME. The turns share the same native session, but are separate CLI
processes. The model and administrator are deterministic local fixtures.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "r04_openclaw_expiry_base",
    REPO / "scripts/personal-experience/r04-openclaw-native-update-smoke.py",
)
r04 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r04)
require = r04.require


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Harness(r04.Harness):
    def issue_session_context(self, session_id, install_id=None):
        return self.api(
            "/v1/skill-contexts",
            {
                "schema_version": "local-skill-execution-context-issue/v1",
                "instance_id": self.instance_id,
                "session_id": session_id,
                "task_id": "",
                "install_id": install_id or self.skill_installation["install_id"],
                "ttl_seconds": 60,
                "actor_id": "automated-fixture-operator",
                "confirm_issue": True,
            },
            expected=201,
        )

    def run_expiry(self) -> dict:
        server, thread = self._start_model()
        try:
            # The initial two turns establish the native session and plugin.
            self.native_turn()
            self.native_turn()
            before = len(self.receipts())
            self.native_turn(self.read_call("lx03-pre-sec", expect="deny"))
            pre = self.decision_for(before, "lx03-pre-sec")
            require(pre["action"] == "deny", "missing SEC did not fail closed")
            session = pre["session_id"]
            sec = self.issue_session_context(session)
            expiry = datetime.fromisoformat(sec["expires_at"].replace("Z", "+00:00"))
            require(datetime.now(UTC) < expiry, "SEC expired before positive control")

            before = len(self.receipts())
            self.native_turn(self.read_call("lx03-before-expiry", expect="allow"))
            positive = self.decision_for(before, "lx03-before-expiry")
            attribution = positive.get("skill_attribution") or {}
            require(
                positive["action"] == "allow"
                and positive["session_id"] == session
                and attribution.get("status") == "verified"
                and attribution.get("context_id") == sec["context_id"],
                "pre-expiry native call was not allowed under verified SEC",
            )

            deadline = time.monotonic() + 75
            while datetime.now(UTC) <= expiry + timedelta(seconds=1):
                require(time.monotonic() < deadline, "real SEC expiry wait exceeded bound")
                time.sleep(min(0.5, max(0.05, (expiry - datetime.now(UTC)).total_seconds())))
            sent_after_expiry = datetime.now(UTC)
            before = len(self.receipts())
            self.native_turn(self.read_call("lx03-after-expiry", expect="deny"))
            negative = self.decision_for(before, "lx03-after-expiry")
            reason = negative.get("authority_reason_code") or negative.get("reason_code")
            require(negative["action"] == "deny" and negative["session_id"] == session,
                    "expired native call did not deny in the same session")
            require(reason == "skill_context_expired", "expired SEC lacked explicit signed reason")
            require(
                not any(row.get("record_type") == "observation"
                        for row in self.receipts()[before:]),
                "expired native read was observed as executed",
            )
            require(not self.model_failures and len(self.model_requests_seen) == len(self.steps),
                    "native model transcript incomplete")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

        self.stop()
        verified = json.loads(self.command([str(self.binary), "verify"]))
        require(verified["verified"], "signed receipt chain did not verify")
        return {
            "schema_version": "personal-lx03-openclaw-sec-expiry-native/v1",
            "recorded_at": datetime.now(UTC).isoformat(),
            "passed": True,
            "binary_sha256": sha256(self.binary),
            "driver_sha256": sha256(Path(__file__)),
            "dependency_driver_sha256": sha256(
                REPO / "scripts/personal-experience/r04-openclaw-native-update-smoke.py"
            ),
            "native_cli_sha256": sha256(self.args.openclaw_root / "openclaw.mjs"),
            "openclaw_version": json.loads((self.args.openclaw_root / "package.json").read_text())["version"],
            "sec_ttl_seconds": 60,
            "sec_expires_at": expiry.isoformat(),
            "post_expiry_call_sent_at": sent_after_expiry.isoformat(),
            "post_expiry_reason_code": reason,
            "checks": [
                "real_public_openclaw_cli_and_installed_native_plugin",
                "native_session_enrolled_before_sec_issue",
                "missing_sec_native_read_denied",
                "session_sec_issued_with_minimum_ttl",
                "pre_expiry_native_read_allowed_with_verified_sec",
                "same_native_session_waited_past_real_wall_clock_expiry",
                "post_expiry_native_read_denied_without_protected_content",
                "post_expiry_signed_reason_is_skill_context_expired",
                "post_expiry_no_execution_observation",
                "receipt_chain_verified",
            ],
            "limitations": [
                "native turns share an OpenClaw session but run in separate CLI processes",
                "local deterministic model and synthetic operator; no paid provider or human approval",
                "this is session-scoped attribution, not task-scoped identity or cross-process effect atomicity",
            ],
        }


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw-root", required=True, type=Path)
    parser.add_argument("--node", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.openclaw_root = args.openclaw_root.resolve(strict=True)
    args.node = args.node.resolve(strict=True)
    args.binary = args.binary.resolve(strict=True)
    require(args.node.is_file() and (args.openclaw_root / "openclaw.mjs").is_file(),
            "public OpenClaw CLI unavailable")
    require(sha256(args.binary) == args.expected_sha256, "candidate binary digest mismatch")
    require(args.out.parent.name.endswith("-private"), "report must stay under *-private/")
    require(not args.out.exists(), "refusing to overwrite evidence")
    with tempfile.TemporaryDirectory(prefix="siq-openclaw-sec-expiry-") as temporary:
        harness = Harness(Path(temporary), args)
        shutil.copy2(args.binary, harness.binary)
        require(sha256(harness.binary) == args.expected_sha256, "candidate copy changed")
        try:
            harness.start()
            harness.setup_authority()
            report = harness.run_expiry()
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print(json.dumps({"passed": True, "checks": len(report["checks"])}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - keep private details out of console
        print(f"OpenClaw SEC expiry smoke failed: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)
