#!/usr/bin/env python3
"""Freeze a clean local product candidate and the legacy fixture allocation."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

from common import (
    Events,
    clean_environment,
    run_command,
    sha256,
    utc_now,
    write_json,
)

ROOT = Path(__file__).resolve().parents[2]


def git(*args, cwd=ROOT):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    campaign = args.campaign.resolve()
    campaign.relative_to(ROOT)
    private = campaign / "private"
    private.mkdir(mode=0o700, parents=True, exist_ok=True)
    private.chmod(0o700)
    inventory = campaign / "inventory"
    events = Events(private / "preparation-events.jsonl", "preparation-v1")
    status = subprocess.check_output(["git", "status", "--porcelain=v1", "-z"], cwd=ROOT)
    (private / "source-status-before.bin").write_bytes(status)
    changed = {}
    for item in status.decode().split("\0"):
        if not item:
            continue
        name = item[3:]
        if name.startswith(("evaluations/", "benchmarks/third-party/")):
            continue
        file = ROOT / name
        if file.is_file() and not file.is_symlink():
            changed[name] = {"status": item[:2], "sha256": sha256(file)}
        elif not file.exists():
            changed[name] = {"status": item[:2], "sha256": None}
    write_json(private / "source-changes-before.json", changed)
    commit = git("rev-parse", "HEAD")
    candidate = private / "candidates" / commit[:12]
    steps = [("clone", ["git", "clone", "--local", "--no-hardlinks", "--no-checkout", str(ROOT), str(candidate)], ROOT),
             ("checkout", ["git", "checkout", "--detach", commit], candidate),
             ("remove-remote", ["git", "remote", "remove", "origin"], candidate)]
    for command_id, argv, cwd in steps:
        result = run_command(events, command_id, argv, cwd, private / "preparation-logs")
        if result["exit_code"] != 0:
            raise SystemExit(f"candidate preparation failed: {command_id}; see private logs")
    if git("status", "--porcelain", cwd=candidate):
        raise SystemExit("cloned candidate is dirty")
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=candidate).decode().split("\0")
    manifest = {name: sha256(candidate / name) for name in files
                if name and (candidate / name).is_file() and not (candidate / name).is_symlink()}
    write_json(inventory / "candidate-source-files.json", manifest)
    write_json(inventory / "candidate.json", {
        "candidate_id": f"commit-{commit[:12]}", "source_commit": commit,
        "git_tree": git("rev-parse", "HEAD^{tree}", cwd=candidate), "working_tree_dirty": False,
        "source_workspace_dirty": bool(status), "includes_source_uncommitted_changes": False,
        "source_file_manifest_sha256": sha256(inventory / "candidate-source-files.json"),
        "source_lock_sha256": {name: manifest[name] for name in
                               ("apps/control-api/uv.lock", "apps/agentshield/go.mod", "apps/web/package-lock.json")},
        "frozen_at": utc_now(), "relationship": "author_run"})
    tool_versions = {}
    for tool, argv in {"go": ["go", "version"], "uv": ["uv", "--version"],
                       "python": ["python3", "--version"]}.items():
        tool_versions[tool] = subprocess.check_output(argv, text=True).strip()
    listening = subprocess.check_output(["ss", "-ltnH"], text=True)
    (private / "listening-ports-before.txt").write_text(listening)
    write_json(inventory / "environment.json", {
        "captured_at": utc_now(), "platform": platform.platform(), "architecture": platform.machine(),
        "cpu_count": os.cpu_count(), "tool_versions": tool_versions, "available_disk_bytes": shutil.disk_usage(campaign).free,
        "existing_listeners_count": len(listening.splitlines()), "loopback_ephemeral_ports_required": True,
        "model_calls_enabled": False, "environment_export": "allowlist only; no credential values"})
    plan = campaign / "plan"
    plan.mkdir(exist_ok=True)
    planfiles = [ROOT / "docs/research/third-party-evaluation-plan-20261006.md"]
    planfiles.extend(sorted((ROOT / "docs/research/third-party-evaluation-20261006").glob("*")))
    copied = {}
    for source in planfiles:
        if source.is_file():
            target = plan / source.name
            with target.open("xb") as stream:
                stream.write(source.read_bytes())
            copied[source.relative_to(ROOT).as_posix()] = sha256(target)
    write_json(plan / "snapshot-index.json", {"copied_at": utc_now(), "files": copied,
                                             "note": "Exact source snapshots; relative links retain their original repository meaning."})
    runtime = [json.loads(p.read_text()) for p in sorted((candidate / "benchmarks/runtime-security/scenarios").glob("*.json"))]
    controls = json.loads((candidate / "benchmarks/hackathon/cases.json").read_text())["cases"]
    allocation = [{"unit_id": f"runtime-r{repeat}:{s['id']}", "suite": "runtime", "repetition": repeat,
                   "case_id": s["id"], "pair_id": s["pair_id"], "kind": s["kind"], "category": s["category"]}
                  for repeat in (1, 2, 3) for s in runtime]
    allocation += [{"unit_id": f"controls:{s['id']}", "suite": "controls", "repetition": 1,
                    "case_id": s["id"], "kind": s["kind"], "category": s["category"]} for s in controls]
    protocols = campaign / "protocols" / "A-v1"
    write_json(protocols / "allocation.json", allocation)
    write_json(inventory / "applicability.json", {
        "A": {"status": "available", "scope": "Linux ARM64 isolated deterministic fixtures"},
        "B": {"status": "implementation_required"}, "C": {"status": "adapter_and_model_required"},
        "D": {"status": "upstream_review_required"}, "E": {"status": "container_review_required"},
        "F": {"linux": "environment_review_required", "windows_native": "device_not_bound", "macos_native": "device_not_bound"},
        "model": {"status": "awaiting_endpoint_and_budget", "cost_cap": 0},
        "independent_review": {"status": "pending_external_party"}})
    protocol = {"schema_version": "siq-evaluation-protocol/v1", "protocol_id": "A-v1", "track": "A",
                "cohort": "legacy_fixture", "ready_to_run": True, "frozen_at": utc_now(),
                "candidate_commit": commit, "candidate_root": str(candidate), "campaign_root": str(campaign),
                "candidate_manifest_sha256": sha256(inventory / "candidate.json"),
                "allocation_sha256": sha256(protocols / "allocation.json"),
                "allocation_count": len(allocation), "runtime_repetitions": 3,
                "runtime_scenarios_per_repeat": len(runtime), "controls_count": len(controls),
                "groups": ["B2"], "model_calls_enabled": False, "model_cost_cap": 0,
                "limits": {"per_command_seconds": 1800, "total_seconds": 21600, "memory_mib": 16384,
                           "output_per_command_mib": 128, "disk_mib": 20480, "max_concurrency": 1},
                "operations": ["contracts", "runtime-r1", "evidence-r1", "runtime-r2", "evidence-r2",
                               "runtime-r3", "evidence-r3", "recovery", "recovery-evidence", "performance",
                               "build", "controls", "controls-verify"],
                "measurement": "Preserve legacy metric populations; decision-only cases retain unknown effects.",
                "retry": "No automatic replay. First failures retained; new run required for rerun.",
                "external_anchor": None, "relationship": "author_run", "publication": "local_only"}
    write_json(protocols / "protocol.json", protocol)
    write_json(protocols / "local-anchor.json", {"protocol_sha256": sha256(protocols / "protocol.json"),
                                                "custody": "author_local_not_independent", "recorded_at": utc_now()})
    progress = {"campaign_id": "20261006", "updated_at": utc_now(), "goal_status": "active", "tasks": []}
    for number in range(11):
        progress["tasks"].append({"task_id": f"TP{number:02d}", "status": "in_progress" if number == 0 else "planned",
                                  "candidate_id": f"commit-{commit[:12]}", "protocol_id": "A-v1" if number < 2 else None,
                                  "commands": [], "artifact_refs": [], "findings": [], "blocked_by": [],
                                  "next_action": "complete interface bindings" if number == 0 else "follow CODEX_HANDOFF"})
    write_json(campaign / "implementation-progress.json", progress)
    events.add("candidate_prepared", candidate_commit=commit, allocation_count=len(allocation))
    result = run_command(events, "dependency-sync", ["uv", "sync", "--dev", "--locked"],
                         candidate / "apps/control-api", private / "preparation-logs",
                         env=clean_environment(private / "tmp"))
    if result["exit_code"] != 0:
        raise SystemExit("locked dependency setup failed; original failure retained")
    print(json.dumps({"candidate": str(candidate), "protocol": str(protocols / "protocol.json"),
                      "allocated": len(allocation), "status": "prepared"}))


if __name__ == "__main__":
    main()
