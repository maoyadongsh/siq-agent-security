#!/usr/bin/env python3
"""Record the existing native decision component baseline, never sandbox/E2E proof."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "apps/agentshield"


def main() -> None:
    started = datetime.now(UTC)
    out = ROOT / "docs/evidence/personal-experience" / (
        "openshell-native-component-" + started.strftime("%Y%m%d-%H%M%S")
    )
    build = ["go", "test", "-trimpath", "-c", "./internal/receipt", "-o"]
    invocation = ["-test.run=^TestRuntimeStageBaseline$", "-test.v", "-test.count=1"]
    # Bind all Go module sources and local fixtures, including dirty/untracked
    # Go files. No file contents, machine paths or credentials enter the report.
    paths = sorted(p for p in MODULE.rglob("*") if p.is_file() and (
        p.suffix in {".go", ".json", ".yaml", ".yml"} or p.name in {"go.mod", "go.sum"}
    ))
    sources = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    with tempfile.TemporaryDirectory(prefix="siq-native-perf-") as td:
        binary = Path(td) / "receipt.test"
        subprocess.run([*build, str(binary)], cwd=MODULE, check=True, timeout=120, capture_output=True)
        binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
        proc = subprocess.run([str(binary), *invocation], cwd=MODULE / "internal/receipt", check=True,
                              timeout=60, capture_output=True, text=True,
                              env={**os.environ, "SIQ_STAGE_BASELINE": "1"})
    marker = "SIQ_STAGE_SAMPLES="
    lines = [line.split(marker, 1)[1] for line in proc.stdout.splitlines() if marker in line]
    if len(lines) != 1:
        raise SystemExit("baseline did not produce exactly one sample block")
    samples = json.loads(lines[0])
    summary = {}
    for stage, values in samples.items():
        if len(values) != 100 or any(not math.isfinite(v) or v < 0 for v in values):
            raise SystemExit("invalid baseline samples")
        ordered = sorted(values)
        summary[stage] = {"n": len(values), **{
            f"p{q}_ms": ordered[math.ceil(q / 100 * len(values)) - 1] for q in (50, 95, 99)
        }}
    if "decision_total" not in summary:
        raise SystemExit("decision total missing")
    report = {
        "format": "openshell-native-component-observation/v1",
        "started_at": started.isoformat(), "finished_at": datetime.now(UTC).isoformat(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_state": "uncommitted_worktree", "source_hashes": sources,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "test_binary_sha256": binary_sha,
        "environment": {"os": platform.system(), "arch": platform.machine(), "cpu_count": os.cpu_count()},
        "commands": [[*build, "<temporary-test-binary>"], ["<temporary-test-binary>", *invocation]],
        "environment_override": {"SIQ_STAGE_BASELINE": "1"}, "exit_code": proc.returncode,
        "warmup": 5, "samples_ms": samples, "summary": summary, "thresholds": None,
        "scope": "existing receipt.Decide component fixture with real local crypto/state; no host or sandbox",
        "not_measured": ["B1-B0", "B3-B2", "host_e2e", "backend_process_count", "cold_start",
                         "CPU", "RSS", "disk_write_bytes", "network_requests", "false_rejection_rate"],
        "notes": ["Not complete O00/O04 acceptance. No latency SLA or release-support claim.",
                  "This test repeats a fixed synthetic request; it is not the full SEC/approval lifecycle."],
    }
    out.mkdir(parents=True, exist_ok=False)
    raw = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    (out / "report.json").write_bytes(raw)
    (out / "SHA256SUMS").write_text(hashlib.sha256(raw).hexdigest() + "  report.json\n")
    print(json.dumps({"path": str(out.relative_to(ROOT)), "decision_total": summary["decision_total"]}))


if __name__ == "__main__":
    main()
