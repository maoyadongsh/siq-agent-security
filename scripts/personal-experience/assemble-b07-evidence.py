#!/usr/bin/env python3
"""Validate immutable B0/B1 runs and derive a component-only comparison.

No sample deletion, budget tuning or mutation of input evidence is permitted.
C is reported as changed-workload observation (version detection differs), E
has no B0 counterpart. Neither is promoted to equivalent-workload acceptance.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("o04_protocol", Path(__file__).with_name("openshell-o04-perf-protocol.py"))
protocol = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(protocol)
FILES = {"report.json", "samples.json", "protocol.md", "source-hashes.json"}


def require(ok, category):
    if not ok:
        raise ValueError(category)


def read_run(root, scenarios):
    require(not any((root / name).exists() for name in ("INVALID.md", "NOT-OFFICIAL.md")),
            "disqualified_evidence")
    manifest = {}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split("  ", 1)
        require(name in FILES and name not in manifest, "unexpected_or_duplicate_manifest_path")
        require(not (root / name).is_symlink(), "symlink_evidence")
        require(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, "evidence_hash_mismatch")
        manifest[name] = digest
    require(set(manifest) == FILES, "incomplete_manifest")
    report = json.loads((root / "report.json").read_text())
    samples = json.loads((root / "samples.json").read_text())["rounds_raw"]
    require(report["source_hashes"] == json.loads((root / "source-hashes.json").read_text()), "source_manifest_mismatch")
    require(set(samples) == set(scenarios), "scenario_set_mismatch")
    p = report["protocol"]
    require(p["frozen_before_measurement"] is True and p["rounds"] == 3
            and p["round_orders"] == protocol.ROUND_ORDERS, "protocol_changed")
    require(p["tail_scenarios"] == (["C", "D"] if set(scenarios) == set("ABCD") else ["C", "D", "E"]), "tail_order_changed")
    require(p["percentile_algorithm"] == protocol.PERCENTILE_ALGORITHM
            and p["exclusion_rule"] == protocol.EXCLUSION_RULE, "sampling_rules_changed")
    summaries = {}
    for scenario in scenarios:
        require(p["samples_per_round"][scenario] == protocol.SAMPLES[scenario]
                and p["warmup"][scenario] == protocol.WARMUP[scenario], "sample_or_warmup_changed")
        require(report["budgets"][scenario] == protocol.BUDGETS[scenario], "budget_changed")
        require(report["evidence_labels"][scenario] == protocol.EVIDENCE_LABEL[scenario], "evidence_level_changed")
        entries = samples[scenario]
        count = 2 if scenario in "AB" else 1
        require(Counter(e["round"] for e in entries) == Counter({1: count, 2: count, 3: count}), "incomplete_rounds")
        summaries[scenario] = {}
        for e in entries:
            require(e["scenario"] == scenario and set(e["warmup"]) <= set(protocol.WARMUP[scenario])
                    and all(e["warmup"].get(key, 0) == count for key, count in protocol.WARMUP[scenario].items()),
                    "entry_metadata_mismatch")
            protocol.validate(scenario, e)
        for metric in protocol.SAMPLES[scenario]:
            values = [v for e in entries for v in e["samples_ms"][metric]]
            require(all(isinstance(v, (int, float)) and not isinstance(v, bool)
                        and math.isfinite(v) and v >= 0 for v in values), "invalid_sample")
            summary = protocol.summarize(values)
            require(summary == report["pooled_summary"][scenario][metric], "summary_not_derived_from_samples")
            summaries[scenario][metric] = summary
    return report, summaries, manifest


def compare(b0, b1):
    r0, s0, h0 = read_run(b0, "ABCD")
    r1, s1, h1 = read_run(b1, "ABCDE")
    require(datetime.fromisoformat(r0["finished_at"]) <= datetime.fromisoformat(r1["started_at"]), "overlapping_runs")
    require(r0["environment"] == r1["environment"], "environment_mismatch")
    rows = []
    for scenario, metrics in s1.items():
        for metric, current in metrics.items():
            previous = s0.get(scenario, {}).get(metric)
            comparable = scenario in "ABD" and previous is not None
            delta = ((current["p95_ms"] / previous["p95_ms"] - 1) * 100
                     if previous and previous["p95_ms"] > 0 else None)
            budget = protocol.BUDGETS[scenario][metric]
            absolute = all(current[key + "_ms"] <= value for key, value in budget.items())
            rows.append({"scenario": scenario, "metric": metric, "b0": previous, "b1": current,
                         "b1_absolute_budget_ms": budget, "b1_absolute_passed": absolute,
                         "relative_p95_percent": delta,
                         "relative_budget_percent": 10 if comparable else None,
                         "relative_passed": delta <= 10 if comparable and delta is not None else None,
                         "comparability": "same_external_component_operation" if comparable else
                             ("changed_probe_workload" if scenario == "C" else "no_b0_implementation")})
    return {"schema_version": "closure-b07-component-comparison/v1", "status": "partial",
            "scope": "component_only; B2/B3 and O05 remain blocked without real backend",
            "input_heads": {"b0": r0["head"], "b1": r1["head"]},
            "input_manifests": {"b0": h0, "b1": h1}, "rows": rows,
            "comparable_relative_passed": all(row["relative_passed"] is True for row in rows
                                              if row["comparability"] == "same_external_component_operation"),
            "b1_absolute_passed": all(row["b1_absolute_passed"] for row in rows),
            "corrections": [
                "B0 D inherited notes mention bounded pipe drainage; b303c6f has no such bound. Raw notes are preserved, this correction supersedes them.",
                "B0 C does not detect the CLI version; B1 cold probe does. C numbers are observations with changed work, not equivalent-workload acceptance.",
                "D total fixture wait is 3 * (3 warmups + 60 samples) * 30 seconds = 94.5 minutes, excluding overhead.",
                "Hash validity attests file integrity, not native/backend verification or absence of background host load.",
            ], "not_measured": ["B2 service", "B3 host end-to-end", "B0 E", "cross-OS real hardware",
                                  "CPU", "RSS per scenario", "network and disk counts", "false rejection rate"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--b0", type=Path, required=True)
    parser.add_argument("--b1", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.b0, args.b1)
    args.out.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(args.out, 0o700)
    lines = ["# B07 组件对照复核", "", "仅组件级；B07 总体保持 partial。", "",
             "| 场景 | 指标 | B0 p95 ms | B1 p95 ms | 相对变化 % | 比较边界 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in result["rows"]:
        old = row["b0"]["p95_ms"] if row["b0"] else "未测量"
        lines.append(f"| {row['scenario']} | {row['metric']} | {old} | {row['b1']['p95_ms']} | {row['relative_p95_percent']} | {row['comparability']} |")
    lines += ["", "## 必须保留的边界", "", *["- " + text for text in result["corrections"]]]
    files = {"report.json": json.dumps(result, indent=2) + "\n", "report.md": "\n".join(lines) + "\n"}
    for name, text in files.items():
        with (args.out / name).open("x") as f:
            os.chmod(f.name, 0o600)
            f.write(text)
    sums = "".join(hashlib.sha256((args.out / name).read_bytes()).hexdigest() + "  " + name + "\n" for name in files)
    with (args.out / "SHA256SUMS").open("x") as f:
        os.chmod(f.name, 0o600)
        f.write(sums)
    print(json.dumps({"status": "partial", "integrity_valid": True,
                      "relative_passed": result["comparable_relative_passed"],
                      "absolute_passed": result["b1_absolute_passed"]}))


if __name__ == "__main__":
    main()
