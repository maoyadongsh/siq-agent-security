#!/usr/bin/env python3
"""Exercise real Hermes tools after the isolated SIQ daemon goes offline.

The online control is the native SEC harness. It proves the same installed
profile can read an allowed file before this test stops only its own daemon.
The offline calls then use the public Hermes CLI and its installed SIQ plugin.
No external model or production profile is used.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "r01_hermes_native", REPO / "scripts/personal-experience/r01-sec-hermes-native-smoke.py"
)
r01 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r01)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def receipt_snapshot(state: Path) -> dict[str, str]:
    root = state / "receipts"
    if not root.is_dir():
        raise RuntimeError("online control produced no receipt chain")
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


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
    if sha256(args.binary) != args.expected_sha256:
        raise RuntimeError("candidate binary digest mismatch")
    if args.out.exists():
        raise RuntimeError("refusing to overwrite existing evidence")
    args.installer_managed_profile = True
    args.remove_installed_skill = False
    args.legacy_binary = None
    # The shared native SEC harness also accepts optional raw-capture modes.
    # Keep this service-loss leg on its original ordinary-tool path.
    args.raw_expiry_seconds = 0
    args.raw_dual_task = False
    with tempfile.TemporaryDirectory(prefix="siq-hermes-offline-") as tmp:
        harness = r01.Harness(Path(tmp), args)
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            harness.setup_authority()
            online = harness.native_sec()  # real allowed read; stops own daemon
            required_control = {
                "native_allowed_read_executes",
                "native_write_denied_before_side_effect",
                "receipt_chain_verified",
            }
            if (not online["passed"] or online["verified_decision_count"] < 2
                    or not required_control.issubset(online["checks"])):
                raise RuntimeError("online native control incomplete")
            before = receipt_snapshot(harness.state)
            host, port_text = harness.endpoint.removeprefix("http://").split(":")
            with socket.socket() as sock:
                sock.settimeout(1)
                if sock.connect_ex((host, int(port_text))) == 0:
                    raise RuntimeError("isolated daemon still accepting connections")

            marker = harness.workspace / "company-a/hermes-offline-must-not-exist.txt"
            calls = [
                {
                    "id": "offline-native-read",
                    "tool": "read_file",
                    "params": {"path": str(harness.workspace / "company-a/report.txt")},
                    "outcome": "deny",
                    "forbidden_text": "fixture-visible-company-a",
                },
                {
                    "id": "offline-native-write",
                    "tool": "write_file",
                    "params": {"path": str(marker), "content": "must not execute"},
                    "outcome": "deny",
                },
            ]
            harness._run_native(
                calls,
                "Use the installed intent-fixture Skill to read the fixture and write the marker.",
                skills=("intent-fixture",),
            )
            if marker.exists():
                raise RuntimeError("offline native write produced a side effect")
            if receipt_snapshot(harness.state) != before:
                raise RuntimeError("offline call mutated signed receipt chain")
            report = {
                "schema_version": "personal-r01-hermes-service-down/v1",
                "recorded_at": datetime.now(UTC).isoformat(),
                "passed": True,
                "binary_sha256": sha256(args.binary),
                "hermes_cli_sha256": sha256(args.hermes_cli),
                "harness_sha256": sha256(Path(__file__)),
                "online_control_decisions": online["verified_decision_count"],
                "checks": [
                    "isolated_managed_hermes_profile",
                    "online_native_allowed_read_control",
                    "online_native_sec_receipts_verified",
                    "only_batch_daemon_stopped",
                    "batch_daemon_listener_absent",
                    "offline_native_read_blocked",
                    "offline_native_write_blocked",
                    "offline_independent_file_marker_absent",
                    "offline_receipt_chain_unchanged",
                ],
                "limitations": [
                    "isolated deterministic local model; no external provider",
                    "write operation also lacks narrow-skill permission while online; the read control isolates service loss",
                    "host tool return proves plugin refusal; no network egress target exercised",
                ],
            }
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with args.out.open("x") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"passed": True, "checks": len(report["checks"])}))


if __name__ == "__main__":
    main()
