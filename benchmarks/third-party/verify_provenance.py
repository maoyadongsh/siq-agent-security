#!/usr/bin/env python3
"""Verify receiver observations, signed decisions and source-only ablation identity."""
import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from common import canonical, safe_path, sha256
from verify_models import lifecycle


def verify(run, anchor, candidate):
    if sha256(safe_path(run, "manifest.json")) != anchor:
        raise ValueError("manifest anchor differs")
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest["schema_version"] != "siq-provenance-trial-manifest/v1":
        raise ValueError("unsupported provenance manifest")
    if sha256(safe_path(run, "checksums.json")) != manifest["checksums_sha256"]:
        raise ValueError("checksums differ")
    sums = json.loads((run / "checksums.json").read_text())
    if not {"protocol.json", "summary.json", "events.jsonl"} <= set(sums):
        raise ValueError("required evidence missing")
    for name, digest in sums.items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError("payload changed: " + name)
    if sha256(run / "protocol.json") != manifest["protocol_sha256"]:
        raise ValueError("protocol changed")
    protocol = json.loads((run / "protocol.json").read_text())
    a, b = protocol["candidate_sources"], protocol["ablation_sources"]
    differences = {name for name in set(a) | set(b) if a.get(name) != b.get(name)}
    if differences != {"apps/agentshield/internal/provenance/matcher.go", "benchmarks/runtime-security/network_fixture.py",
                       "benchmarks/runtime-security/approval_fixture.py"}:
        raise ValueError("ablation differs outside registered predicate/legacy fixture repairs")
    # The two repaired Python fixtures are not part of either Go binary, and the
    # runtime trial uses the identical frozen Python fixture for every SIQ arm.
    source = candidate / "benchmarks/runtime-security/evidence.py"
    if sha256(source) != a["benchmarks/runtime-security/evidence.py"]:
        raise ValueError("signature verifier source changed")
    spec = importlib.util.spec_from_file_location("provenance_trial_signatures", source)
    signatures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(signatures)
    units = protocol["allocation"]
    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    lifecycle(events, units)
    if manifest["allocated"] != len(units):
        raise ValueError("allocation differs")
    params_digest = hashlib.sha256(canonical(protocol["fixed_params"])).hexdigest()
    counts, effects, receipts_count = {"pass": 0, "fail": 0, "inconclusive": 0}, {}, 0
    for unit in units:
        prefix = "cases/" + unit["unit_id"] + "/"
        if not {prefix + "result.json", prefix + "oracle.json"} <= set(sums):
            raise ValueError("allocated material missing")
        row = json.loads(safe_path(run, prefix + "result.json").read_text())
        observation = json.loads(safe_path(run, prefix + "oracle.json").read_text())
        if any(row[key] != value for key, value in unit.items()) or observation["case_id"] != unit["unit_id"]:
            raise ValueError("unit identity differs")
        if row["params_sha256"] != params_digest:
            raise ValueError("same-value parameters differ")
        count = len(observation["events"])
        delivered = count == 1 and observation["events"][0]["body_sha256"] == params_digest
        healthy = observation["healthy"]
        harm = True if unit["condition"] == "adversarial" and count else False if healthy else None
        utility = delivered if healthy else None
        if (row["harm_observed"], row["utility_completed"]) != (harm, utility):
            raise ValueError("receiver outcome projection differs")
        actual = [count == unit["expected_deliveries"]]
        if unit["group"] != "B0":
            if not {prefix + "product-evidence.json", prefix + "request.json", prefix + "authority.json"} <= set(sums):
                raise ValueError("SIQ binding material missing")
            evidence = json.loads(safe_path(run, prefix + "product-evidence.json").read_text())
            if evidence["binary_sha256"] != protocol["binaries"][unit["group"]]["sha256"]:
                raise ValueError("wrong binary for arm")
            receipts, verified = signatures.verify_receipt_bundles([evidence])
            receipts_count += verified
            decision = row["decision"]
            signed, key = receipts[decision["receipt_id"]]
            if any(decision[name] != signed[name] for name in ("action", "reason_code", "action_id")):
                raise ValueError("decision is not the signed decision")
            request = json.loads(safe_path(run, prefix + "request.json").read_text())
            if request["params"] != protocol["fixed_params"]:
                raise ValueError("dispatch arguments differ")
            authority = json.loads(safe_path(run, prefix + "authority.json").read_text())
            assertion = authority["selected_assertion"]
            key.verify(bytes.fromhex(assertion["signature"]), signatures.canonical({k: v for k, v in assertion.items() if k != "signature"}))
            desired_source = "MCP" if unit["variant"] == "same-value" and unit["condition"] == "adversarial" else "USER"
            if assertion["source"]["type"] != desired_source:
                raise ValueError("source treatment differs from preregistration")
            if request["parameter_provenance"] != [{"parameter_path": "/recipient", "provenance_refs": [assertion["provenance_id"]]}]:
                raise ValueError("decision references another source")
            actual += [decision["action"] == unit["expected_action"], decision["reason_code"] == unit["expected_reason"]]
        expected_status = "fail" if not all(actual) else "inconclusive" if row["error_type"] or not healthy else "pass"
        if row["assertion_status"] != expected_status or all(a["pass"] for a in row["assertions"]) != all(actual):
            raise ValueError("assertion projection differs")
        counts[expected_status] += 1
        if unit["variant"] == "same-value":
            effects[unit["unit_id"]] = utility
    summary = json.loads((run / "summary.json").read_text())
    expected = {"allocated": len(units), "passed": counts["pass"], "failed": counts["fail"], "inconclusive": counts["inconclusive"],
                "same_value_effects": effects, "all_params_equal": True}
    if any(summary[key] != value for key, value in expected.items()):
        raise ValueError("summary differs from receiver and signed capture")
    return {"integrity": "verified_against_supplied_digest", **expected, "verified_receipts": receipts_count,
            "scope": "controlled dispatch with one source/trust predicate ablated; author_run; no model ASR"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--trusted-candidate", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.run, args.expected_manifest_sha256, args.trusted_candidate)))
        return 0
    except Exception as exc:  # noqa: BLE001 -- invalid signatures and malformed payloads fail closed.
        print(json.dumps({"integrity": "failed", "error_type": type(exc).__name__, "reason": str(exc)}), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
