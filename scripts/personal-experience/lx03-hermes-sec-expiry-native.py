#!/usr/bin/env python3
"""Check real-wall-clock SEC expiry in one public Hermes chat process.

The existing R01 fixture installs SIQ in an isolated Hermes profile. A local
identity observer reports Hermes-generated session/task IDs; the product API
issues a 60-second task-bound SEC. Two native read_file calls in that same
chat bracket its expiry. No paid model, user profile, or shared daemon is used.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "r01_sec_hermes", REPO / "scripts/personal-experience/r01-sec-hermes-native-smoke.py"
)
r01 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r01)
require = r01.fixture.require


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Harness(r01.Harness):
    def _context_body(self, install_id, session_id, task_id):
        body = super()._context_body(install_id, session_id, task_id)
        body["ttl_seconds"] = 60
        return body

    def run_expiry(self) -> dict:
        subjects: list[tuple[str, str]] = []
        errors: list[str] = []
        lock = threading.Lock()
        harness = self

        class Bootstrap(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                try:
                    require(self.path == "/bind", "unexpected native observer route")
                    size = int(self.headers.get("Content-Length", "0"))
                    require(0 < size <= 2048, "observer request budget")
                    body = json.loads(self.rfile.read(size))
                    require(set(body) == {"session_id", "task_id"}, "observer fields")
                    session_id, task_id = body["session_id"], body["task_id"]
                    require(
                        isinstance(session_id, str) and 0 < len(session_id) <= 256
                        and isinstance(task_id, str) and 0 < len(task_id) <= 256,
                        "native identity missing",
                    )
                    with lock:
                        if not subjects:
                            subjects.append((session_id, task_id))
                            credential = Path(harness.issued["credential_path"]).read_text().strip()
                            harness.api(
                                "/v1/runtime-sessions",
                                {"schema_version": "local-runtime-session-enroll/v1", "session_id": session_id},
                                token=credential,
                            )
                            harness.sec = harness.api(
                                "/v1/skill-contexts",
                                harness._context_body(harness.narrow_install, session_id, task_id),
                                expected=201,
                            )
                        else:
                            require(subjects[0] == (session_id, task_id), "native identity changed")
                    raw = b'{"ready":true}'
                    self.send_response(200)
                except (RuntimeError, ValueError, TypeError, KeyError, OSError) as exc:
                    errors.append(type(exc).__name__)
                    raw = b'{"ready":false}'
                    self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        controller = ThreadingHTTPServer(("127.0.0.1", 0), Bootstrap)
        thread = threading.Thread(target=controller.serve_forever, daemon=True)
        thread.start()
        self._install_bootstrap_observer(f"http://127.0.0.1:{controller.server_port}/bind")
        second = self.workspace / "company-a/sec-expiry-second.txt"
        second.write_text("fixture-visible-company-a expired-sec-second\n")
        calls = [
            {"id": "sec-expiry-before", "tool": "read_file",
             "params": {"path": str(self.workspace / "company-a/report.txt")}, "outcome": "allow"},
            {"id": "sec-expiry-after", "tool": "read_file",
             "params": {"path": str(second)}, "outcome": "deny",
             "forbidden_text": "fixture-visible-company-a expired-sec-second"},
        ]
        times = {}

        def before_next_native_call(index: int):
            if index != 1:
                return
            require(len(subjects) == 1, "native identity was not enrolled")
            expiry = datetime.fromisoformat(self.sec["expires_at"].replace("Z", "+00:00"))
            require(datetime.now(UTC) < expiry, "SEC expired before positive control")
            times["expires_at"] = expiry
            deadline = time.monotonic() + 75
            while datetime.now(UTC) <= expiry + timedelta(seconds=1):
                require(time.monotonic() < deadline, "SEC expiry wait exceeded bound")
                time.sleep(min(0.5, max(0.05, (expiry - datetime.now(UTC)).total_seconds())))
            times["post_expiry_at"] = datetime.now(UTC)

        self._native_step_callback = before_next_native_call
        try:
            self._run_native(calls, "Use the installed intent-fixture Skill to read both fixture files.",
                             skills=("intent-fixture",))
        finally:
            del self._native_step_callback
            controller.shutdown()
            controller.server_close()
            thread.join(timeout=3)
            (Path(self.env["HERMES_HOME"]) / "config.yaml").write_bytes(self.product_config)
            shutil.rmtree(Path(self.env["HERMES_HOME"]) / "plugins/sec-bootstrap", ignore_errors=True)
        require(not errors and len(subjects) == 1, "native SEC bootstrap failed")
        require(times["post_expiry_at"] > times["expires_at"], "post-expiry call was too early")
        records = self.receipts()
        decisions = {r.get("tool_call_id"): r for r in records if r.get("record_type") == "decision"}
        before, after = (decisions[c["id"]] for c in calls)
        require(before["action"] == "allow" and after["action"] == "deny", "native expiry verdict mismatch")
        require(
            before["session_id"] == after["session_id"] == subjects[0][0]
            and before.get("runtime_task_id") == after.get("runtime_task_id") == subjects[0][1],
            "native identity changed across expiry",
        )
        require(
            before["skill_attribution"]["status"] == "verified"
            and before["skill_attribution"]["context_id"] == self.sec["context_id"],
            "pre-expiry SEC was not verified",
        )
        require(
            after.get("authority_reason_code") == "skill_context_expired"
            or after.get("reason_code") == "skill_context_expired",
            "expired SEC lacked explicit signed reason",
        )
        require(not any(r.get("record_type") == "observation" and
                        r.get("tool_call_id") == "sec-expiry-after" for r in records),
                "expired native read was observed as executed")
        self.stop()
        verified = json.loads(self.command([str(self.binary), "verify"]))
        require(verified["verified"], "receipt chain verification failed")
        return {
            "schema_version": "personal-lx03-hermes-sec-expiry-native/v1",
            "recorded_at": datetime.now(UTC).isoformat(),
            "passed": True,
            "binary_sha256": sha256(self.binary),
            "driver_sha256": sha256(Path(__file__)),
            "dependency_driver_sha256": sha256(REPO / "scripts/personal-experience/r01-sec-hermes-native-smoke.py"),
            "native_cli_sha256": sha256(self.args.hermes_cli),
            "sec_ttl_seconds": 60,
            "sec_expires_at": times["expires_at"].isoformat(),
            "post_expiry_call_at": times["post_expiry_at"].isoformat(),
            "post_expiry_reason_code": after.get("authority_reason_code") or after.get("reason_code"),
            "checks": [
                "real_public_hermes_cli_and_isolated_profile",
                "native_session_and_task_enrolled",
                "task_bound_sec_issued_with_minimum_ttl",
                "pre_expiry_native_read_allowed_with_verified_sec",
                "same_native_chat_process_waited_past_real_wall_clock_expiry",
                "post_expiry_native_read_denied_without_protected_content",
                "post_expiry_signed_reason_is_skill_context_expired",
                "post_expiry_native_identity_unchanged",
                "post_expiry_no_execution_observation",
                "receipt_chain_verified",
            ],
            "limitations": [
                "local deterministic model and isolated synthetic files; no paid provider",
                "test-only pre_llm observer reports host-generated IDs but carries no SIQ authority",
                "this tests SEC expiry in one Hermes process, not cross-process atomicity or other hosts",
            ],
        }


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--hermes-cli", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.binary = args.binary.resolve(strict=True)
    args.hermes_cli = args.hermes_cli.resolve(strict=True)
    require(sha256(args.binary) == args.expected_sha256, "candidate binary digest mismatch")
    require(not args.out.exists(), "refusing to overwrite evidence")
    args.installer_managed_profile = True
    args.remove_installed_skill = False
    args.legacy_binary = None
    args.raw_expiry_seconds = 0
    args.raw_dual_task = False
    args.grant_write_symlink_overreach = False
    with tempfile.TemporaryDirectory(prefix="siq-hermes-sec-expiry-") as temporary:
        harness = Harness(Path(temporary), args)
        shutil.copy2(args.binary, harness.binary)
        try:
            harness.start()
            harness.setup_authority()
            report = harness.run_expiry()
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with args.out.open("x") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print(json.dumps({"passed": True, "checks": len(report["checks"])}))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        # Native logs may contain paths or credentials; print only the class.
        print(json.dumps({"passed": False, "error_type": type(exc).__name__}), file=sys.stderr)
        sys.exit(1)
