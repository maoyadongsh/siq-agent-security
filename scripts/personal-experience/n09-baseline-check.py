#!/usr/bin/env python3
"""Validate v2 evidence integrity and row-level coverage, not product acceptance."""

import argparse
import re
from datetime import datetime
from pathlib import Path

from n09_evidence import Invalid, passed_checks, read_json, report_binary, require, safe_ref, sha256

ITEMS = [f"J{i}" for i in range(1, 12)]
PLATFORMS = ["hermes", "openclaw", "workbuddy"]
OS_NAMES = ["linux", "macos", "windows"]
STATUSES = ["native", "controlled_start", "unavailable", "unverified", "blocked", "out_of_scope"]
REASONS = ["environment_unavailable", "upstream_runtime_unconfirmed", "host_capability_missing"]
CLASSIFICATIONS = ["static_check", "unit_test", "component_integration", "native_machine", "complete_acceptance"]


def keys(value, required, optional=()):
    require(isinstance(value, dict), "object required")
    require(set(required) <= value.keys() <= set(required) | set(optional), "unknown or missing fields")


def digest(value):
    require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value), "invalid sha256")


def timestamp(value):
    require(isinstance(value, str), "timestamp type")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(result.utcoffset() is not None, "timestamp needs timezone")
        return result
    except ValueError as exc:
        raise Invalid("invalid timestamp") from exc


