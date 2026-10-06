#!/usr/bin/env python3
"""Execute frozen evaluation operations with append-only attempt evidence."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from common import Events, clean_environment, run_command, sha256, utc_now, write_json

ROOT = Path(__file__).resolve().parents[2]
OPERATIONS = ["contracts", "runtime-r1", "evidence-r1", "runtime-r2", "evidence-r2",
              "runtime-r3", "evidence-r3", "recovery", "recovery-evidence", "performance",
              "build", "controls", "controls-verify"]


def validate_protocol(path: Path, track: str):
    p = json.loads(path.read_text())
    if p.get("schema_version") != "siq-evaluation-protocol/v1" or p.get("track") != track:
        raise ValueError("protocol schema/track mismatch")
    if track != "A" or p.get("operations") != OPERATIONS:
        raise ValueError("track/operations not implemented")
    if p.get("ready_to_run") is not True or p.get("model_calls_enabled") is not False:
        raise ValueError("protocol not ready or model calls requested")
    allocation = json.loads((path.parent / "allocation.json").read_text())
    if sha256(path.parent / "allocation.json") != p["allocation_sha256"]:
        raise ValueError("allocation digest mismatch")
    ids = [row["unit_id"] for row in allocation]
    if not ids or len(ids) != len(set(ids)) or len(ids) != p["allocation_count"]:
        raise ValueError("empty, duplicate, or incomplete allocation")
    candidate = Path(p["candidate_root"]).resolve()
    campaign = Path(p["campaign_root"]).resolve()
    candidate.relative_to(campaign / "private" / "candidates")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=candidate, text=True).strip()
    if commit != p["candidate_commit"]:
        raise ValueError("candidate commit changed")
    inventory = campaign / p.get("candidate_inventory", "inventory")
    inventory.resolve().relative_to(campaign)
    if sha256(inventory / "candidate.json") != p["candidate_manifest_sha256"]:
        raise ValueError("candidate manifest changed")
    original = json.loads((inventory / "candidate-source-files.json").read_text())
    for name, digest in original.items():
        if sha256(candidate / name) != digest:
            raise ValueError("candidate source digest changed: " + name)
    for key in ("per_command_seconds", "total_seconds", "memory_mib", "disk_mib", "max_concurrency"):
        if type(p["limits"].get(key)) is not int or p["limits"][key] <= 0:
            raise ValueError("missing finite resource limit")
    return p, allocation


def commands(candidate: Path, run: Path):
    python = str(candidate / "apps/control-api/.venv/bin/python")
    raw = run / "raw-private"
    binary = raw / "siq-agent-security"
    items = [("contracts", [python, "benchmarks/runtime-security/check_contracts.py"], None)]
    for i in (1, 2, 3):
        report = raw / f"runtime-r{i}.json"
        items += [(f"runtime-r{i}", [python, "benchmarks/runtime-security/run.py", "--suite", "full", "--out", str(report)], None),
                  (f"evidence-r{i}", [python, "benchmarks/runtime-security/evidence.py", str(report), "--suite", "full"], report)]
    recovery, performance, controls = (raw / f"{name}.json" for name in ("recovery", "performance", "controls"))
    items += [("recovery", [python, "benchmarks/runtime-security/recovery_fixture.py", "--out", str(recovery)], None),
              ("recovery-evidence", [python, "benchmarks/runtime-security/recovery_evidence.py", str(recovery)], recovery),
              ("performance", [python, "benchmarks/runtime-security/performance.py", "--out", str(performance)], None),
              ("build", ["go", "-C", "apps/agentshield", "build", "-trimpath", "-o", str(binary), "./cmd/agentshield"], None),
              ("controls", [python, "benchmarks/hackathon/run.py", "--binary", str(binary), "--state-root", str(raw / "controls-state"),
                            "--cohort", "controls", "--out", str(controls)], binary),
              ("controls-verify", [python, "benchmarks/hackathon/verify.py", str(controls), "--out", str(raw / "controls-verification.json")], controls)]
    return items


def summarize(run: Path, p: dict, allocation: list, results: list):
    raw = run / "raw-private"
    command_map = {r["command_id"]: r for r in results}
    captures, legacy_metrics = {}, {}
    for suite in ("runtime-r1", "runtime-r2", "runtime-r3", "controls"):
        path = raw / f"{suite}.json"
        if path.exists():
            report = json.loads(path.read_text())
            legacy_metrics[suite] = report.get("summary", report.get("metrics"))
            captures[suite] = {row.get("scenario_id", row.get("case_id", row.get("id", row.get("case", {}).get("id")))): row
                               for row in report.get("observations", report.get("results", report.get("cases", [])))}
    rows = []
    for unit in allocation:
        suite = f"runtime-r{unit['repetition']}" if unit["suite"] == "runtime" else "controls"
        observed = captures.get(suite, {}).get(unit["case_id"])
        verifier = command_map.get(suite.replace("runtime", "evidence") if suite.startswith("runtime") else "controls-verify", {})
        complete = observed is not None
        violations = observed.get("expectation_violations", []) if observed else []
        success = complete and not violations and verifier.get("exit_code") == 0
        row = {**unit, "run_id": run.name, "attempt": 1, "group": "B2", "track": "A",
               "execution_status": "completed" if complete else "error",
               "measurement_status": "determinate" if success else "indeterminate",
               "assertion_status": "fail" if violations else "pass" if success else "inconclusive",
               "harm_observed": None, "utility_completed": None,
               "harm_unknown_reason": "legacy observation does not define an independent harmful-outcome oracle",
               "utility_unknown_reason": "legacy completion retained separately; no new independent gold label",
               "evidence_refs": [f"raw-private/{suite}.json"] if complete else [],
               "legacy_observation": observed}
        rows.append(row)
    with (run / "cases.jsonl").open("x") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    failed = [r["command_id"] for r in results if r.get("exit_code") != 0 or r.get("error")]
    metrics = {"allocated": len(allocation), "captured": sum(r["execution_status"] == "completed" for r in rows),
               "assertion_pass": sum(r["assertion_status"] == "pass" for r in rows),
               "inconclusive": sum(r["assertion_status"] == "inconclusive" for r in rows),
               "failed_commands": failed, "legacy_metrics_separate_populations": legacy_metrics,
               "note": "42 scenarios × 3 repetitions + 23 controls; repetitions are not independent scenarios."}
    write_json(run / "metrics.json", metrics)
    findings = [{"finding_id": f"A-{i+1:03d}", "type": "execution_or_assertion_failure", "command_id": name,
                 "classification": "requires_triage", "original_attempt_retained": True} for i, name in enumerate(failed)]
    write_json(run / "findings.json", findings)
    return metrics


def seal(run: Path, metadata: dict):
    # Explicit whitelist excludes daemon states, keys, logs, temp files, and binaries.
    paths = ["protocol.json", "allocation.json", "execution-plan.json", "command-events.jsonl", "case-events.jsonl",
             "cases.jsonl", "metrics.json", "findings.json", "report.md"]
    paths += [p.relative_to(run).as_posix() for p in sorted((run / "harness-source").glob("*.py"))]
    paths += [p.relative_to(run).as_posix() for p in sorted((run / "raw-private").glob("*.json"))]
    sums = {name: sha256(run / name) for name in paths if (run / name).is_file()}
    write_json(run / "checksums.json", sums)
    write_json(run / "manifest.json", {**metadata, "schema_version": "siq-evaluation-manifest/v1",
                                      "sealed_at": utc_now(), "checksums_sha256": sha256(run / "checksums.json"),
                                      "trust": "author_local; digest must be held independently for external integrity"})
    return sha256(run / "manifest.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--track", choices=list("ABCDEF"), required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--resume", action="store_true", help="v2 journal: execute only scheduled attempts")
    parser.add_argument("--retry", help="v2 journal: explicitly schedule a new attempt for a reconciled unit")
    parser.add_argument("--seal", action="store_true", help="v2 journal: seal immutable final projections")
    args = parser.parse_args()
    try:
        document = json.loads(args.protocol.read_text())
        if not isinstance(document, dict):
            raise TypeError("protocol must be an object")
        version = document.get("schema_version")
        if version == "siq-evaluation-protocol/v2":
            if document.get("operation") == "product_samples":
                from product_journal import preflight
                from product_journal import run as run_journal
            else:
                from journal_runner import preflight
                from journal_runner import run as run_journal
            p = preflight(args.protocol)
            if p["track"] != args.track:
                raise ValueError("track mismatch")
            if args.preflight_only:
                print(json.dumps({"preflight": "passed", "scope": p["measurement_kind"]}))
                return 0
            if not args.out:
                raise ValueError("--out required")
            return run_journal(args.protocol, args.out, resume=args.resume, retry=args.retry, seal=args.seal)
        if args.resume or args.retry or args.seal:
            raise ValueError("legacy runs cannot be replayed or mutated; use a new cohort")
    except (ValueError, KeyError, OSError, TypeError) as exc:
        print(json.dumps({"error_type": type(exc).__name__, "detail": str(exc)}), file=sys.stderr)
        return 3
    try:
        p, allocation = validate_protocol(args.protocol.resolve(), args.track)
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
        print(f"invalid protocol: {exc}", file=sys.stderr)
        return 3
    if args.preflight_only:
        print(json.dumps({"preflight": "passed", "allocated": len(allocation), "model_calls": False}))
        return 0
    if not args.out:
        parser.error("--out is required for execution")
    os.umask(0o077)
    run = args.out.resolve()
    run.relative_to(Path(p["campaign_root"]) / "private" / "runs")
    run.mkdir(mode=0o700, parents=True, exist_ok=False)
    raw = run / "raw-private"
    raw.mkdir(mode=0o700)
    shutil.copyfile(args.protocol, run / "protocol.json")
    shutil.copyfile(args.protocol.parent / "allocation.json", run / "allocation.json")
    harness = run / "harness-source"
    harness.mkdir()
    for source in Path(__file__).parent.glob("*.py"):
        shutil.copyfile(source, harness / source.name)
    candidate = Path(p["candidate_root"])
    items = commands(candidate, run)
    write_json(run / "execution-plan.json", [{"command_id": name, "argv": argv,
                                            "depends_on_artifact": str(dependency) if dependency else None}
                                           for name, argv, dependency in items])
    events = Events(run / "command-events.jsonl", run.name)
    cases = Events(run / "case-events.jsonl", run.name)
    for unit in allocation:
        cases.add("scheduled", **unit, attempt=1)
    started = time.monotonic()
    results = []
    for name, argv, dependency in items:
        reason = None
        if dependency and not dependency.is_file():
            reason = "dependency_artifact_missing"
        if time.monotonic() - started >= p["limits"]["total_seconds"]:
            reason = "total_time_limit"
        disk = sum(f.stat().st_size for f in run.rglob("*") if f.is_file() and not f.is_symlink())
        if disk > p["limits"]["disk_mib"] * 1024 * 1024:
            reason = "disk_limit"
        if reason:
            row = {"command_id": name, "exit_code": None, "error": reason}
            events.add("command_blocked", **row)
        else:
            print(f"START {name}", flush=True)
            row = run_command(events, name, argv, candidate, raw / "logs",
                              timeout=min(p["limits"]["per_command_seconds"],
                                          max(1, int(p["limits"]["total_seconds"] - (time.monotonic() - started)))),
                              memory_mib=p["limits"]["memory_mib"], env=clean_environment(raw / "tmp"))
            print(f"FINISH {name}: exit={row['exit_code']} error={row['error']}", flush=True)
        results.append(row)
    metrics = summarize(run, p, allocation, results)
    for line in (run / "cases.jsonl").read_text().splitlines():
        row = json.loads(line)
        cases.add("legacy_capture_finished", unit_id=row["unit_id"], attempt=1,
                  execution_status=row["execution_status"], assertion_status=row["assertion_status"],
                  timing_scope="legacy batch capture; per-case start time unavailable")
    report = (f"# A 轨道确定性复现\n\n候选 `{p['candidate_commit']}`；执行方 `author_run`；模型调用 0。\n\n"
              f"分配 {metrics['allocated']} 单元，捕获 {metrics['captured']}，经既有验证器核对通过 {metrics['assertion_pass']}，"
              f"待核实 {metrics['inconclusive']}。\n\n三轮运行时报告各自包含 42 场景，三轮重复不构成 126 个独立场景。"
              "应用控制单独计 23 项。旧指标保留在 metrics.json，各自使用原分母。\n\n"
              f"失败命令：{', '.join(metrics['failed_commands']) or '无'}。\n\n"
              "这批结果检验既有确定性入口，不证明模型抗攻击率、同 UID 强隔离、全部原生平台或独立第三方认证。"
              "新外部 oracle 的 harm/utility 尚未测量，保持 null。\n")
    (run / "report.md").write_text(report)
    anchor = seal(run, {"run_id": run.name, "candidate_commit": p["candidate_commit"],
                        "protocol_sha256": sha256(run / "protocol.json"), "allocation_count": len(allocation),
                        "relationship": "author_run", "model_calls": 0})
    write_json(Path(p["campaign_root"]) / "inventory" / f"{run.name}-local-anchor.json",
               {"run_id": run.name, "manifest_sha256": anchor, "recorded_at": utc_now(), "custody": "author_local"})
    print(json.dumps({"run": str(run), "manifest_sha256": anchor, "failed_commands": metrics["failed_commands"]}))
    return 2 if metrics["failed_commands"] or metrics["inconclusive"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
