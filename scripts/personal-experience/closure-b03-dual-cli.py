#!/usr/bin/env python3
"""Two actual binaries refusing future/corrupt fixture state, without migration.

This exercises real CLI dispatch with synthetic incompatible markers. It does
not claim a released future format or complete per-command healthy workflows.
"""
import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def snapshot(root):
    return {str(p.relative_to(root)): ("directory" if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(root.rglob("*"))}


def run(old, new, out):
    os.umask(0o077)
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    checks = []
    # Valid mutation commands deliberately receive no target/confirmation.
    # The incompatible-state guard must run before argument dispatch, which
    # keeps even a regressed binary from operating on a system service.
    commands = ["admit", "grant", "adapter", "setup", "client-install", "service-upgrade",
                "service-rollback", "service-register", "service-unregister", "teardown"]
    for label, binary in (("old", old), ("new", new)):
        with tempfile.TemporaryDirectory(prefix="siq-b03-cli-") as td:
            root = Path(td)
            state, home = root / "state", root / "home"
            state.mkdir(mode=0o700)
            home.mkdir(mode=0o700)
            env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "TZ")}
            env.update(HOME=str(home), SIQ_AGENT_SECURITY_STATE_DIR=str(state))
            initialized = subprocess.run([str(binary), "init"], env=env, capture_output=True, timeout=20, check=False)
            if initialized.returncode != 0:
                raise RuntimeError("isolated initialization failed")
            marker = state / "state-format.json"
            if not marker.exists():
                marker.write_text(json.dumps({"schema": "state-format/v1", "program_version": "fixture",
                    "format_version": 1, "published_at": datetime.now(UTC).isoformat()}))
            healthy = json.loads(marker.read_text())
            # v2 format_version is fixed at 2; raising it would only test
            # corruption. Raise the supported writer floor on a valid v2
            # marker to exercise the actual newer-program rejection.
            future = (dict(healthy, min_writer=999) if healthy["schema"] == "state-format/v2"
                      else dict(healthy, format_version=999))
            for kind, payload in (("future", json.dumps(future)), ("corrupt", "{invalid-json")):
                marker.write_text(payload)
                before = snapshot(root)
                for command in commands:
                    result = subprocess.run([str(binary), command], env=env, capture_output=True, timeout=20, check=False)
                    # Recovery commands are stable operator guidance emitted by
                    # the central gate, not an unrelated usage/network failure.
                    response = result.stdout + result.stderr
                    category = (b"format requires a newer program" if kind == "future"
                                else b"invalid state format marker or directory")
                    ok = (result.returncode == 1 and b"state-status" in response
                          and b"state-migrate" in response and category in response)
                    checks.append({"binary": label, "marker": kind, "command": command,
                                   "exit": result.returncode, "passed": ok and snapshot(root) == before})
                result = subprocess.run([str(binary), "state-status"], env=env, capture_output=True, timeout=20, check=False)
                checks.append({"binary": label, "marker": kind, "command": "state-status",
                               "exit": result.returncode, "passed": result.returncode == 0 and snapshot(root) == before})
    report = {"schema_version": "closure-b03-dual-cli/v1", "recorded_at": datetime.now(UTC).isoformat(),
              "binary_sha256": {label: hashlib.sha256(p.read_bytes()).hexdigest()
                                for label, p in (("old", old), ("new", new))},
              "evidence_level": "real_cli_synthetic_state_markers", "checks": checks,
              "passed": all(c["passed"] for c in checks),
              "boundary": "not an actual future-format release; no system service command reached its operational body"}
    data = (json.dumps(report, indent=2) + "\n").encode()
    (out / "report.json").write_bytes(data)
    (out / "SHA256SUMS").write_text(hashlib.sha256(data).hexdigest() + "  report.json\n")
    print(json.dumps({"passed": report["passed"], "checks": len(checks)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--old", required=True, type=Path)
    p.add_argument("--new", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args()
    raise SystemExit(run(args.old.resolve(strict=True), args.new.resolve(strict=True), args.out))
