#!/usr/bin/env python3
"""Measure Go stages plus complete Decide calls; no HTTP/model latency substitution."""
import argparse
import hashlib
import json
import math
import os
import platform
import subprocess
from pathlib import Path

from metrics import TIMINGS

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    env = {key: value for key, value in os.environ.items()
           if key in {"PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SYSTEMROOT", "GOTOOLCHAIN"}}
    env["SIQ_STAGE_BASELINE"] = "1"
    command = ["go", "test", "-json", "-count=1", "-run", "^(TestRuntimeStageBaseline|TestEffectStageBaseline)$",
               "./internal/receipt", "./internal/effectevidence"]
    result = subprocess.run(command, cwd=ROOT / "apps/agentshield", env=env,
                            capture_output=True, text=True, timeout=180, check=True)
    samples = {}
    streams = {}
    # go test -json can split a single long log line across output events.
    for line in result.stdout.splitlines():
        event = json.loads(line)
        identity = (event.get("Package"), event.get("Test"))
        streams[identity] = streams.get(identity, "") + event.get("Output", "")
    for stream in streams.values():
        for output in stream.splitlines():
            if "SIQ_STAGE_SAMPLES=" not in output:
                continue
            value = json.loads(output.split("SIQ_STAGE_SAMPLES=", 1)[1])
            if set(value) & set(samples):
                raise ValueError("duplicate stage output")
            samples.update(value)
    if set(samples) != set(TIMINGS) | {"decision_total"}:
        raise ValueError("missing actual stage measurements")
    percentiles = {}
    for stage, values in samples.items():
        if len(values) != 100 or any(type(v) not in (float, int) or not math.isfinite(v) or v < 0 for v in values):
            raise ValueError("invalid stage measurements")
        ordered = sorted(values)
        percentiles[stage] = {"samples": len(values), **{
            f"p{p}_ms": ordered[math.ceil(len(ordered) * p / 100) - 1] for p in (50, 95, 99)}}
    report = {"schema_version": "runtime-stage-performance/v1", "coverage": "component_microbenchmark",
              "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "go_version": subprocess.check_output(["go", "version"], env=env, text=True).strip(),
              "platform": platform.platform(), "cpu_count": os.cpu_count(), "warmup_per_fixture": 5,
              "command": command, "samples_ms": samples, "percentiles": percentiles,
              "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "source_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
                  "apps/agentshield/internal/receipt/engine.go",
                  "apps/agentshield/internal/receipt/performance_test.go",
                  "apps/agentshield/internal/effectevidence/store.go",
                  "apps/agentshield/internal/effectevidence/performance_test.go")},
              "limitations": ["100 sequential warm samples, not production SLA or load saturation",
                              "decision fixture uses real signed V3, context, provenance and deployed test Grant",
                              "decision_total includes the complete Engine.Decide call and timing callbacks; excludes HTTP and tool execution",
                              "stage percentiles overlap decision_total and must not be added to it",
                              "effect fixture separately times SubmitFile with a synthetic authorized Action",
                              "effect timing excludes file capture and tool execution; includes signing and publication",
                              "no race instrumentation; performance results are not race-test evidence"]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(percentiles, indent=2))


if __name__ == "__main__":
    main()
