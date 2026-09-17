#!/usr/bin/env python3
"""Frozen O04 incremental comparison using a separate git archive, never reset.

Native SIQ loopback HTTP with fixture skills, signed local state and receipts.
This is not OpenShell integration B2/B3, host-agent e2e, or a pre-O01 B0.
No production source is copied into the baseline: only the identical test harness.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "6e34f3ad82033b0b5ffe49cd82bc042c84414429"
HARNESS = Path("apps/agentshield/internal/server/openshell_native_http_test.go")
ORDER = [["before", "after"], ["after", "before"], ["before", "after"]]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(values):
    if not values or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("invalid samples")
    ordered = sorted(values)
    return {"n": len(values), "max_ms": ordered[-1],
            **{f"p{p}_ms": ordered[math.ceil(p / 100 * len(values)) - 1] for p in (50, 95, 99)}}


def source_hashes():
    module = ROOT / "apps/agentshield"
    return {str(p.relative_to(ROOT)): digest(p)
            for p in sorted(module.rglob("*"))
            if p.is_file() and (p.suffix == ".go" or p.name in {"go.mod", "go.sum"})}


def resources(row):
    before, after = row.pop("resources_before"), row.pop("resources_after")
    def metric(snapshot, source, key):
        for line in snapshot.get(source, "").splitlines():
            if line.startswith(key + ":"):
                return int(line.split()[1])
        return None
    def cpu(snapshot):
        raw = snapshot.get("stat")
        if raw is None:
            return None
        fields = raw.rsplit(")", 1)[1].split()
        return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")
    rss = metric(after, "status", "VmRSS")
    out = {"rss_after_bytes": None if rss is None else rss * 1024,
           "rss_source": "os_vm_rss" if rss is not None else "unavailable",
           "window": "both decision phases + warmup + grant revoke; excludes setup and receipt verification"}
    start, end = cpu(before), cpu(after)
    out["cpu_seconds"] = None if start is None or end is None else end - start
    for field in ("write_bytes", "wchar", "syscw", "cancelled_write_bytes"):
        start, end = metric(before, "io", field), metric(after, "io", field)
        out[field + "_delta"] = None if start is None or end is None else end - start
    row["resources"] = out
    return row


def main():
    out = ROOT / "docs/evidence/personal-experience" / (
        "openshell-o04-http-review-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S"))
    out.mkdir(parents=True, exist_ok=False)
    sources = source_hashes()
    protocol = {
        "format": "openshell-o04-native-http-comparison/v1",
        "baseline_commit": BASE, "baseline_scope": "before O04, after O01-O03; not original B0",
        "candidate_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "candidate_state": "uncommitted_worktree", "source_hashes": sources,
        "runner_sha256": digest(Path(__file__)), "harness_sha256": digest(ROOT / HARNESS),
        "round_order": ORDER, "warmup_per_phase": 5, "samples_per_phase_per_round": 200,
        "percentile": "nearest rank", "sample_exclusion": "none; retain failed attempt separately",
        "concurrency": 1, "relative_p95_budget_increase": 0.10,
        "scope": "service_http_fixture_native_no_agent_effects",
        "environment": {"os": platform.system(), "arch": platform.machine(),
                        "go": subprocess.check_output(["go", "version"], text=True).strip(),
                        "cpu_count": os.cpu_count()},
        "not_measured": [
            "pre-O01 B0 versus complete lightening plan B1",
            "real OpenShell integration B2/B3", "installed daemon / host agent effects",
            "long-running real-workload false rejection rate",
            "OS process-tree count (runner call counts are instrumentation only)",
            "network bytes or remote requests (only local HTTP counts measured)",
        ],
    }
    # Freeze protocol on disk before any timed operation.
    (out / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n")
    results = {"before": [], "after": []}
    try:
        with tempfile.TemporaryDirectory(prefix="siq-o04-compare-") as temporary:
            directory = Path(temporary)
            baseline = directory / "source"
            baseline.mkdir()
            archive = subprocess.check_output(["git", "archive", "--format=tar", BASE], cwd=ROOT)
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(baseline, filter="data")
            shutil.copy2(ROOT / HARNESS, baseline / HARNESS)
            trees = {"before": baseline, "after": ROOT}
            binaries = {}
            for name, tree in trees.items():
                binary = directory / (name + ".test")
                subprocess.run(["go", "test", "-trimpath", "-c", "./internal/server", "-o", str(binary)],
                               cwd=tree / "apps/agentshield", check=True, capture_output=True, timeout=180)
                binaries[name] = binary
            binary_hashes = {name: digest(path) for name, path in binaries.items()}
            for round_number, order in enumerate(ORDER, 1):
                for name in order:
                    proc = subprocess.run(
                        [str(binaries[name]), "-test.run=^TestO04NativeHTTP$", "-test.v", "-test.count=1"],
                        cwd=trees[name] / "apps/agentshield/internal/server",
                        env={**os.environ, "SIQ_O04_HTTP_PERF": "1"}, capture_output=True, text=True, timeout=180)
                    if proc.returncode:
                        # Test failures log only the harness's fixed diagnostic categories.
                        (out / "failed-attempt.txt").write_text(proc.stdout + proc.stderr)
                        raise RuntimeError(f"{name} round {round_number} failed")
                    marker = "SIQ_O04_HTTP_RESULT="
                    blocks = [line.split(marker, 1)[1] for line in proc.stdout.splitlines() if marker in line]
                    if len(blocks) != 1:
                        raise RuntimeError("missing result")
                    row = resources(json.loads(blocks[0]))
                    for values in row["samples_ms"].values():
                        if len(values) != 200:
                            raise RuntimeError("wrong sample count")
                        summarize(values)
                    row["round"] = round_number
                    results[name].append(row)
                    (out / "samples.json").write_text(json.dumps(results, indent=2) + "\n")
            if source_hashes() != sources:
                raise RuntimeError("candidate source changed during measurement")
        summaries = {name: {key: summarize([v for row in rows for v in row["samples_ms"][key]])
                            for key in ("allow_ms", "revoked_deny_ms")} for name, rows in results.items()}
        comparison = {}
        for key in ("allow_ms", "revoked_deny_ms"):
            ratio = summaries["after"][key]["p95_ms"] / summaries["before"][key]["p95_ms"] - 1
            comparison[key] = {"p95_relative_increase": ratio, "within_10_percent": ratio <= 0.10}
        report = {"protocol_sha256": digest(out / "protocol.json"), "binary_hashes": binary_hashes,
                  "summary": summaries, "comparison": comparison, "source_unchanged": True,
                  "functional_journey": "auth negatives; pending deny; admit/challenge/approve/deploy; allow; revoke; deny; receipt chain verified",
                  "finished_at": datetime.now(UTC).isoformat()}
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    except Exception as exc:
        (out / "failure.json").write_text(json.dumps({"status": "failed", "type": type(exc).__name__}) + "\n")
        raise
    finally:
        files = sorted(p for p in out.iterdir() if p.name != "SHA256SUMS")
        (out / "SHA256SUMS").write_text("".join(f"{digest(p)}  {p.name}\n" for p in files))
    print(json.dumps({"path": str(out.relative_to(ROOT)), "comparison": comparison}))


if __name__ == "__main__":
    main()
