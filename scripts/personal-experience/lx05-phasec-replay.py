#!/usr/bin/env python3
"""Run a frozen, consecutive real R07 browser replay for phase-c reliability.

Every attempt is retained, including failures. The synthetic model is local;
the OpenClaw CLI, daemon, embedded UI and Chromium are real runtime paths.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path: Path, doc: dict) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    if plan.get("schema_version") != "linux-lx05-phasec-replay-plan/v2" or plan.get("attempts") != 3:
        raise ValueError("frozen three-attempt replay plan required")
    paths = {key: Path(plan[key]).resolve(strict=True) for key in ("binary", "openclaw_root", "node", "driver")}
    expected = {"binary": plan["candidate_sha256"], "driver": plan["driver_sha256"],
                "node": plan["node_sha256"]}
    if any(sha(paths[key]) != value for key, value in expected.items()):
        raise ValueError("frozen replay input drifted")
    if sha(paths["openclaw_root"] / "openclaw.mjs") != plan["host_entry_sha256"]:
        raise ValueError("frozen OpenClaw entrypoint drifted")
    repo = Path(__file__).resolve().parents[2]
    dependencies = {repo / name: digest for name, digest in plan["dependencies"].items()}
    if not dependencies or any(not path.is_file() or sha(path) != digest
                               for path, digest in dependencies.items()):
        raise ValueError("frozen transitive harness dependency drifted")
    if args.private.exists() or args.summary.exists():
        raise FileExistsError("replay output already exists")
    args.private.mkdir(mode=0o700, parents=True)
    attempts = []
    for number in range(1, 4):
        output = args.private / f"attempt-{number}.json"
        log = args.private / f"attempt-{number}.log"
        command = [sys.executable, str(paths["driver"]),
                   "--openclaw-root", str(paths["openclaw_root"]),
                   "--node", str(paths["node"]),
                   "--binary", str(paths["binary"]), "--out", str(output)]
        started = datetime.now(UTC)
        with log.open("x") as handle:
            try:
                process = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT,
                                         timeout=600, check=False)
                exit_code = process.returncode
                timeout = False
            except subprocess.TimeoutExpired:
                exit_code, timeout = None, True
        record = {"attempt": number, "started_at_utc": started.isoformat(),
                  "finished_at_utc": datetime.now(UTC).isoformat(),
                  "exit_code": exit_code, "timeout": timeout,
                  "private_log_sha256": sha(log)}
        if output.exists():
            try:
                report = json.loads(output.read_text())
                results = report.get("results", [])
                phase_c = [item for item in results if item.get("id", "").startswith("r07_step8_")]
                nested = report.get("nested_legs", [])
                record.update({
                    "private_report_sha256": sha(output),
                    "candidate_matches": report.get("binary_sha256") == expected["binary"],
                    "driver_matches": report.get("harness_sha256") == expected["driver"],
                    "check_count": len(report.get("checks", [])),
                    "phase_c_checks": len(phase_c),
                    "phase_c_passed": bool(phase_c) and all(x.get("status") == "pass" for x in phase_c),
                    "nested_checks": [x.get("checks") for x in nested],
                    "reported_passed": report.get("passed") is True,
                })
            except (ValueError, TypeError, KeyError):
                record["report_parse_error"] = True
        record["valid_pass"] = (
            exit_code == 0 and record.get("reported_passed") is True
            and record.get("candidate_matches") is True and record.get("driver_matches") is True
            and record.get("check_count") == 30 and record.get("phase_c_passed") is True
            and record.get("nested_checks") == [31]
        )
        attempts.append(record)
        print(json.dumps({"attempt": number, "passed": record["valid_pass"],
                          "phase_c_passed": record.get("phase_c_passed"), "timeout": timeout}), flush=True)
        if timeout:
            # A timed-out journey may own a child process. Preserve state and
            # stop replaying until its exact process ownership is reviewed.
            break
    result = {"schema_version": "linux-lx05-phasec-replay-result/v1",
              "recorded_at": datetime.now(UTC).isoformat(),
              "candidate_sha256": expected["binary"], "driver_sha256": expected["driver"],
              "plan_sha256": sha(args.plan), "attempts_planned": 3,
              "attempts_run": len(attempts), "passed_count": sum(x["valid_pass"] for x in attempts),
              "failed_count": sum(not x["valid_pass"] for x in attempts),
              "all_passed": len(attempts) == 3 and all(x["valid_pass"] for x in attempts),
              "attempts": attempts,
              "inputs_unchanged_after_run": (
                  all(sha(paths[key]) == value for key, value in expected.items())
                  and sha(paths["openclaw_root"] / "openclaw.mjs") == plan["host_entry_sha256"]
                  and all(sha(path) == digest for path, digest in dependencies.items())
              ),
              "limitations": ["A finite replay does not prove a historical intermittent timeout cannot recur.",
                              "The harness uses a synthetic model and automated browser operator.",
                              "Each attempt creates and cleans its own isolated runtime; logs remain private."]}
    write_new(args.summary, result)
    return 0 if result["all_passed"] and result["inputs_unchanged_after_run"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
