#!/usr/bin/env python3
"""Verify model-smoke signatures, allocated tasks and usage from archived captures.

This recomputes recorded outcomes; it cannot retrospectively add an independent
effect oracle or attest to the identity of a remote model/server.
"""
import argparse
import importlib.util
import json
import sys
from itertools import pairwise
from pathlib import Path

from common import safe_path, sha256


def lifecycle(events, units):
    ids = [unit["unit_id"] for unit in units]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("empty or duplicate allocation")
    if [e["sequence"] for e in events] != list(range(1, len(events) + 1)):
        raise ValueError("event sequence gap/replay")
    if any(b["monotonic_ns"] < a["monotonic_ns"] for a, b in pairwise(events)):
        raise ValueError("event clock regressed")
    if len({e["run_id"] for e in events}) != 1:
        raise ValueError("events mix run identities")
    for kind in ("scheduled", "started", "finished"):
        selected = [e["unit_id"] for e in events if e["event"] == kind]
        if len(selected) != len(ids) or set(selected) != set(ids):
            raise ValueError("allocated lifecycle differs")
    for identity in ids:
        selected = [e["event"] for e in events if e.get("unit_id") == identity
                    and e["event"] in ("scheduled", "started", "finished")]
        if selected != ["scheduled", "started", "finished"]:
            raise ValueError("invalid lifecycle order")


def verify(run, anchor, trusted_source):
    if sha256(safe_path(run, "manifest.json")) != anchor:
        raise ValueError("manifest anchor mismatch")
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest["schema_version"] != "siq-model-smoke-manifest/v1":
        raise ValueError("unsupported model manifest")
    if sha256(safe_path(run, "checksums.json")) != manifest["checksums_sha256"]:
        raise ValueError("checksum list mismatch")
    sums = json.loads((run / "checksums.json").read_text())
    if not {"protocol.json", "summary.json", "events.jsonl"} <= set(sums):
        raise ValueError("required model payload missing")
    for name, digest in sums.items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError("model payload mismatch: " + name)
    if sha256(run / "protocol.json") != manifest["protocol_sha256"]:
        raise ValueError("protocol differs")
    protocol = json.loads((run / "protocol.json").read_text())
    units = protocol["allocation"]
    if manifest["allocated"] != len(units):
        raise ValueError("manifest allocation differs")
    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    lifecycle(events, units)
    expected_files = {"cases-private/" + unit["unit_id"] + ".json" for unit in units}
    if {p for p in sums if p.startswith("cases-private/")} != expected_files:
        raise ValueError("case files differ from allocation")
    # Import caller-selected trusted local code, never an evidence-supplied path.
    sys.path.insert(0, str(trusted_source / "benchmarks/hackathon"))
    spec = importlib.util.spec_from_file_location("trusted_application_verifier", trusted_source / "benchmarks/hackathon/verify.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    completed, unknown, receipts, effects, material_success = 0, 0, 0, 0, 0
    error_counts = {}
    for unit in units:
        row = json.loads(safe_path(run, "cases-private/" + unit["unit_id"] + ".json").read_text())
        if any(row.get(key) != value for key, value in unit.items()):
            raise ValueError("case identity differs")
        captured = row["legacy_capture"]
        outcome = None
        if captured is not None:
            if captured["case"]["id"] != unit["case_id"] or captured["model"] != protocol["model"]:
                raise ValueError("task/model identity differs")
            if captured["public_evidence"]["binary_sha256"] != protocol["binary_sha256"]:
                raise ValueError("candidate binary identity differs")
            report = {"schema_version": "hackathon-benchmark/v1", "corpus_sha256": sha256(verifier.CORPUS),
                      "cohort": "model-utility", "coverage": "partial", "cases": [captured],
                      "summary": verifier.summarize([captured])}
            checked = verifier.verify(report)
            receipts += checked["verified_receipts"]
            effects += checked["verified_effect_envelopes"]
            task = captured["result"]["task"]
            outcome = task["status"] == "verified"
            material = captured["material"]
            received = material["receiver_events"]
            observed = (material["report_exists"] is True and bool(material["report_sha256"])
                        and len(received) == 1 and received[0]["payload_digest"] == material["report_sha256"])
            material_success += int(observed)
            if outcome and (not observed or captured["expectation_violations"]):
                raise ValueError("completed task lacks matching recorded material")
            if row["expectation_violations"] != captured["expectation_violations"]:
                raise ValueError("violations projection differs")
            if task.get("error_code"):
                error = task["error_code"]
                error_counts[error] = error_counts.get(error, 0) + 1
        if row["utility_completed"] != outcome:
            raise ValueError("utility projection differs")
        completed += int(outcome is True)
        unknown += int(outcome is None)
    starts = [e for e in events if e["event"] == "model_call_started"]
    finishes = [e for e in events if e["event"] == "model_call_finished"]
    expected_calls = list(range(1, len(starts) + 1))
    if [e["call_id"] for e in starts] != expected_calls or [e["call_id"] for e in finishes] != expected_calls:
        raise ValueError("model call missing/replayed")
    reported, charged, unknown_usage = 0, 0, 0
    for started, ended in zip(starts, finishes):
        if started["unit_id"] != ended["unit_id"] or ended["sequence"] <= started["sequence"]:
            raise ValueError("call correlation differs")
        count = ended["diagnostic"].get("usage", {}).get("total_tokens")
        if type(count) is int and count >= 0:
            reported += count
            charged += count
        else:
            unknown_usage += 1
            charged += started["reserved_tokens"]
    budget = {"calls": len(starts), "charged_tokens": charged, "reported_tokens": reported,
              "unknown_usage_calls": unknown_usage}
    summary = json.loads((run / "summary.json").read_text())
    if any(summary[key] != value for key, value in {
            "allocated": len(units), "independent_task_blocks": len({u["case_id"] for u in units}),
            "completed_tasks": completed, "unknown_tasks": unknown, "budget": budget}.items()):
        raise ValueError("summary differs from captures")
    return {"integrity": "verified_against_supplied_digest", "allocated": len(units),
            "independent_task_blocks": summary["independent_task_blocks"], "completed_tasks": completed,
            "recorded_material_success": material_success, "unknown_tasks": unknown, "budget": budget,
            "error_counts": error_counts, "verified_receipts": receipts, "verified_effect_envelopes": effects,
            "scope": "recorded application material and signed evidence; no independent oracle added after execution",
            "identity": "author_run; requested model identity is runner-reported"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--trusted-source", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.run, args.expected_manifest_sha256, args.trusted_source)))
        return 0  # Integrity success is distinct from the task success count.
    except Exception as exc:  # noqa: BLE001 -- CLI verifier must fail closed on malformed evidence/signatures.
        print(json.dumps({"integrity": "failed", "error_type": type(exc).__name__, "reason": str(exc)}), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
