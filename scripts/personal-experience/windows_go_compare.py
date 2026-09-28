"""Compare real Windows Go runs; baseline failures remain failures in the report."""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path


def summarize(raw, code):
    packages, failed, skipped = {}, set(), set()
    for line in raw.splitlines():
        event = json.loads(line)
        package, test, action = event.get("Package"), event.get("Test"), event.get("Action")
        if not package:
            continue
        if test and action in {"fail", "skip"}:
            (failed if action == "fail" else skipped).add(package + "/" + test)
        if not test and action in {"pass", "fail", "skip"}:
            packages[package] = action
    unexplained = [p for p, a in packages.items() if a == "fail" and not any(t.startswith(p + "/") for t in failed)]
    if code not in (0, 1) or not packages or unexplained or bool(code) != bool(failed):
        raise ValueError("incomplete/build/tool failure; not a comparable test run")
    return {"exit_code": code, "packages": packages, "failed_tests": sorted(failed), "skipped_tests": sorted(skipped)}


def compare(candidate, baseline):
    if set(candidate["packages"]) != set(baseline["packages"]):
        raise ValueError("package inventories differ; requires review")
    return {
        "new_failures": sorted(set(candidate["failed_tests"]) - set(baseline["failed_tests"])),
        "new_skips": sorted(set(candidate["skipped_tests"]) - set(baseline["skipped_tests"])),
        "candidate_full_suite_passed": candidate["exit_code"] == 0,
        "workbuddy_native_acceptance": "not_run",
    }


def run_suite(root, output, label):
    command = ["go", "test", "-json", "-p", "2", "-count=1", "-timeout", "10m", "./..."]
    with (
        (output / (label + ".jsonl")).open("w", encoding="utf-8") as stdout,
        (output / (label + ".stderr.txt")).open("w", encoding="utf-8") as stderr,
    ):
        result = subprocess.run(command, cwd=root / "apps/agentshield", stdout=stdout, stderr=stderr, timeout=900, check=False)
    (output / (label + ".exit.txt")).write_text(str(result.returncode), encoding="utf-8")
    summary = summarize((output / (label + ".jsonl")).read_text(encoding="utf-8"), result.returncode)
    expected = subprocess.check_output(["go", "list", "./..."], cwd=root / "apps/agentshield", text=True).splitlines()
    if set(expected) != set(summary["packages"]):
        raise ValueError("full module package results missing")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    if os.name != "nt" or not re.fullmatch(r"[0-9a-f]{40}", args.base):
        parser.error("requires Windows and an exact base commit")
    root = Path(__file__).resolve().parents[2]
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    base = output / "base"
    subprocess.run(["git", "worktree", "add", "--detach", str(base), args.base], cwd=root, check=True)
    report = {
        "candidate_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "base_commit": args.base,
        "go_version": subprocess.check_output(["go", "version"], text=True).strip(),
    }
    # Keep both raw runs, including failures; never upload state dirs or keys.
    report["candidate"] = run_suite(root, output, "candidate")
    report["baseline"] = run_suite(base, output, "baseline")
    report.update(compare(report["candidate"], report["baseline"]))
    raw = json.dumps(report, ensure_ascii=False, indent=2)
    (output / "comparison.json").write_text(raw, encoding="utf-8")
    print(raw)
    return 1 if report["new_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
