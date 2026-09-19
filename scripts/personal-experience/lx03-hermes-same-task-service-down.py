#!/usr/bin/env python3
"""Prove Hermes fail-closed behavior inside one authorized native task.

The ordinary R01 offline check starts a new task after the daemon stops. That
task cannot obtain a new SEC, so its denial alone cannot isolate service loss.
Here the test-only pre-LLM observer issues one SEC for the Hermes-generated
task. The public CLI performs allowed read and write calls, then the model
fixture stops only this test's SIQ daemon before two more calls in that same
CLI process. The allowed write and denied write have the same Grant scope.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import sys
import tempfile
import traceback
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "r01_hermes_native", ROOT / "scripts/personal-experience/r01-sec-hermes-native-smoke.py"
)
r01 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r01)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def receipt_snapshot(state: Path) -> dict[str, str]:
    root = state / "receipts"
    if not root.is_dir():
        raise RuntimeError("online controls produced no receipt chain")
    return {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob("*")) if p.is_file()}


def run(args: argparse.Namespace) -> dict:
    with tempfile.TemporaryDirectory(prefix="siq-hermes-same-task-offline-") as tmp:
        harness = r01.Harness(Path(tmp), args)
        shutil.copy2(args.binary, harness.binary)
        bootstrapped = False
        try:
            harness.start()
            harness.setup_authority()
            harness.prepare_task_attribution()
            bootstrapped = True

            online_read = harness.workspace / "company-a/report.txt"
            offline_read = harness.workspace / "company-a/offline-read.txt"
            offline_read.write_text("fixture-visible-company-a offline protected body\n")
            online_write = harness.workspace / "company-a/online-control.txt"
            offline_write = harness.workspace / "company-a/offline-must-not-exist.txt"
            calls = [
                {"id": "same-task-online-read", "tool": "read_file",
                 "params": {"path": str(online_read)}, "outcome": "allow"},
                # The shared real-host model harness treats this exact ID as
                # an allowed write, whose tool result need not echo file text.
                {"id": "sec-write-in-grant", "tool": "write_file",
                 "params": {"path": str(online_write), "content": "fixture-visible-company-a online write"},
                 "outcome": "allow"},
                {"id": "same-task-offline-read", "tool": "read_file",
                 "params": {"path": str(offline_read)}, "outcome": "deny",
                 "forbidden_text": "offline protected body"},
                {"id": "same-task-offline-write", "tool": "write_file",
                 "params": {"path": str(offline_write), "content": "must not execute"},
                 "outcome": "deny"},
            ]
            control = {}

            def after_model_result(index: int) -> None:
                if index != 2:
                    return
                if online_write.read_text() != "fixture-visible-company-a online write":
                    raise RuntimeError("online native write control did not execute")
                records = [r for r in harness.receipts() if r.get("record_type") == "decision"]
                selected = [r for r in records if r.get("tool_call_id") in
                            {"same-task-online-read", "sec-write-in-grant"}]
                if (len(selected) != 2 or any(r.get("action") != "allow" for r in selected)
                        or any(r.get("skill_attribution", {}).get("status") != "verified"
                               for r in selected)
                        or len({(r.get("session_id"), r.get("runtime_task_id")) for r in selected}) != 1):
                    raise RuntimeError("online calls lacked one verified native task authority")
                control["task_identity"] = (selected[0]["session_id"], selected[0]["runtime_task_id"])
                control["receipt_snapshot"] = receipt_snapshot(harness.state)
                harness.stop()
                host, port = harness.endpoint.removeprefix("http://").split(":")
                with socket.socket() as sock:
                    sock.settimeout(1)
                    if sock.connect_ex((host, int(port))) == 0:
                        raise RuntimeError("isolated daemon still accepting connections")
                control["daemon_stopped_before_offline_calls"] = True

            harness._native_step_callback = after_model_result
            harness._run_native(calls, "Use the installed intent-fixture Skill for the same-task service-loss check.",
                                skills=("intent-fixture",))
            del harness._native_step_callback
            if not control.get("daemon_stopped_before_offline_calls"):
                raise RuntimeError("native model did not reach the service-loss boundary")
            if offline_write.exists():
                raise RuntimeError("offline native write created a file")
            if receipt_snapshot(harness.state) != control["receipt_snapshot"]:
                raise RuntimeError("offline calls changed signed receipts")
            harness.cleanup_task_attribution()
            bootstrapped = False
            harness.verify_task_attribution()
            verified = json.loads(harness.command([str(harness.binary), "verify"]))
            if verified.get("verified") is not True:
                raise RuntimeError("signed receipt chain failed verification")
            return {
                "schema_version": "linux-lx03-hermes-same-task-service-down/v1",
                "recorded_at": datetime.now(UTC).isoformat(),
                "passed": True,
                "candidate_sha256": digest(args.binary),
                "driver_sha256": digest(Path(__file__)),
                "hermes_cli_sha256": digest(args.hermes_cli),
                "native_entrypoint": "public hermes chat --oneshot, one generated session/task, real file tools",
                "checks": [
                    "isolated_managed_installed_skill_and_sec",
                    "same_native_process_and_task_for_four_calls",
                    "online_native_read_allowed",
                    "online_native_write_effect_observed",
                    "online_decisions_verified_and_same_task",
                    "only_batch_daemon_stopped_before_offline_calls",
                    "offline_listener_absent",
                    "offline_native_read_denied_without_body",
                    "offline_native_write_denied_without_file_effect",
                    "offline_signed_receipt_chain_unchanged",
                    "one_task_sec_bootstrap",
                    "signed_receipt_chain_verified",
                ],
                "limitations": [
                    "The model endpoint and SEC bootstrap observer are local deterministic test fixtures.",
                    "This is one native process with local file effects; it does not prove cross-process or external-effect atomicity.",
                    "No network egress target or OS sandbox behavior is exercised.",
                ],
            }
        finally:
            if bootstrapped:
                harness.cleanup_task_attribution()
            harness.stop()


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--hermes-cli", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.binary = args.binary.resolve(strict=True)
    args.hermes_cli = args.hermes_cli.resolve(strict=True)
    if not any(part.endswith("-private") for part in args.out.parts[:-1]):
        raise RuntimeError("same-task evidence must remain in a private directory")
    if digest(args.binary) != args.expected_sha256 or args.out.exists():
        raise RuntimeError("candidate digest mismatch or evidence path exists")
    args.installer_managed_profile = True
    args.remove_installed_skill = False
    args.legacy_binary = None
    args.raw_expiry_seconds = 0
    args.raw_dual_task = False
    args.grant_write_symlink_overreach = True
    report = run(args)
    args.out.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with args.out.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"passed": True, "checks": len(report["checks"])}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 -- private diagnostic, public output names the type only
        target = next((Path(sys.argv[i + 1]) for i, arg in enumerate(sys.argv[:-1]) if arg == "--out"), None)
        if target is not None and any(part.endswith("-private") for part in target.parts[:-1]):
            target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            target.with_suffix(".failure.log").write_text(traceback.format_exc())
        print(json.dumps({"passed": False, "error_type": type(exc).__name__}), file=sys.stderr)
        sys.exit(1)
