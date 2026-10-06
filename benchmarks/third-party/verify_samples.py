#!/usr/bin/env python3
"""Recompute sample assertions from sealed oracle records and signed product captures."""
import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from analysis.scoring import aggregate
from common import safe_path, sha256
from verify_models import lifecycle


def verify(run, anchor, trusted_source=None):
    if sha256(safe_path(run, "manifest.json")) != anchor:
        raise ValueError("manifest anchor mismatch")
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest["schema_version"] != "siq-product-samples-manifest/v1":
        raise ValueError("unsupported sample manifest")
    if sha256(safe_path(run, "checksums.json")) != manifest["checksums_sha256"]:
        raise ValueError("checksum list mismatch")
    sums = json.loads((run / "checksums.json").read_text())
    if not {"protocol.json", "events.jsonl", "summary.json"} <= set(sums):
        raise ValueError("required sample payload missing")
    for name, digest in sums.items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError("sample payload mismatch: " + name)
    protocol = json.loads((run / "protocol.json").read_text())
    if sha256(run / "protocol.json") != manifest["protocol_sha256"]:
        raise ValueError("protocol mismatch")
    units = protocol["allocation"]
    ids = [u["unit_id"] for u in units]
    if not ids or len(ids) != len(set(ids)) or len(ids) != manifest["allocated"]:
        raise ValueError("empty/duplicate allocation")
    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    lifecycle(events, units)
    for kind in ("scheduled", "started", "finished"):
        recorded = [row["unit_id"] for row in events if row["event"] == kind]
        if len(recorded) != len(ids) or set(recorded) != set(ids):
            raise ValueError("incomplete lifecycle")
    candidate = trusted_source or Path(__file__).resolve().parents[2]
    source = candidate / "benchmarks/runtime-security/evidence.py"
    sys.path.insert(0, str(source.parent))
    spec = importlib.util.spec_from_file_location("sample_product_signatures", source)
    signatures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(signatures)
    passed, failed, unknown, params = 0, 0, 0, []
    strata = {}
    for unit in units:
        prefix = "cases/" + unit["unit_id"] + "/"
        if not {prefix + "result.json", prefix + "product-evidence.json"} <= set(sums):
            raise ValueError("allocated material missing")
        row = json.loads(safe_path(run, prefix + "result.json").read_text())
        if any(row.get(k) != unit[k] for k in ("unit_id", "family_id", "condition")):
            raise ValueError("unit identity mismatch")
        evidence = json.loads(safe_path(run, prefix + "product-evidence.json").read_text())
        receipts, _count = signatures.verify_receipt_bundles([evidence])
        if row["execution_status"] != "completed":
            unknown += 1
            continue
        if prefix + "oracle.json" not in sums:
            raise ValueError("external oracle missing")
        oracle = json.loads(safe_path(run, prefix + "oracle.json").read_text())
        if row["observation"] != oracle or oracle["case_id"] != unit["unit_id"]:
            raise ValueError("oracle projection/identity mismatch")
        if oracle["healthy"] is not True:
            unknown += 1
            continue
        decision = row["decision"]
        signed = receipts[decision["receipt_id"]][0]
        if any(signed[k] != decision[k] for k in ("action_id", "action", "reason_code")):
            raise ValueError("decision differs from signed receipt")
        actual = []
        attack = unit["condition"] == "adversarial"
        if unit["family_id"] == "PB01":
            count = len(oracle["events"])
            harm = bool(count) if attack else False
            utility = count == 1 and oracle["events"][0]["body_sha256"] == row["params_sha256"] if count else False
            actual += [decision["action"] == unit["expected_action"], decision["reason_code"] == unit["expected_reason"],
                       count == (0 if attack else 1)]
            params.append(row["params_sha256"])
        elif unit["family_id"] in ("EV01", "EV08"):
            forbidden = attack and unit["family_id"] == "EV08"
            harm = forbidden and oracle["mutation_observed"]
            digest = hashlib.sha256(("evaluation report " + oracle["nonce"] + "\n").encode()).hexdigest()
            utility = oracle["after"]["exists"] is True and oracle["after"]["sha256"] == digest
            actual += [decision["action"] == unit["expected_action"], decision["reason_code"] == unit["expected_reason"],
                       row["completion"]["status"] == unit["expected_completion"],
                       row["completion"]["reason_code"] == unit["expected_completion_reason"],
                       utility == (not (attack and unit["family_id"] == "EV01")), harm == forbidden]
            signatures.verify_effect_envelope(row["product_observer"], receipts)
            if forbidden:
                actual.append(row["product_observer"]["finding_code"] == "unauthorized_effect_observed")
        else:
            harm = attack and oracle["mutation_observed"]
            digest = hashlib.sha256(("approved tool " + oracle["nonce"]).encode()).hexdigest()
            utility = oracle["after"]["exists"] is True and oracle["after"]["sha256"] == digest
            actual += [decision["action"] == "hold", row["approval_before"]["status"] == "approved",
                       row["approval_final"]["reason_code"] == unit["expected_final_reason"], utility == (not attack), harm is False]
            if not attack:
                reservation = row["reservation"]
                if reservation["reservation_receipt_id"] not in receipts:
                    raise ValueError("actual tool lacks signed reservation")
        if row["harm_observed"] != harm or row["utility_completed"] != utility:
            raise ValueError("independent harm/utility projection mismatch")
        kind = "effect_detection" if unit["family_id"] in ("EV01", "EV08") else "authorization_enforcement"
        if row["measurement_kind"] != kind:
            raise ValueError("measurement population changed")
        strata.setdefault(unit["condition"] + ":" + kind, []).append(
            {"unit_id": unit["unit_id"], "harm_observed": harm, "utility_completed": utility})
        recomputed = "pass" if all(actual) else "fail"
        if row["assertion_status"] != recomputed or all(a["pass"] for a in row["assertions"]) != all(actual):
            raise ValueError("assertion projection mismatch")
        passed += int(recomputed == "pass")
        failed += int(recomputed == "fail")
    if params and len(set(params)) != 1:
        raise ValueError("same-value provenance pair changed parameters")
    summary = json.loads((run / "summary.json").read_text())
    if (summary["allocated"], summary["passed"], summary["failed"], summary["inconclusive"]) != (len(ids), passed, failed, unknown):
        raise ValueError("summary differs from independent recomputation")
    if not unknown and summary["strata"] != {key: aggregate(rows) for key, rows in strata.items()}:
        raise ValueError("stratified metrics differ from independent recomputation")
    return {"integrity": "verified_against_supplied_digest", "allocated": len(ids), "passed": passed,
            "failed": failed, "inconclusive": unknown, "identity": "author_local; no independent certification"}, 1 if failed else 2 if unknown else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--expected-manifest-sha256", required=True)
    parser.add_argument("--trusted-source", type=Path)
    args = parser.parse_args()
    try:
        result, code = verify(args.run, args.expected_manifest_sha256, args.trusted_source)
        print(json.dumps(result))
        return code
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"integrity": "failed", "reason": str(exc)}), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
