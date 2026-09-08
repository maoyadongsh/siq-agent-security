#!/usr/bin/env python3
"""Combine verified Agent timings and existing measured SIQ component samples."""

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "benchmarks/hackathon"))

from verify import verify


def percentiles(values):
    if any(type(value) not in (float, int) or not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("invalid measured duration")
    ordered = sorted(values)
    return {"samples": len(values), **{f"p{p}_ms": ordered[math.ceil(len(ordered) * p / 100) - 1] if ordered else None
                                     for p in (50, 95, 99)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-report", type=Path, required=True)
    parser.add_argument("--stage-report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    model = json.loads(args.model_report.read_bytes())
    verified = verify(model)
    if model["cohort"] != "model-utility" or model["coverage"] != "full":
        raise ValueError("requires a full actual-model utility cohort")
    stages = json.loads(args.stage_report.read_bytes())
    if stages["schema_version"] != "runtime-stage-performance/v1" or stages["coverage"] != "component_microbenchmark":
        raise ValueError("requires existing component performance output")
    recomputed = {name: percentiles(values) for name, values in stages["samples_ms"].items()}
    if recomputed != stages["percentiles"]:
        raise ValueError("component percentiles differ from samples")
    if not {"decision_total", "provenance_resolution", "effect_evidence_processing"} <= set(recomputed):
        raise ValueError("required measured stages missing")
    calls = [call for case in model["cases"] for call in case["result"]["model_calls"]]
    report = {"schema_version": "hackathon-performance/v1", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {"model": {"path": str(args.model_report), "sha256": hashlib.sha256(args.model_report.read_bytes()).hexdigest()},
                   "stages": {"path": str(args.stage_report), "sha256": hashlib.sha256(args.stage_report.read_bytes()).hexdigest()}},
        "providers": sorted({case["provider"] for case in model["cases"]}),
        "models": sorted({case["model"] for case in model["cases"]}),
        "verified_receipts": verified["verified_receipts"], "verified_effect_envelopes": verified["verified_effect_envelopes"],
        "agent_measurements": {
            "model_attempt": percentiles([call["elapsed_ms"] for call in calls]),
            "model_planning": percentiles([call["elapsed_ms"] for call in calls if call["operation"] == "plan"]),
            "complete_task_attempt": percentiles([case["e2e_ms"] for case in model["cases"]]),
            "completed_task_only": percentiles([case["e2e_ms"] for case in model["cases"] if case["result"]["task"]["status"] == "verified"])},
        "component_measurements": recomputed,
        "failures": {"model_attempts": sum(call["status"] == "failed" for call in calls),
                     "tasks": sum(case["result"]["task"]["status"] != "verified" for case in model["cases"])},
        "limitations": [
            "Different recorded code snapshots and populations; do not add component and Agent percentiles.",
            "Model timings include transport, generation and strict validation, not isolated GPU kernel time.",
            "All task attempts include any failed attempts; completed-only figures exclude failures explicitly.",
            "Component tests use 100 sequential warm samples and actual SIQ signing/state; exclude model, HTTP and tool execution.",
            "Effect component measurement is SubmitFile, not file capture or external delivery latency.",
            "Five model tasks are a descriptive local sample, not an SLA or saturation/load benchmark.",
            "StepFun is deferred by the operator; measurements identify actual ornith and do not substitute labels."]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"report": str(args.out), "providers": report["providers"], "failures": report["failures"]}))


if __name__ == "__main__":
    main()
