#!/usr/bin/env python3
"""Freeze explicitly allowlisted benchmark repairs without changing product code."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

from common import Events, run_command, sha256, utc_now, write_json

ROOT = Path(__file__).resolve().parents[2]
REPAIRS = ("benchmarks/runtime-security/network_fixture.py", "benchmarks/runtime-security/approval_fixture.py")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--repair-id", required=True)
    args = parser.parse_args()
    if not args.repair_id.isalnum():
        raise ValueError("repair id must be alphanumeric")
    campaign = args.campaign.resolve()
    private = campaign / "private"
    base = json.loads((campaign / "inventory/candidate.json").read_text())
    commit = base["source_commit"]
    original = private / "candidates" / commit[:12]
    target = private / "candidates" / (commit[:12] + "-" + args.repair_id)
    events = Events(private / f"{args.repair_id}-preparation-events.jsonl", args.repair_id)
    logs = private / f"{args.repair_id}-preparation-logs"
    for name, argv, cwd in [
        ("clone", ["git", "clone", "--local", "--no-hardlinks", "--no-checkout", str(original), str(target)], ROOT),
        ("checkout", ["git", "checkout", "--detach", commit], target),
        ("remove-remote", ["git", "remote", "remove", "origin"], target),
    ]:
        result = run_command(events, name, argv, cwd, logs)
        if result["exit_code"] != 0:
            raise RuntimeError("candidate preparation failed: " + name)
    files = json.loads((campaign / "inventory/candidate-source-files.json").read_text())
    for name in REPAIRS:
        shutil.copyfile(ROOT / name, target / name)
        files[name] = sha256(target / name)
    inventory = campaign / "inventory/candidates" / args.repair_id
    write_json(inventory / "candidate-source-files.json", files)
    base.update(candidate_id=commit[:12] + "-" + args.repair_id, working_tree_dirty=True,
                source_file_manifest_sha256=sha256(inventory / "candidate-source-files.json"),
                patch_kind="benchmark_fixtures_only", changed_source={name: files[name] for name in REPAIRS},
                product_runtime_unchanged=True, frozen_at=utc_now())
    write_json(inventory / "candidate.json", base)
    (inventory / "fixture-fix.patch").write_bytes(subprocess.check_output(["git", "diff", "--", *REPAIRS], cwd=target))
    protocol = json.loads((campaign / "protocols/A-v1/protocol.json").read_text())
    protocol.update(protocol_id="A-" + args.repair_id, candidate_root=str(target),
                    candidate_inventory=str(inventory.relative_to(campaign)),
                    candidate_manifest_sha256=sha256(inventory / "candidate.json"), frozen_at=utc_now(),
                    repair={"files": list(REPAIRS), "product_runtime_unchanged": True},
                    first_attempt_protocol="A-v1")
    dest = campaign / "protocols" / protocol["protocol_id"]
    dest.mkdir()
    shutil.copyfile(campaign / "protocols/A-v1/allocation.json", dest / "allocation.json")
    write_json(dest / "protocol.json", protocol)
    write_json(dest / "local-anchor.json", {"protocol_sha256": sha256(dest / "protocol.json"),
                                           "custody": "author_local", "recorded_at": utc_now()})
    result = run_command(events, "dependency-sync", ["uv", "sync", "--dev", "--locked"],
                         target / "apps/control-api", logs)
    if result["exit_code"] != 0:
        raise RuntimeError("locked dependency setup failed")
    print(json.dumps({"protocol": str(dest / "protocol.json"), "candidate": str(target)}))


if __name__ == "__main__":
    main()
