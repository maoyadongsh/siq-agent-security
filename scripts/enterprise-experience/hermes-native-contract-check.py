#!/usr/bin/env python3
"""CL-03-HERMES-NATIVE one-key native acceptance for the Hermes connector.

Builds the connector from the CURRENT (uncommitted) worktree into an isolated
temporary directory — never the checked-in connectors/hermes/hermes binary —
then runs static checks and the native NDJSON protocol acceptance tests
(native_protocol_test.go / native_protocol_linux_test.go) and records an
evidence bundle.

Properties:
  * subprocess argument arrays only, no shell=True;
  * uses installed tools only (go, gofmt, git, optional ruff); GOPROXY=off
    proves no network download happens during build/test;
  * --evidence-dir is created fresh; an existing directory is never
    overwritten;
  * every check reports its actual exit status; nothing is hardcoded passed;
  * saved logs are redacted (token/key/password shapes) and never include
    environment variables or secret bodies;
  * the temporary run directory it creates is removed; the evidence directory
    and other people's temp directories are left untouched;
  * overall exit status is non-zero if any check fails. A failing check is a
    finding, not a script bug: today TestNativeOversizedFileTruncationMustBeFlagged
    reproduces NATIVE-FINDING-01 and fails honestly.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONNECTOR = ROOT / "connectors" / "hermes"
PROTOCOL = ROOT / "edge" / "agent" / "protocol"
NEW_GO_FILES = [
    CONNECTOR / "native_protocol_test.go",
    CONNECTOR / "native_protocol_linux_test.go",
]
SOURCE_FILES = (
    sorted(CONNECTOR.glob("*.go"))
    + [CONNECTOR / "go.mod"]
    + sorted(PROTOCOL.glob("*.go"))
    + [PROTOCOL.parent / "go.mod"]
    + [Path(__file__).resolve()]
)

# Redaction shapes mirror siq.redaction.v1 (edge/agent/protocol/redact.go).
REDACTIONS = [
    re.compile(r"(?i)(?:sk|pk)-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)(?:api[_-]?key|apikey)\s*[:=]\s*[^\s,;\"]{4,}"),
    re.compile(r"(?i)(?:password|passwd|pwd)\s*[:=]\s*[^\s,;\"]{4,}"),
    re.compile(r"(?i)(?:secret|token)\s*[:=]\s*[^\s,;\"]{4,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=#-]{4,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"(?s)-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"(?i)[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@"),
]


def redact(text: str) -> str:
    for pattern in REDACTIONS:
        text = pattern.sub("[REDACTED]", text)
    return text


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def minimal_env() -> dict:
    """Environment for build/test subprocesses: enough for the Go toolchain,
    nothing sensitive, and GOPROXY=off to prove no network fetch occurs.
    The mapping is recorded as key names only, never values."""
    env = {}
    for key in ("PATH", "HOME", "LANG", "LC_ALL", "TZ", "GOCACHE", "GOPATH", "TMPDIR"):
        if key in os.environ:
            env[key] = os.environ[key]
    env["GOPROXY"] = "off"
    env["GOFLAGS"] = "-mod=readonly"
    return env


def run_check(name: str, argv: list, cwd: Path, timeout: int, log_dir: Path) -> dict:
    started = time.time()
    record = {
        "name": name,
        "argv": [str(a) for a in argv],
        "cwd": str(cwd),
        "timeout_s": timeout,
    }
    try:
        proc = subprocess.run(
            [str(a) for a in argv],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=minimal_env(),
            stdin=subprocess.DEVNULL,
        )
        record["exit_code"] = proc.returncode
        record["passed"] = proc.returncode == 0
        out, err = redact(proc.stdout), redact(proc.stderr)
    except subprocess.TimeoutExpired as exc:
        record["exit_code"] = None
        record["passed"] = False
        record["timed_out"] = True
        out = redact(exc.stdout or "") if isinstance(exc.stdout, str) else ""
        err = redact(exc.stderr or "") if isinstance(exc.stderr, str) else ""
    record["duration_s"] = round(time.time() - started, 3)
    log_name = f"{len(list(log_dir.glob('*.log'))) + 1:02d}-{name}.log"
    (log_dir / log_name).write_text(
        f"argv: {json.dumps(record['argv'])}\ncwd: {record['cwd']}\n"
        f"exit_code: {record['exit_code']}\nduration_s: {record['duration_s']}\n"
        f"--- stdout ---\n{out}\n--- stderr ---\n{err}\n"
    )
    record["log"] = f"logs/{log_name}"
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True,
                        help="fresh directory for the evidence bundle; must not exist")
    args = parser.parse_args()
    if args.evidence_dir.exists():
        print(f"refusing to overwrite existing evidence dir: {args.evidence_dir}", file=sys.stderr)
        return 2
    log_dir = args.evidence_dir / "logs"
    log_dir.mkdir(parents=True)

    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    summary = {
        "task": "CL-03-HERMES-NATIVE",
        "started_at": started,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "checks": [],
        "notes": [
            "Build and tests ran against the UNCOMMITTED worktree; git HEAD does "
            "not identify the tested sources. Source identity is the per-file "
            "sha256 list below.",
            "The checked-in connectors/hermes/hermes binary was NOT used; the "
            "acceptance binary was built into this run's own temp directory.",
            "Logs are redacted with siq.redaction.v1-shaped rules; environment "
            "variable values and secret bodies are never recorded.",
        ],
    }

    # Toolchain identity (actual command output, not assumed).
    go_version = subprocess.run(["go", "version"], capture_output=True, text=True, timeout=30)
    summary["platform"]["go"] = go_version.stdout.strip()

    # Source identity: HEAD for reference + per-file digests as the real identity.
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=30)
    status = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                            capture_output=True, text=True, timeout=60)
    status_lines = [ln for ln in status.stdout.splitlines() if ln.strip()]
    (args.evidence_dir / "git-status-porcelain.txt").write_text(status.stdout)
    summary["source_identity"] = {
        "git_head_reference_only": head.stdout.strip(),
        "worktree_dirty": bool(status_lines),
        "worktree_changed_paths": len(status_lines),
        "build_identity": "uncommitted-worktree",
        "files": [
            {"path": str(p.relative_to(ROOT)), "sha256": sha256_file(p), "bytes": p.stat().st_size}
            for p in SOURCE_FILES
        ],
    }

    checks = summary["checks"]
    with tempfile.TemporaryDirectory(prefix="siq-hermes-native-run-") as run_dir:
        binary = Path(run_dir) / "hermes-connector-native-check"

        checks.append(run_check("gofmt-new-files", ["gofmt", "-l"] + NEW_GO_FILES,
                                CONNECTOR, 60, log_dir))
        checks[-1]["passed"] = checks[-1]["passed"] and checks[-1]["exit_code"] == 0
        # gofmt -l lists unformatted files: clean means empty stdout.
        log_text = (log_dir / checks[-1]["log"].split("/", 1)[1]).read_text()
        stdout_part = log_text.split("--- stdout ---\n", 1)[1].split("--- stderr ---", 1)[0].strip()
        if stdout_part:
            checks[-1]["passed"] = False
            checks[-1]["detail"] = f"gofmt lists unformatted files: {stdout_part}"

        checks.append(run_check("go-vet", ["go", "vet", "./..."], CONNECTOR, 300, log_dir))

        build = run_check("native-build", ["go", "build", "-o", str(binary), "."],
                          CONNECTOR, 300, log_dir)
        checks.append(build)
        if build["passed"] and binary.exists():
            summary["binary"] = {
                "path_note": "inside the run temp dir, removed after the run",
                "sha256": sha256_file(binary),
                "bytes": binary.stat().st_size,
            }
            binary_check = run_check("native-binary-smoke", [str(binary), "--serve"],
                                     CONNECTOR, 10, log_dir)
            # --serve with stdin closed must exit 0 immediately (EOF on stdin).
            checks.append(binary_check)
        else:
            summary["binary"] = {"build_failed": True}

        checks.append(run_check("go-test-race-all", ["go", "test", "-race", "-count=1", "./..."],
                                CONNECTOR, 600, log_dir))
        checks.append(run_check("go-test-race-native-focused",
                                ["go", "test", "-race", "-count=1", "-run", "TestNative", "-v", "."],
                                CONNECTOR, 600, log_dir))

        checks.append(run_check("git-diff-check", ["git", "-C", str(ROOT), "diff", "--check"],
                                ROOT, 120, log_dir))
        if shutil.which("ruff"):
            checks.append(run_check("ruff-self", ["ruff", "check", str(Path(__file__).resolve())],
                                    ROOT, 120, log_dir))
        else:
            summary["notes"].append("ruff not installed; ruff-self check not run")

    summary["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    summary["overall_passed"] = all(c["passed"] for c in checks)
    summary["failed_checks"] = [c["name"] for c in checks if not c["passed"]]
    (args.evidence_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({
        "overall_passed": summary["overall_passed"],
        "failed_checks": summary["failed_checks"],
        "evidence_dir": str(args.evidence_dir),
    }, indent=2))
    return 0 if summary["overall_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
