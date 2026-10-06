"""Freeze only explicit governance repair and preexisting benchmark fixture fixes."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from common import Events, run_command, sha256, utc_now, write_json

ROOT = Path(__file__).resolve().parents[2]
FILES = ("apps/control-api/app/routers/policies.py",
         "benchmarks/runtime-security/network_fixture.py", "benchmarks/runtime-security/approval_fixture.py")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--repair-id", required=True)
    args = parser.parse_args()
    if not args.repair_id.isalnum():
        raise ValueError("alphanumeric repair ID required")
    campaign = args.campaign.resolve()
    base = json.loads((campaign / "inventory/candidate.json").read_text())
    commit = base["source_commit"]
    original = campaign / "private/candidates" / commit[:12]
    target = original.with_name(commit[:12] + "-" + args.repair_id)
    inventory = campaign / "inventory/candidates" / args.repair_id
    events = Events(campaign / "private" / (args.repair_id + "-preparation-events.jsonl"), args.repair_id)
    logs = campaign / "private" / (args.repair_id + "-preparation-logs")
    for name, argv, cwd in [
        ("clone", ["git", "clone", "--local", "--no-hardlinks", "--no-checkout", str(original), str(target)], ROOT),
        ("checkout", ["git", "checkout", "--detach", commit], target),
        ("remove-remote", ["git", "remote", "remove", "origin"], target),
    ]:
        result = run_command(events, name, argv, cwd, logs)
        if result["exit_code"]:
            raise RuntimeError("candidate preparation failed: " + name)
    files = json.loads((campaign / "inventory/candidate-source-files.json").read_text())
    for name in FILES:
        shutil.copyfile(ROOT / name, target / name)
        files[name] = sha256(target / name)
    write_json(inventory / "candidate-source-files.json", files)
    base.update(candidate_id=target.name, candidate_root=str(target), working_tree_dirty=True,
                changed_source={name: files[name] for name in FILES}, product_runtime_unchanged=False,
                patch_kind="governance_concurrency_fix_plus_preexisting_benchmark_fixtures", frozen_at=utc_now(),
                source_file_manifest_sha256=sha256(inventory / "candidate-source-files.json"))
    write_json(inventory / "candidate.json", base)
    (inventory / "repair.patch").write_bytes(subprocess.check_output(["git", "diff", "--", *FILES], cwd=target))
    shutil.copyfile(__file__, inventory / "prepare_governance_repair.py")
    result = run_command(events, "dependency-sync", ["uv", "sync", "--dev", "--locked"], target / "apps/control-api", logs)
    if result["exit_code"]:
        raise RuntimeError("locked dependency setup failed")
    print(json.dumps({"candidate": str(target), "inventory": str(inventory)}))


if __name__ == "__main__":
    main()