def check(matrix_path, repo, summary_path=None):
    matrix = read_json(matrix_path)
    keys(matrix, ("schema_version", "batch", "recorded_at", "legs", "cells", "evidence_sha256", "notes"))
    require(matrix["schema_version"] == "personal-acceptance-baseline/v2", "v2 row coverage required")
    require(isinstance(matrix["batch"], str) and matrix["batch"], "batch")
    timestamp(matrix["recorded_at"])
    require(isinstance(matrix["notes"], list) and all(isinstance(n, str) for n in matrix["notes"]), "notes")
    require(isinstance(matrix["evidence_sha256"], dict), "evidence hashes")
    for ref, recorded in matrix["evidence_sha256"].items():
        digest(recorded)
        require(sha256(safe_ref(repo, ref)) == recorded, "evidence sha mismatch")
    legs = matrix["legs"]
    require(isinstance(legs, list) and legs, "legs")
    by_id, by_ref = {}, {}
    for leg in legs:
        keys(leg, ("leg_id", "platform", "os", "binary_sha256", "started_at", "finished_at", "report_ref", "report_sha256", "checks_passed"))
        name = leg["leg_id"]
        require(isinstance(name, str) and name and name not in by_id, "duplicate or invalid leg id")
        require(leg["platform"] in PLATFORMS and leg["os"] in OS_NAMES, "leg environment")
        digest(leg["binary_sha256"])
        digest(leg["report_sha256"])
        require(timestamp(leg["finished_at"]) >= timestamp(leg["started_at"]), "leg time order")
        ref = leg["report_ref"]
        path = safe_ref(repo, ref)
        require(ref not in by_ref, "duplicate leg report")
        require(matrix["evidence_sha256"].get(ref) == leg["report_sha256"], "missing or inconsistent evidence hash")
        report = read_json(path)
        names = passed_checks(report)
        require(type(leg["checks_passed"]) is int and leg["checks_passed"] == len(names), "check count mismatch")
        require(report_binary(report) == leg["binary_sha256"], "report binary mismatch")
        runtime = report.get("runtime", {})
        for field in ("os", "platform"):
            require(field not in runtime or runtime[field] == leg[field], "report environment mismatch")
        by_id[name] = (leg, report, names)
        by_ref[ref] = name
    cells = matrix["cells"]
    require(isinstance(cells, list) and len(cells) == 9, "nine cells required")
    seen = set()
    for cell in cells:
        keys(cell, ("platform", "os", "rows"))
        env = (cell["platform"], cell["os"])
        require(env[0] in PLATFORMS and env[1] in OS_NAMES and env not in seen, "duplicate or invalid cell")
        seen.add(env)
        rows = cell["rows"]
        require(isinstance(rows, list) and len(rows) == 11, "eleven rows required")
        require(all(isinstance(row, dict) for row in rows) and [r.get("item") for r in rows] == ITEMS, "row items")
        if any(row.get("status") == "out_of_scope" for row in rows):
            require(env == ("workbuddy", "linux") and all(row.get("status") == "out_of_scope" for row in rows),
                    "only the entire Linux/WorkBuddy cell may be out of scope")
        for row in rows:
            keys(row, ("item", "status", "classification", "evidence_refs", "coverage", "note"), ("reason", "required_evidence"))
            require(row["status"] in STATUSES and row["classification"] in CLASSIFICATIONS, "closed-set status/classification")
            require(isinstance(row["note"], str), "row note")
            if "required_evidence" in row:
                require(isinstance(row["required_evidence"], str) and row["required_evidence"], "evidence requirement type")
            if row["status"] == "out_of_scope":
                require(row.get("reason") == "product_scope_excluded" and row["classification"] == "static_check"
                        and row["note"] and not row["evidence_refs"] and not row["coverage"]
                        and "required_evidence" not in row,
                        "out-of-scope rows cannot claim runtime evidence or acceptance")
            elif row["status"] == "blocked":
                require(row.get("reason") in REASONS, "blocked reason")
            else:
                require("reason" not in row, "unexpected reason")
            if row["status"] in ("unverified", "unavailable"):
                require(isinstance(row.get("required_evidence"), str) and row["required_evidence"], "missing evidence requirements")
            refs, coverage = row["evidence_refs"], row["coverage"]
            require(isinstance(refs, list) and all(isinstance(r, str) for r in refs) and len(set(refs)) == len(refs), "row refs")
            require(isinstance(coverage, list), "coverage type")
            cited = set()
            for entry in coverage:
                keys(entry, ("leg_id", "checks"))
                name = entry["leg_id"]
                require(isinstance(name, str) and name in by_id and name not in cited, "coverage leg")
                cited.add(name)
                leg, report, names = by_id[name]
                require((leg["platform"], leg["os"]) == env, "cross-platform evidence")
                checks = entry["checks"]
                require(isinstance(checks, list) and checks and all(isinstance(c, str) for c in checks)
                        and len(set(checks)) == len(checks) and set(checks) <= names, "unproven check coverage")
                require(leg["report_ref"] in refs, "coverage missing ref")
                if row["classification"] == "complete_acceptance":
                    scope = report.get("acceptance_scope", {})
                    require(isinstance(scope, dict) and scope.get("platform") == env[0]
                            and scope.get("os") == env[1]
                            and isinstance(scope.get("completed_items"), list)
                            and all(isinstance(item, str) and item in ITEMS for item in scope["completed_items"])
                            and len(set(scope["completed_items"])) == len(scope["completed_items"])
                            and row["item"] in scope["completed_items"],
                            "partial leg cannot certify complete acceptance")
            require(set(refs) == {by_id[name][0]["report_ref"] for name in cited}, "refs lack explicit coverage")
            if row["status"] in ("native", "controlled_start"):
                require(coverage, "positive row without coverage")
            if row["classification"] == "complete_acceptance":
                require(row["status"] in ("native", "controlled_start") and coverage
                        and not row.get("required_evidence"), "incomplete row marked complete")
    if summary_path is not None:
        summary = read_json(summary_path)
        require(summary.get("passed") is True, "summary failed")
        entries = summary.get("legs")
        require(isinstance(entries, list) and all(isinstance(x, dict) for x in entries), "summary legs")
        require(len(entries) == len(by_id) and {x.get("leg_id") for x in entries} == set(by_id), "summary leg set")
        for entry in entries:
            leg = by_id[entry["leg_id"]][0]
            require(entry.get("passed") is True and entry.get("report_sha256") == leg["report_sha256"], "summary mismatch")
    return []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    try:
        check(args.matrix, args.repo, args.summary)
    except (Invalid, TypeError, KeyError, ValueError) as exc:
        print(f"INVALID: {exc}")
        raise SystemExit(1)
    print("baseline matrix valid (integrity and declared coverage only; not release acceptance)")


if __name__ == "__main__":
    main()
