#!/usr/bin/env python3
"""Build a v2 matrix from this review's B04 HTTP and B05 native legs only.

Keep the nine environment cells and J1-J11 denominator. Historical runs and
test-release lifecycle binaries cannot certify this candidate's native rows.
"""
import argparse
import importlib.util
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from n09_evidence import (
    passed_checks,
    read_json,
    report_binary,
    require,
    safe_ref,
    sha256,
)

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("matrix_requirements", Path(__file__).with_name("n09-current-candidate-matrix.py"))
baseline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(baseline)


def build(b04_ref, b05_ref):
    legs, hashes, names, candidates = [], {}, {}, set()
    for name, ref in (("B04_HTTP", b04_ref), ("B05_NATIVE", b05_ref)):
        path = safe_ref(ROOT, ref)
        report = read_json(path)
        names[name] = passed_checks(report)
        candidate = report_binary(report)
        candidates.add(candidate)
        hashes[ref] = sha256(path)
        legs.append({"leg_id": name, "platform": "openclaw", "os": "linux",
                     "binary_sha256": candidate, "report_ref": ref,
                     "report_sha256": hashes[ref], "checks_passed": len(names[name]),
                     "started_at": report["recorded_at"], "finished_at": report["recorded_at"]})
    require(len(candidates) == 1, "mixed candidate binaries")
    refs = {leg["leg_id"]: leg["report_ref"] for leg in legs}
    rows = []
    for item, needed in baseline.REQUIREMENTS.items():
        row = {"item": item, "status": "unverified", "classification": "static_check",
               "evidence_refs": [], "coverage": [], "note": "Not fully exercised by this batch.",
               "required_evidence": needed}
        source, checks = None, []
        if item == "J8":
            source = "B05_NATIVE"
            checks = ["positive_control_marker_write_executed_with_service_up",
                      "service_down_denies_file_write_before_execution",
                      "service_down_denies_read_without_content_leak",
                      "service_down_zero_loopback_egress_from_denied_exec",
                      "managed_audit_only_override_still_fails_closed"]
            row.update(status="controlled_start", classification="native_machine",
                       note="Real OpenClaw local entrypoint; deterministic local model; denied file/network effects independently observed. No OS sandbox or paid-model claim.")
            row.pop("required_evidence")
        elif item == "J9":
            source = "B05_NATIVE"
            checks = ["same_port_restart_recovers_pairing", "pending_lines_promoted_onto_signed_receipt_chain",
                      "recovered_service_allows_authorized_read", "receipt_chain_verified_after_promotion"]
            row.update(classification="native_machine",
                       note="Same-port restart and signed pending promotion verified; the full restart/old-authority/uncertain-operation matrix remains open.")
        elif item == "J11":
            source = "B04_HTTP"
            checks = sorted(names[source])
            row.update(classification="component_integration",
                       note="Real daemon HTTP tasks with synthetic capture: signature, export/trace-export scope, revocation, deletion and snapshot checks. Native capture and full real expiry remain separate; this row is not complete.")
        if source:
            require(set(checks) <= names[source], "missing required coverage")
            row["coverage"] = [{"leg_id": source, "checks": checks}]
            row["evidence_refs"] = [refs[source]]
        rows.append(row)
    cells = [{"platform": "openclaw", "os": "linux", "rows": rows}]
    for system in ("linux", "macos", "windows"):
        for platform in ("hermes", "openclaw", "workbuddy"):
            if (system, platform) == ("linux", "openclaw"):
                continue
            rows = []
            for item, needed in baseline.REQUIREMENTS.items():
                row = {"item": item, "status": "unverified", "classification": "static_check",
                       "coverage": [], "evidence_refs": [], "required_evidence": needed,
                       "note": "No same-candidate native leg in this review; historical results are retained separately."}
                if system != "linux" or platform == "workbuddy":
                    row.update(status="blocked", reason="environment_unavailable" if system != "linux" else "upstream_runtime_unconfirmed")
                    row.pop("required_evidence")
                rows.append(row)
            cells.append({"platform": platform, "os": system, "rows": rows})
    return {"schema_version": "personal-acceptance-baseline/v2", "batch": "closure-b10-review-20260916",
            "recorded_at": datetime.now(UTC).isoformat(), "legs": legs, "cells": cells,
            "evidence_sha256": hashes,
            "notes": ["No complete_acceptance rows; validation checks integrity and declared coverage only.",
                      "B01 test-release old/new binaries are deliberately not mixed into this candidate matrix.",
                      "Leg timestamps are report completion times, not measured execution durations.",
                      "B04 is component integration, B05 is real OpenClaw with a deterministic model.",
                      "N09 remains partial; T01-T06 are not unlocked; sunbo/Luke responsibilities are unchanged."]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--b04-ref", required=True)
    p.add_argument("--b05-ref", required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    result = build(args.b04_ref, args.b05_ref)
    os.umask(0o077)
    args.out.mkdir(parents=True, mode=0o700, exist_ok=False)
    path = args.out / "matrix.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    (args.out / "SHA256SUMS").write_text(sha256(path) + "  matrix.json\n")
    print(json.dumps({"cells": len(result["cells"]), "rows": sum(len(c["rows"]) for c in result["cells"]),
                      "complete_acceptance": 0}))


if __name__ == "__main__":
    main()
