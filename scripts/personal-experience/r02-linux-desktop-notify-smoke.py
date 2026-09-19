#!/usr/bin/env python3
"""Verify the product's count-only Linux notification reaches the session bus."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
loader = importlib.util.spec_from_file_location(
    "openclaw_approval_fixture",
    ROOT / "scripts/validate-intent-v2-openclaw-approval-gate.py",
)
approval = importlib.util.module_from_spec(loader)
loader.loader.exec_module(approval)
require = approval.require


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wait_for_notification(path: Path, process: subprocess.Popen, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        content = path.read_text(errors="replace") if path.exists() else ""
        if (
            "interface=org.freedesktop.Notifications; member=Notify" in content
            and 'string "SIQ AgentShield"' in content
            and 'string "有 1 项待确认操作，请在本地控制台处理"' in content
        ):
            return content
        require(process.poll() is None, "D-Bus monitor exited before notification")
        time.sleep(0.05)
    raise RuntimeError("product notification did not reach the session bus")


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--binary", type=Path, help="prebuilt SIQ candidate; otherwise build current source")
    parser.add_argument("--expected-sha256", help="required with --binary; binds the exact candidate")
    args = parser.parse_args()
    require(bool(args.binary) == bool(args.expected_sha256), "--binary and --expected-sha256 must be provided together")
    if args.binary:
        require(
            len(args.expected_sha256) == 64 and all(c in "0123456789abcdef" for c in args.expected_sha256),
            "expected SHA256 must be lowercase hexadecimal",
        )
        args.binary = args.binary.resolve(strict=True)
        require(sha256(args.binary) == args.expected_sha256, "selected candidate SHA256 mismatch")
    require(sys.platform.startswith("linux"), "Linux is required")
    require(shutil.which("notify-send") is not None, "notify-send is unavailable")
    require(shutil.which("dbus-monitor") is not None, "dbus-monitor is unavailable")
    require(bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")), "session D-Bus is unavailable")

    with tempfile.TemporaryDirectory(prefix="siq-linux-notify-") as temporary:
        root = Path(temporary)
        fixture_args = argparse.Namespace(
            openclaw_root=Path("/non-runtime-notification-test"), node=Path(sys.executable),
            binary=args.binary,
        )
        harness = approval.ApprovalHarness(root, fixture_args)
        harness.config("optional")
        config_path = harness.state / "config.json"
        config = json.loads(config_path.read_text())
        config["desktop_notify"] = True
        config_path.write_text(json.dumps(config))
        harness.env["DBUS_SESSION_BUS_ADDRESS"] = os.environ["DBUS_SESSION_BUS_ADDRESS"]
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_CURRENT_DESKTOP"):
            if os.environ.get(key):
                harness.env[key] = os.environ[key]

        monitor_log = root / "dbus-monitor.log"
        with monitor_log.open("w+") as stream:
            monitor = subprocess.Popen(
                [
                    "dbus-monitor",
                    "--session",
                    "type='method_call',interface='org.freedesktop.Notifications',member='Notify'",
                ],
                stdout=stream,
                stderr=subprocess.DEVNULL,
                env=os.environ.copy(),
            )
            try:
                harness.build()
                harness.start()
                harness.setup_grant()
                decision_token = (harness.state / "token").read_text().strip()
                decision = harness.api(
                    "/v1/decide",
                    {
                        "platform": "openclaw",
                        "session_id": "linux-notify-session",
                        "agent_id": approval.fixture.AGENT,
                        "tool": "exec",
                        "tool_call_id": "linux-notify-hold",
                        "params": {"command": "printf fixture"},
                    },
                    token=decision_token,
                )
                require(decision["action"] == "hold", "fixture did not produce a pending confirmation")
                bus_output = wait_for_notification(monitor_log, monitor, 12)
                require("linux-notify-hold" not in bus_output, "notification leaked tool-call identity")
                require(decision["action_id"] not in bus_output, "notification leaked action identity")
                require(decision["receipt_id"] not in bus_output, "notification leaked receipt identity")
                require("printf fixture" not in bus_output, "notification leaked tool parameters")
                harness.api(
                    "/v1/hold/" + decision["receipt_id"],
                    {"approve": False, "actor_id": "automated-fixture-operator"},
                )
                records = harness.receipts()
                require(
                    any(
                        item.get("record_type") == "hold_resolution"
                        and item.get("action_id") == decision["action_id"]
                        and item.get("action") == "deny"
                        for item in records
                    ),
                    "notification fixture hold was not safely resolved",
                )
                harness.stop()
                verified = json.loads(harness.command([str(harness.binary), "verify"]))
                require(verified["verified"], "receipt chain verification failed")
                report = {
                    "schema_version": "personal-r02-linux-desktop-notify/v1",
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "passed": True,
                    "platform": platform.platform(),
                    "runtime": {"platform": "openclaw", "os": "linux"},
                    "binary_sha256": sha256(harness.binary),
                    "candidate_binding": "prebuilt-sha256" if args.binary else "built-current-source",
                    "harness_sha256": sha256(Path(__file__)),
                    "notify_send_sha256": sha256(Path(shutil.which("notify-send"))),
                    "checks": [
                        "product_dispatcher_started_with_opt_in",
                        "signed_hold_became_pending",
                        "notify_method_reached_real_session_bus",
                        "title_and_count_only_body_matched",
                        "tool_action_receipt_and_params_not_exposed",
                        "hold_safely_resolved_and_receipt_chain_verified",
                    ],
                    "limitations": [
                        "D-Bus method acceptance is verified; visual rendering and user attention are not observable",
                        "automated fixture hold and operator; no human approval or external model",
                        "remote TTY session reused the logged-in user's real GNOME notification service",
                        "Windows and macOS notification transports are outside this Linux evidence",
                    ],
                }
            finally:
                harness.stop()
                if monitor.poll() is None:
                    monitor.terminate()
                    try:
                        monitor.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        monitor.kill()
                        monitor.wait(timeout=5)

    args.out.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with args.out.open("x") as output:
        output.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": True, "checks": len(report["checks"])}))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"Linux desktop notification smoke failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
