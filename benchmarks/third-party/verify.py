#!/usr/bin/env python3
"""Verify anchored evidence, allocation completeness and independent projections."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import safe_path, sha256


def read_lines(path):
    lines = path.read_text().splitlines()
    if not lines or any(not line for line in lines):
        raise ValueError("empty or interrupted JSONL")
    return [json.loads(line) for line in lines]


def check_events(rows, run_id):
    previous = -1
    for seq, row in enumerate(rows, 1):
        if row.get("sequence") != seq or row.get("run_id") != run_id:
            raise ValueError("event sequence/run mismatch")
        if type(row.get("monotonic_ns")) is not int or row["monotonic_ns"] < previous:
            raise ValueError("event monotonic clock invalid")
        previous = row["monotonic_ns"]


def verify(run: Path, expected: str | None):
    if run.is_symlink():
        raise ValueError("symlink run root forbidden")
    manifest_path = safe_path(run, "manifest.json")
    if expected is not None and sha256(manifest_path) != expected:
        raise ValueError("independent manifest digest mismatch")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") == "siq-lifecycle-attacks-manifest/v1":
        from verify_lifecycle_attacks import verify as verify_lifecycle_attacks
        return verify_lifecycle_attacks(run, expected)
    if manifest.get("schema_version") == "siq-native-lifecycle-manifest/v1":
        from verify_native_lifecycle import verify as verify_native_lifecycle
        return verify_native_lifecycle(run, expected)
    if manifest.get("schema_version") == "siq-discovery-browser-manifest/v1":
        from verify_discovery_browser import verify as verify_discovery_browser
        return verify_discovery_browser(run, expected)
    if manifest.get("schema_version") == "siq-discovery-manifest/v1":
        from verify_discovery import verify as verify_discovery
        return verify_discovery(run, expected)
    if manifest.get("schema_version") == "siq-management-browser-manifest/v1":
        from verify_browser_management import verify as verify_browser_management
        return verify_browser_management(run, expected)
    if manifest.get("schema_version") == "siq-management-http-manifest/v1":
        from verify_management import verify as verify_management
        return verify_management(run, expected)
    if manifest.get("schema_version") == "siq-product-journal-manifest/v1":
        from verify_product_journal import verify as verify_product_journal
        return verify_product_journal(run, expected)
    if manifest.get("schema_version") == "siq-journal-manifest/v1":
        from verify_journal import verify as verify_journal
        return verify_journal(run, expected)
    if manifest.get("schema_version") != "siq-evaluation-manifest/v1":
        raise ValueError("manifest schema unsupported")
    sums_path = safe_path(run, "checksums.json")
    if sha256(sums_path) != manifest["checksums_sha256"]:
        raise ValueError("checksum list replaced")
    sums = json.loads(sums_path.read_text())
    required = {"protocol.json", "allocation.json", "execution-plan.json", "command-events.jsonl",
                "case-events.jsonl", "cases.jsonl", "metrics.json", "findings.json", "report.md"}
    if not required <= set(sums) or "checksums.json" in sums or "manifest.json" in sums:
        raise ValueError("required payload absent or self-reference")
    for name, digest in sums.items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError("payload digest mismatch: " + name)
    protocol = json.loads((run / "protocol.json").read_text())
    if sha256(run / "protocol.json") != manifest["protocol_sha256"]:
        raise ValueError("protocol identity mismatch")
    if sha256(run / "allocation.json") != protocol["allocation_sha256"]:
        raise ValueError("protocol allocation mismatch")
    allocation = json.loads((run / "allocation.json").read_text())
    expected_ids = [row["unit_id"] for row in allocation]
    if not expected_ids or len(expected_ids) != len(set(expected_ids)):
        raise ValueError("empty/duplicate allocation")
    if len(expected_ids) != protocol["allocation_count"] or len(expected_ids) != manifest["allocation_count"]:
        raise ValueError("allocated denominator mismatch")
    cases = read_lines(run / "cases.jsonl")
    ids = [row["unit_id"] for row in cases]
    if len(ids) != len(expected_ids) or set(ids) != set(expected_ids):
        raise ValueError("missing/duplicate/unallocated case")
    events = read_lines(run / "case-events.jsonl")
    check_events(events, manifest["run_id"])
    for kind in ("scheduled", "legacy_capture_finished"):
        recorded = [row["unit_id"] for row in events if row["event"] == kind]
        if len(recorded) != len(expected_ids) or set(recorded) != set(expected_ids):
            raise ValueError("case lifecycle incomplete")
    commands = read_lines(run / "command-events.jsonl")
    check_events(commands, manifest["run_id"])
    planned = json.loads((run / "execution-plan.json").read_text())
    by_name = {row["command_id"]: row for row in planned}
    if list(by_name) != protocol["operations"] or len(by_name) != len(planned):
        raise ValueError("command plan mismatch")
    states = {}
    for row in commands:
        name = row.get("command_id")
        if name not in by_name:
            raise ValueError("unregistered command")
        event = row["event"]
        if event == "command_started":
            if name in states or row["argv"] != by_name[name]["argv"]:
                raise ValueError("command replay or argv mismatch")
            states[name] = "started"
        elif event == "command_finished":
            if states.get(name) != "started" or row["argv"] != by_name[name]["argv"]:
                raise ValueError("finished command without matching start")
            states[name] = row
        elif event == "command_blocked":
            if name in states:
                raise ValueError("blocked command replay")
            states[name] = row
        else:
            raise ValueError("unknown command event")
    if set(states) != set(by_name) or any(not isinstance(row, dict) for row in states.values()):
        raise ValueError("unaccounted command")
    for row in cases:
        for ref in row["evidence_refs"]:
            if ref not in sums:
                raise ValueError("unsealed referenced material")
        suite = f"runtime-r{row['repetition']}" if row["suite"] == "runtime" else "controls"
        report_path = run / "raw-private" / f"{suite}.json"
        if report_path.exists():
            if report_path.relative_to(run).as_posix() not in sums:
                raise ValueError("unsealed legacy report")
            report = json.loads(report_path.read_text())
            captured = {item.get("scenario_id", item.get("case", {}).get("id")): item
                        for item in report.get("observations", report.get("cases", []))}
            if len(captured) != len(report.get("observations", report.get("cases", []))):
                raise ValueError("duplicate legacy case")
            observation = captured.get(row["case_id"])
        else:
            observation = None
        if row["legacy_observation"] != observation:
            raise ValueError("case projection differs from raw capture: " + row["unit_id"])
        if row["harm_observed"] is not None or row["utility_completed"] is not None:
            raise ValueError("legacy observations promoted to new independent gold")
        if row["assertion_status"] == "pass":
            ver = suite.replace("runtime", "evidence") if suite.startswith("runtime") else "controls-verify"
            if observation is None or states[ver].get("exit_code") != 0 or observation.get("expectation_violations"):
                raise ValueError("invalid passing assertion")
    metrics = json.loads((run / "metrics.json").read_text())
    recalculated = {"allocated": len(expected_ids),
                    "captured": sum(row["execution_status"] == "completed" for row in cases),
                    "assertion_pass": sum(row["assertion_status"] == "pass" for row in cases),
                    "inconclusive": sum(row["assertion_status"] == "inconclusive" for row in cases)}
    if any(metrics.get(key) != value for key, value in recalculated.items()):
        raise ValueError("summary differs from cases")
    failures = [name for name in protocol["operations"]
                if states[name].get("exit_code") != 0 or states[name].get("error")]
    if metrics["failed_commands"] != failures:
        raise ValueError("failed command projection mismatch")
    outcome = 1 if any(row["assertion_status"] == "fail" for row in cases) else 2 if failures or metrics["inconclusive"] else 0
    return {"integrity": "verified_against_supplied_digest" if expected else "internal_consistency_only",
            "external_identity": "not_established_by_self_contained_package", "product_outcome_exit_code": outcome,
            **recalculated}, outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--expected-manifest-sha256")
    args = parser.parse_args()
    try:
        result, code = verify(args.run, args.expected_manifest_sha256)
        print(json.dumps(result))
        return code
    except (ValueError, KeyError, OSError, TypeError) as exc:
        print(json.dumps({"integrity": "failed", "reason": str(exc)}), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
