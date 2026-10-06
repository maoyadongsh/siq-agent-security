"""Real SIGKILL, exclusive-writer, conservative resume and explicit-retry calibration."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from common import canonical, sha256, utc_now, write_json
from lifecycle import project
from verify_journal import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if not args.run_id.replace("-", "").isalnum():
        raise ValueError("invalid run ID")
    campaign = args.campaign.resolve()
    root = campaign / "protocols" / (args.run_id + "-protocol")
    root.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).parent
    names = ["run.py", "common.py", "lifecycle.py", "journal_runner.py", "schemas/case.v1.schema.json"]
    for name in names:
        target = root / "harness-source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    sources = {name: sha256(root / "harness-source" / name) for name in names}
    allocation = [{"unit_id": name, "case_id": name, "pair_id": "recovery", "task_block_id": name,
                   "track": "B", "group": "CALIBRATION", "family_id": "TP02", "claim_ids": [],
                   "product_group_ids": [], "forbid_write": index == 0}
                  for index, name in enumerate(("interrupted-write", "independent-write"))]
    protocol = {"schema_version": "siq-evaluation-protocol/v2", "run_id": args.run_id,
                "operation": "marker_calibration", "track": "B", "measurement_kind": "harness_calibration",
                "relationship": "author_run", "model_calls_enabled": False, "max_attempts": 2,
                "pause_seconds": 60, "campaign_root": str(campaign), "allocation": allocation,
                "candidate_digest": hashlib.sha256(canonical(sources)).hexdigest(),
                "harness_sources": sources, "frozen_at": utc_now()}
    write_json(root / "protocol.json", protocol)
    write_json(root / "local-anchor.json", {"sha256": sha256(root / "protocol.json")})
    out = campaign / "private/runs" / args.run_id
    evidence = campaign / "data" / (args.run_id + "-calibration")
    evidence.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, str(root / "harness-source/run.py"), "--protocol", str(root / "protocol.json"),
               "--track", "B", "--out", str(out)]
    results = {}

    def invoke(name, *flags):
        response = subprocess.run([*command, *flags], capture_output=True, text=True, timeout=20, check=False)
        write_json(evidence / (name + ".json"), {"argv": [*command, *flags], "exit_code": response.returncode,
                                               "stdout": response.stdout, "stderr": response.stderr})
        return response.returncode

    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError("worker exited before interruption window")
            try:
                _, states, _, _ = project(out)
                if states["interrupted-write#1"]["harm_observed"] is True:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.05)
        else:
            raise RuntimeError("interruption window timeout")
        results["live_writer_excluded"] = invoke("concurrent-writer", "--resume") == 3
        child.kill()
        stdout, stderr = child.communicate(timeout=5)
        write_json(evidence / "killed-worker.json", {"pid": child.pid, "returncode": child.returncode, "stdout": stdout, "stderr": stderr})
        results["actual_sigkill"] = child.returncode == -9
        before = (out / "journal.jsonl").read_bytes()
        (evidence / "before-resume.jsonl").write_bytes(before)
        results["resume_preserves_unknown_exit"] = invoke("resume", "--resume") == 2
        _, states, _, _ = project(out)
        results["only_unstarted_dispatched"] = len(list((out / "attempts").rglob("marker.txt"))) == 2
        results["original_harm_preserved"] = states["interrupted-write#1"]["harm_observed"] is True
        results["original_utility_unknown"] = states["interrupted-write#1"]["utility_completed"] is None
        results["independent_unit_completed"] = states["independent-write#1"]["assertion_status"] == "pass"
        after = (out / "journal.jsonl").read_bytes()
        (evidence / "after-resume.jsonl").write_bytes(after)
        results["original_prefix_unchanged"] = after.startswith(before)
        results["second_resume_no_replay"] = invoke("second-resume", "--resume") == 2 and (out / "journal.jsonl").read_bytes() == after
        results["explicit_retry_keeps_first_outcome"] = invoke("retry", "--resume", "--retry", "interrupted-write") == 2
        _, states, _, _ = project(out)
        results["new_attempt_linked"] = states["interrupted-write#2"]["retry_of"] == "interrupted-write#1" and states["interrupted-write#2"]["assertion_status"] == "pass"
        results["retry_separate_effect"] = len(list((out / "attempts").rglob("marker.txt"))) == 3
        retry_bytes = (out / "journal.jsonl").read_bytes()
        results["attempt_budget_enforced"] = invoke("excess-retry", "--resume", "--retry", "interrupted-write") == 3 and (out / "journal.jsonl").read_bytes() == retry_bytes
        results["seal_keeps_unknown"] = invoke("seal", "--resume", "--seal") == 2
        results["sealed_run_immutable"] = invoke("sealed-resume", "--resume") == 3 and (out / "journal.jsonl").read_bytes() == retry_bytes
        anchor = sha256(out / "manifest.json")
        verified, code = verify(out, anchor)
        results["offline_first_attempt_recomputed"] = code == 2 and verified["attempts"] == 3 and verified["known_harm_first_attempt"] == 1
        export = campaign / "data" / args.run_id
        export.mkdir()
        manifest = json.loads((out / "manifest.json").read_text())
        for name in [*manifest["artifacts"], "manifest.json"]:
            target = export / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out / name, target)
        write_json(campaign / "inventory/anchors" / (args.run_id + ".json"), {"manifest_sha256": anchor, "custody": "author_local"})
        write_json(campaign / "reports" / (args.run_id + "-verification.json"), verified)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        write_json(evidence / "calibration.json", {"checks": results, "passed": len(results) == 16 and all(results.values()),
                   "scope": "real evaluation process interruption; no product security result"})
        write_json(evidence / "manifest.json", {"artifacts": {p.name: sha256(p) for p in evidence.iterdir() if p.is_file()}})
    print(json.dumps({"checks": results, "calibration_manifest_sha256": sha256(evidence / "manifest.json")}), flush=True)
    return 0 if len(results) == 16 and all(results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
