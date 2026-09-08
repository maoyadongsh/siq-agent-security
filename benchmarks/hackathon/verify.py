#!/usr/bin/env python3
"""Verify archived SIQ evidence and recompute application benchmark metrics."""

import argparse
import hashlib
import json
from pathlib import Path

from run import CORPUS, EVIDENCE, expectation_violations, load_corpus, summarize


def verify(report):
    corpus = {c["id"]: c for c in load_corpus()}
    if report["schema_version"] != "hackathon-benchmark/v1" or report["corpus_sha256"] != hashlib.sha256(CORPUS.read_bytes()).hexdigest():
        raise ValueError("benchmark corpus/version differs")
    if report["cohort"] not in ("controls", "model-utility") or report["coverage"] not in ("full", "partial"):
        raise ValueError("unknown cohort or coverage")
    eligible = {k for k, c in corpus.items() if report["cohort"] == "controls" or c["kind"] == "benign"}
    seen, receipt_count, effect_count = set(), 0, 0
    for item in report["cases"]:
        identity, result = item["case"]["id"], item["result"]
        if identity in seen or identity not in eligible or item["case"] != corpus[identity]:
            raise ValueError("duplicate, unknown or altered case")
        seen.add(identity)
        if item["expectation_violations"] != expectation_violations(item["case"], result, item["material"], item["checks"]):
            raise ValueError("expectation outcomes differ from actual task")
        if ((report["cohort"] == "controls" and item["provider"] != "fixture")
                or (report["cohort"] == "model-utility" and item["provider"] not in ("ornith", "stepfun"))):
            raise ValueError("provider differs from declared cohort")
        receipts, count = EVIDENCE.verify_receipt_bundles([item["public_evidence"]])
        effects, action_ids = {}, set()
        for action in result.get("preparation", {}).get("actions", []) + result["task"]["actions"]:
            signed, _ = receipts[action["receipt_id"]]
            if (signed["record_type"] != "decision" or signed["action_id"] != action["action_id"]
                    or signed["action"] != action["decision"] or signed["reason_code"] != action["reason_code"]
                    or action["action_id"] in action_ids or type(action["d3_materialized"]) is not bool):
                raise ValueError("application action differs from signed decision")
            action_ids.add(action["action_id"])
            record = action["effect"]
            if record:
                EVIDENCE.verify_effect_envelope(record, receipts)
                effect = record["evidence"]
                if effect["action_id"] != action["action_id"] or effect["effect_evidence_id"] in effects:
                    raise ValueError("effect copied to a different action")
                effects[effect["effect_evidence_id"]] = record
        if item["verification"] != {"receipts": count, "effects": len(effects)}:
            raise ValueError("verification counts differ")
        task = result["task"]
        completion = task.get("completion")
        if task["status"] == "verified" and (not completion or completion["status"] != "verified"):
            raise ValueError("verified task lacks Completion")
        if completion:
            expected = {r["requirement_id"]: r for r in result["intent"]["effect_requirements"]}
            if ({r["requirement_id"] for r in completion["requirements"]} != set(expected)
                    or len(completion["requirements"]) != len(expected) or completion["task_id"] != task["task_id"]):
                raise ValueError("Completion requirements/task differ")
            for requirement in completion["requirements"]:
                if requirement["status"] != "verified":
                    continue
                refs = requirement["evidence_ids"]
                if not refs or any(ref not in effects for ref in refs):
                    raise ValueError("verified requirement lacks signed effect")
                target = expected[requirement["requirement_id"]]
                for ref in refs:
                    record, effect = effects[ref], effects[ref]["evidence"]
                    if (record["task_id"] != task["task_id"] or effect["result"] != "expected"
                            or effect["effect_type"] != target["effect_type"] or effect["resource_ref"] != target["resource_ref"]):
                        raise ValueError("verified requirement differs from signed effect")
            if completion["status"] == "verified" and (not completion["requirements"] or any(
                    r["status"] != "verified" for r in completion["requirements"])):
                raise ValueError("verified Completion has unfinished requirements")
        if item["case"]["mutation"] in ("wrong-task", "cross-session"):
            assertion = item["checks"]["replayed_assertion"]
            # Signed provenance is additional evidence, never model authority.
            key = next(iter(receipts.values()))[1]
            key.verify(bytes.fromhex(assertion["signature"]), EVIDENCE.canonical(
                {k: v for k, v in assertion.items() if k != "signature"}))
        receipt_count += count
        effect_count += len(effects)
    if not seen or (report["coverage"] == "full" and seen != eligible):
        raise ValueError("benchmark coverage incomplete")
    computed = summarize(report["cases"])
    # Early development captures predate the task-level approval projection.
    # Require every original metric and compare all supplied derived values;
    # always emit the complete current aggregation in this verification output.
    required = set(computed) - {"manual_approval_rate"}
    if not required <= set(report["summary"]) or any(computed.get(k) != v for k, v in report["summary"].items()):
        raise ValueError("reported metrics differ from observations")
    return {"verified_receipts": receipt_count, "verified_effect_envelopes": effect_count, "summary": computed,
            "scope": "SIQ signatures/action correlation and metric consistency; tool/model metadata is runner-reported"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    raw = args.report.read_bytes()
    result = {"report_sha256": hashlib.sha256(raw).hexdigest(), **verify(json.loads(raw))}
    output = json.dumps(result, indent=2) + "\n"
    if args.out:
        with args.out.open("x") as stream:
            stream.write(output)
    else:
        print(output, end="")


if __name__ == "__main__":
    main()
