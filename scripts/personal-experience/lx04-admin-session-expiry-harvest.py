#!/usr/bin/env python3
"""Validate and publish an LX04 natural admin-session expiry result.

The long-running verifier writes credentials and raw details only below an
ignored 0700 directory.  This harvester refuses to publish until that verifier
is terminal, the exact owned daemon is gone, its loopback port is closed, and
the private result proves both bearer export and cookie restore expired on the
same live daemon after the production 12-hour TTL.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import socket
import stat
import time
from datetime import UTC, datetime
from pathlib import Path


SEED_SCHEMA = "linux-lx04-admin-natural-expiry-seed/v1"
RESULT_SCHEMA = "linux-lx04-admin-natural-expiry-result/v1"
PENDING_SCHEMA = "linux-lx04-admin-natural-expiry-pending/v1"
SUMMARY_SCHEMA = "linux-lx04-admin-natural-expiry-summary/v1"


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_private(path: Path) -> dict:
    require(path.is_file() and not path.is_symlink(), "private_file_required")
    require(stat.S_IMODE(path.stat().st_mode) == 0o600, "private_file_mode_invalid")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), "private_json_object_required")
    return value


def process_matches(pid: int, starttime: str) -> bool:
    try:
        value = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[19]
        return value == starttime
    except (FileNotFoundError, PermissionError, IndexError):
        return False


def daemon_matches(pid: int, starttime: str, state: str) -> bool:
    if not process_matches(pid, starttime):
        return False
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except (FileNotFoundError, PermissionError):
        return False
    return state in command and " serve " in f" {command} "


def port_closed(port: int) -> bool:
    with socket.socket() as client:
        client.settimeout(0.25)
        return client.connect_ex(("127.0.0.1", port)) != 0


def wait_absent(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while predicate() and time.monotonic() < deadline:
        time.sleep(0.1)
    return not predicate()


def write_exclusive(path: Path, value: dict) -> None:
    path = path.absolute()
    require(path.parent.is_dir(), "summary_parent_missing")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def harvest(args) -> dict:
    private = args.private.absolute()
    require(private.is_dir() and not private.is_symlink(), "private_directory_required")
    info = private.stat()
    require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
            "private_directory_owner_or_mode_invalid")

    seed_path = private / "seed.json"
    result_path = private / "result.json"
    worker_path = private / "worker.json"
    seed = load_private(seed_path)
    result = load_private(result_path)
    worker = load_private(worker_path)
    pending_path = args.pending_summary.absolute()
    require(pending_path.is_file() and not pending_path.is_symlink(),
            "pending_summary_required")
    pending = json.loads(pending_path.read_text())

    require(seed.get("schema_version") == SEED_SCHEMA, "seed_schema_invalid")
    require(result.get("schema_version") == RESULT_SCHEMA, "result_schema_invalid")
    require(pending.get("schema_version") == PENDING_SCHEMA, "pending_schema_invalid")
    require(pending.get("candidate_sha256") == seed.get("candidate_sha256")
            == result.get("candidate_sha256"), "candidate_binding_mismatch")
    require(pending.get("private_seed_sha256") == sha(seed_path),
            "private_seed_binding_mismatch")
    require(pending.get("pre_expiry_signed_task_export_sha256")
            == seed.get("export_before_sha256"), "pre_expiry_export_binding_mismatch")
    require(pending.get("verify_after_utc") == seed.get("verify_after_utc"),
            "expiry_deadline_binding_mismatch")

    ttl = int(pending.get("production_admin_ttl_seconds", 0))
    require(ttl == 43200, "production_admin_ttl_changed")
    required_wall = float(seed["not_before_epoch"]) - float(seed["paired_after_epoch"])
    require(required_wall >= ttl and float(result.get("real_wall_seconds", 0)) >= required_wall,
            "real_wall_expiry_not_proven")
    require(result.get("passed") is True and result.get("same_daemon_alive") is True,
            "same_daemon_expiry_result_failed")
    require(result.get("health_ready") is True, "same_daemon_health_not_ready")
    require(result.get("expired_export_status") == 401
            and result.get("expired_restore_status") == 401,
            "expired_credentials_not_rejected")
    require(result.get("export_payload_absent") is True
            and result.get("restore_session_absent") is True,
            "expired_response_leaked_protected_payload")

    worker_pid = int(worker["pid"])
    worker_start = str(worker["starttime"])
    require(not process_matches(worker_pid, worker_start), "expiry_worker_still_running")

    daemon_pid = int(seed["daemon_pid"])
    daemon_start = str(seed["daemon_starttime"])
    state = str(seed["state"])

    def predicate() -> bool:
        return daemon_matches(daemon_pid, daemon_start, state)

    if not wait_absent(predicate, args.cleanup_wait_seconds) and args.cleanup_owned_daemon:
        # Identity, start time and exact private state path were checked above;
        # never signal a merely matching process name or port owner.
        os.kill(daemon_pid, signal.SIGTERM)
        require(wait_absent(predicate, args.cleanup_wait_seconds),
                "owned_daemon_did_not_exit_after_sigterm")
    require(not predicate(), "owned_daemon_still_running")
    require(wait_absent(lambda: not port_closed(int(seed["port"])), args.cleanup_wait_seconds),
            "owned_daemon_port_still_listening")

    for name in ("daemon.log", "worker.log"):
        path = private / name
        require(path.is_file() and not path.is_symlink(), f"{name}_missing")
        require(stat.S_IMODE(path.stat().st_mode) == 0o600, f"{name}_mode_invalid")

    summary = {
        "schema_version": SUMMARY_SCHEMA,
        "recorded_at": datetime.now(UTC).isoformat(),
        "status": "passed_real_wall_clock",
        "candidate_sha256": seed["candidate_sha256"],
        "driver_sha256": pending.get("driver_sha256"),
        "pending_summary_sha256": sha(pending_path),
        "private_seed_sha256": sha(seed_path),
        "private_result_sha256": sha(result_path),
        "private_daemon_log_sha256": sha(private / "daemon.log"),
        "private_worker_log_sha256": sha(private / "worker.log"),
        "paired_at_utc": seed["paired_at_utc"],
        "verify_after_utc": seed["verify_after_utc"],
        "checked_at_utc": result["checked_at_utc"],
        "production_admin_ttl_seconds": ttl,
        "real_wall_seconds": result["real_wall_seconds"],
        "same_daemon_verified_before_expiry_check": True,
        "pre_expiry_signed_export_verified": pending.get(
            "pre_expiry_signed_export_independently_verified") is True,
        "expired_bearer_export_status": 401,
        "expired_cookie_restore_status": 401,
        "expired_payload_absent": True,
        "owned_worker_absent": True,
        "owned_daemon_absent": True,
        "owned_loopback_port_closed": True,
        "release_acceptance": False,
        "limitations": [
            "This proves the production 12-hour local admin bearer and recovery cookie expire on one continuously running isolated daemon.",
            "The state was copied from an accepted real OpenClaw journey; this is not a second native host execution journey.",
            "Human desktop visual acceptance, formal release signing and other operating systems remain separate gates.",
        ],
    }
    require(summary["pre_expiry_signed_export_verified"],
            "pre_expiry_export_independent_verification_missing")
    write_exclusive(args.output, summary)
    return summary


def main() -> None:
    os.umask(0o022)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--pending-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cleanup-wait-seconds", type=float, default=15.0)
    parser.add_argument("--cleanup-owned-daemon", action="store_true")
    args = parser.parse_args()
    require(0 <= args.cleanup_wait_seconds <= 60, "cleanup_wait_seconds_out_of_range")
    summary = harvest(args)
    print(json.dumps({
        "status": summary["status"],
        "candidate_sha256": summary["candidate_sha256"],
        "real_wall_seconds": summary["real_wall_seconds"],
        "owned_resources_absent": True,
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"LX04 admin expiry harvest: {type(exc).__name__}: {exc}", file=os.sys.stderr)
        raise SystemExit(1) from None
