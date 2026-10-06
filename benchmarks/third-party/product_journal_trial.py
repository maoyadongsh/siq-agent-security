"""Interrupt an owned real product evaluator; reconcile daemon, resume, retry and seal."""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from common import sha256, write_json
from lifecycle import process_state, project
from process_resources import stop_owned
from product_journal import freeze
from verify_product_journal import verify


def export(campaign, out):
    anchor = sha256(out / "manifest.json")
    verified, code = verify(out, anchor)
    target = campaign / "data" / out.name
    manifest = json.loads((out / "manifest.json").read_text())
    secrets = [p.read_bytes().strip() for p in (campaign / "private/credentials").glob("*.key")]
    for name in [*manifest["artifacts"], "manifest.json"]:
        if any(secret and secret in (out / name).read_bytes() for secret in secrets):
            raise ValueError("credential detected; export stopped")
    target.mkdir(exist_ok=False)
    for name in [*manifest["artifacts"], "manifest.json"]:
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out / name, destination)
    write_json(campaign / "inventory/anchors" / (out.name + ".json"), {"manifest_sha256": anchor, "custody": "author_local"})
    write_json(campaign / "reports" / (out.name + "-verification.json"), verified)
    return verified, code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    campaign = args.campaign.resolve()
    unit_id = "EV08.sample.adversarial"
    freeze(campaign, args.run_id, unit_id)
    root = campaign / "protocols" / (args.run_id + "-protocol")
    out = campaign / "private/runs" / args.run_id
    evidence = campaign / "data" / (args.run_id + "-recovery")
    evidence.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, str(root / "harness-source/run.py"), "--protocol", str(root / "protocol.json"),
               "--track", "B", "--out", str(out)]
    checks = {}

    def invoke(name, *flags):
        response = subprocess.run([*command, *flags], capture_output=True, text=True, timeout=240, check=False)
        write_json(evidence / (name + ".json"), {"argv": [*command, *flags], "exit_code": response.returncode,
                                               "stdout": response.stdout, "stderr": response.stderr})
        return response.returncode

    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    resource = None
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError("product evaluator exited before checkpoint")
            try:
                _, states, _, _ = project(out)
                row = states[unit_id + "#1"]
                if row["harm_observed"] is True:
                    resource = json.loads((out / "attempts" / unit_id / "1/resource.json").read_text())
                    break
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(0.05)
        else:
            raise RuntimeError("product interruption checkpoint timeout")
        checks["daemon_alive_before_interruption"] = process_state(resource["daemon"]) == "alive"
        checks["live_writer_excluded"] = invoke("concurrent-writer", "--resume") == 3
        child.kill()
        stdout, stderr = child.communicate(timeout=5)
        write_json(evidence / "killed-worker.json", {"pid": child.pid, "returncode": child.returncode,
                                                   "stdout": stdout, "stderr": stderr, "resource": resource})
        checks["actual_sigkill"] = child.returncode == -9
        checks["orphan_daemon_really_remains"] = process_state(resource["daemon"]) == "alive"
        before = (out / "journal.jsonl").read_bytes()
        (evidence / "before-resume.jsonl").write_bytes(before)
        checks["resume_retains_unknown_exit"] = invoke("resume", "--resume") == 2
        _, states, _, _ = project(out)
        interrupted = states[unit_id + "#1"]
        checks["observed_harm_retained"] = interrupted["harm_observed"] is True
        checks["interrupted_utility_unknown"] = interrupted["utility_completed"] is None
        checks["owned_daemon_stopped"] = process_state(resource["daemon"]) != "alive" and interrupted["cleanup_confirmed"]
        checks["only_remaining_nine_completed"] = sum(row["assertion_status"] == "pass" for row in states.values()) == 9 and len(states) == 10
        after = (out / "journal.jsonl").read_bytes()
        (evidence / "after-resume.jsonl").write_bytes(after)
        checks["journal_prefix_retained"] = after.startswith(before)
        checks["second_resume_no_replay"] = invoke("second-resume", "--resume") == 2 and (out / "journal.jsonl").read_bytes() == after
        checks["retry_preserves_first_outcome"] = invoke("retry", "--resume", "--retry", unit_id) == 2
        _, states, _, _ = project(out)
        retry = states[unit_id + "#2"]
        checks["fresh_linked_retry_passed"] = retry["retry_of"] == unit_id + "#1" and retry["assertion_status"] == "pass"
        first_oracle = json.loads((out / "attempts" / unit_id / "1/oracle.json").read_text())
        retry_oracle = json.loads((out / "attempts" / unit_id / "2/oracle.json").read_text())
        checks["fresh_effect_nonce"] = first_oracle["nonce"] != retry_oracle["nonce"]
        retry_bytes = (out / "journal.jsonl").read_bytes()
        checks["attempt_limit_enforced"] = invoke("excess-retry", "--resume", "--retry", unit_id) == 3 and (out / "journal.jsonl").read_bytes() == retry_bytes
        checks["seal_retains_unknown_exit"] = invoke("seal", "--resume", "--seal") == 2
        checks["sealed_run_immutable"] = invoke("sealed-resume", "--resume") == 3 and (out / "journal.jsonl").read_bytes() == retry_bytes
        verified, code = export(campaign, out)
        checks["offline_first_attempt_recomputed"] = code == 2 and verified["attempts"] == 11 and verified["first_attempt_unknown"] == 1 and verified["known_harm_first_attempt"] == 1
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        if resource and process_state(resource["daemon"]) == "alive":
            write_json(evidence / "emergency-cleanup.json", stop_owned(resource["daemon"], resource["command_sha256"]))
        write_json(evidence / "recovery.json", {"checks": checks, "passed": len(checks) == 18 and all(checks.values()),
                   "scope": "registered real component evaluator and owned daemon; no model/native-host recovery claim"})
        write_json(evidence / "manifest.json", {"artifacts": {p.name: sha256(p) for p in evidence.iterdir() if p.is_file()}})
    print(json.dumps({"checks": checks, "recovery_manifest_sha256": sha256(evidence / "manifest.json")}), flush=True)
    return 0 if len(checks) == 18 and all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
