#!/usr/bin/env python3
"""Seed and verify a real 12-hour local admin-session expiry in isolation.

The worker keeps the same daemon alive until its bearer and recovery cookie
expire naturally. All credentials and daemon logs stay in an ignored private
directory. No clock injection or production TTL override is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from http import HTTPStatus
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path: Path, value: dict) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def request(port: int, route: str, *, method="GET", body=None, bearer="", cookie=""):
    raw = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    if cookie:
        headers["Cookie"] = cookie
        headers["X-SIQ-Session"] = "1"
    req = Request(f"http://127.0.0.1:{port}{route}", data=raw, method=method, headers=headers)
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(req, timeout=15) as response:
            payload = json.loads(response.read())
            return response.status, payload, response.headers.get("Set-Cookie", "")
    except HTTPError as error:
        return error.code, json.loads(error.read()), error.headers.get("Set-Cookie", "")


def owned(pid: int, starttime: str, state: Path) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        current = stat.rsplit(") ", 1)[1].split()[19]
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
        return current == starttime and str(state) in cmdline and " serve " in f" {cmdline} "
    except (FileNotFoundError, PermissionError):
        return False


def starttime(pid: int) -> str:
    return Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[19]


def seed(args) -> None:
    private = args.private.resolve()
    if private.exists():
        raise FileExistsError("exclusive private expiry run already exists")
    private.mkdir(mode=0o700, parents=True)
    state = private / "state"
    shutil.copytree(args.source_state.resolve(strict=True), state)
    home = private / "home"
    home.mkdir(mode=0o700)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    binary = args.binary.resolve(strict=True)
    log = private / "daemon.log"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("SIQ_", "B2B3_"))}
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    with log.open("x") as handle:
        daemon = subprocess.Popen(
            [str(binary), "serve", "-state-dir", str(state), "-port", str(port)],
            env=env, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True,
        )
    try:
        birth = starttime(daemon.pid)
        deadline = time.monotonic() + 30
        code = None
        while time.monotonic() < deadline:
            if daemon.poll() is not None:
                raise RuntimeError("owned daemon exited during seed")
            match = re.search(r"admin pairing code.*?([0-9a-f]{4}(?:-[0-9a-f]{4}){3})", log.read_text())
            if match:
                code = match.group(1)
                break
            time.sleep(0.2)
        if not code:
            raise RuntimeError("owned daemon did not publish a pairing code")
        for _ in range(30):
            try:
                status, health, _ = request(port, "/healthz")
                if status == 200 and health.get("status") == "ready":
                    break
            except OSError:
                pass
            time.sleep(0.2)
        else:
            raise RuntimeError("owned daemon health unavailable")
        before = time.time()
        status, pair, cookie = request(port, "/v1/pair", method="POST", body={"code": code, "remember": True}, cookie="probe=1")
        if status != HTTPStatus.OK or pair.get("expires_in") != 43200 or not cookie:
            raise RuntimeError("12-hour paired session not established")
        bearer = pair["session"]
        cookie = cookie.split(";", 1)[0]
        status, activity, _ = request(port, "/v1/task-activities?limit=100", bearer=bearer)
        if status != 200:
            raise RuntimeError("task activity unavailable before expiry")
        rows = [item for item in activity["items"] if item.get("binding", {}).get("platform") == "openclaw"]
        if not rows:
            raise RuntimeError("isolated state has no OpenClaw task activity")
        activity_id = rows[0]["activity_id"]
        route = f"/v1/task-activities/{activity_id}/export?snapshot={activity['snapshot']}"
        status, export, _ = request(port, route, bearer=bearer)
        if status != 200 or not export.get("receipts") or export.get("activity_id") != activity_id:
            raise RuntimeError("task export unavailable before expiry")
        if not owned(daemon.pid, birth, state):
            raise RuntimeError("owned daemon identity changed")
        seed_doc = {
            "schema_version": "linux-lx04-admin-natural-expiry-seed/v1",
            "candidate_sha256": sha(binary),
            "source_state_sha256": hashlib.sha256(
                json.dumps({str(p.relative_to(state)): sha(p) for p in sorted(state.rglob("*")) if p.is_file()}, sort_keys=True).encode()
            ).hexdigest(),
            "daemon_pid": daemon.pid, "daemon_starttime": birth, "port": port,
            "state": str(state), "bearer": bearer, "cookie": cookie, "export_route": route,
            "export_before_sha256": hashlib.sha256(json.dumps(export, sort_keys=True).encode()).hexdigest(),
            "paired_after_epoch": before, "not_before_epoch": before + 43202,
            "paired_at_utc": datetime.fromtimestamp(before, UTC).isoformat(),
            "verify_after_utc": datetime.fromtimestamp(before + 43202, UTC).isoformat(),
        }
        write_new(private / "seed.json", seed_doc)
        with (private / "worker.log").open("x") as worker_log:
            worker = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "verify", "--private", str(private), "--wait"],
                stdout=worker_log, stderr=subprocess.STDOUT, start_new_session=True,
            )
        write_new(private / "worker.json", {"pid": worker.pid, "starttime": starttime(worker.pid)})
        print(json.dumps({"seeded": True, "candidate_sha256": seed_doc["candidate_sha256"],
                          "verify_after_utc": seed_doc["verify_after_utc"], "daemon_pid": daemon.pid,
                          "worker_pid": worker.pid}))
    except BaseException:
        if daemon.poll() is None and owned(daemon.pid, birth, state):
            daemon.terminate()
            daemon.wait(timeout=10)
        raise


def verify(args) -> None:
    private = args.private.resolve(strict=True)
    seed_doc = json.loads((private / "seed.json").read_text())
    due = seed_doc["not_before_epoch"]
    if args.wait:
        while time.time() < due:
            time.sleep(min(300, max(1, due - time.time())))
    elif time.time() < due:
        raise RuntimeError("natural expiry deadline has not elapsed")
    pid, state = seed_doc["daemon_pid"], Path(seed_doc["state"])
    report = {"schema_version": "linux-lx04-admin-natural-expiry-result/v1",
              "candidate_sha256": seed_doc["candidate_sha256"], "checked_at_utc": datetime.now(UTC).isoformat(),
              "real_wall_seconds": time.time() - seed_doc["paired_after_epoch"],
              "same_daemon_alive": owned(pid, seed_doc["daemon_starttime"], state)}
    try:
        if not report["same_daemon_alive"]:
            raise RuntimeError("seed daemon identity no longer live")
        port = seed_doc["port"]
        health_status, health, _ = request(port, "/healthz")
        export_status, export, _ = request(port, seed_doc["export_route"], bearer=seed_doc["bearer"])
        restore_status, restore, _ = request(port, "/v1/session/restore", method="POST", body={}, cookie=seed_doc["cookie"])
        report.update({"health_ready": health_status == 200 and health.get("status") == "ready",
                       "expired_export_status": export_status, "expired_restore_status": restore_status,
                       "export_payload_absent": "receipts" not in export and "sources" not in export,
                       "restore_session_absent": "session" not in restore})
        report["passed"] = (report["health_ready"] and export_status == 401 and restore_status == 401
                            and report["export_payload_absent"] and report["restore_session_absent"])
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        report.update({"passed": False, "error_category": type(error).__name__})
    finally:
        write_new(private / "result.json", report)
        if owned(pid, seed_doc["daemon_starttime"], state):
            os.kill(pid, signal.SIGTERM)
    print(json.dumps({"passed": report["passed"], "real_wall_seconds": report["real_wall_seconds"]}))
    if not report["passed"]:
        raise SystemExit(1)


def main() -> None:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    seed_parser = subs.add_parser("seed")
    seed_parser.add_argument("--private", type=Path, required=True)
    seed_parser.add_argument("--source-state", type=Path, required=True)
    seed_parser.add_argument("--binary", type=Path, required=True)
    verify_parser = subs.add_parser("verify")
    verify_parser.add_argument("--private", type=Path, required=True)
    verify_parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()
    if args.action == "seed":
        seed(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
