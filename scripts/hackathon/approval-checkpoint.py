#!/usr/bin/env python3
"""Actual SIQ approval/recheck cases with explicit fixture-model proposals."""

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/secure-agent"))

from secure_agent.application import SecureApplication
from secure_agent.authority import LocalDaemon
from secure_agent.contracts import AgentError
from secure_agent.fixtures import FixtureServices
from secure_agent.models import FixtureProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.state_root.mkdir(parents=True, mode=0o700)
    spec = importlib.util.spec_from_file_location("runtime_evidence", ROOT / "benchmarks/runtime-security/evidence.py")
    evidence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evidence)
    cases = []
    for case in ("approved", "rejected", "revoked", "parameters-changed", "unavailable", "expired"):
        with LocalDaemon(args.binary, args.state_root / case) as daemon, FixtureServices(ROOT / "demo/fixtures") as fixtures:
            snapshot = {}
            checked_effects = []

            def changed(value, snapshot=snapshot):
                snapshot.update(value)

            def hold(request, decision, authority, snapshot=snapshot, checked_effects=checked_effects, case=case):
                for action in snapshot["task"]["actions"]:
                    if action["effect"]:
                        record = action["effect"]
                        identity = record["evidence"]["effect_evidence_id"]
                        if daemon.admin.request("/v1/effect-evidence/" + identity) != record:
                            raise ValueError("effect readback mismatch")
                        checked_effects.append(identity)
                if case == "expired":
                    return  # the actual daemon's sixty-second hold expires normally
                authority.admin.request("/v1/hold/" + decision["receipt_id"],
                    {"approve": case != "rejected", "actor_id": "automated-approval-test-operator"})
                if case == "revoked":
                    authority.admin.request("/v1/intents/" + authority.intent["intent_id"] + "/revoke",
                                            {"expected_intent_digest": authority.intent["digest"]})
                if case == "parameters-changed":
                    replaced = {**request, "params": {"path": request["params"]["path"] + ".replaced"}}
                    try:
                        authority.client.recheck_hold(replaced, decision)
                    except AgentError as exc:
                        if str(exc) == "hold_identity_mismatch":
                            raise
                        raise ValueError("wrong replacement rejection") from exc
                    raise ValueError("replaced parameters passed")
                if case == "unavailable":
                    daemon._proc.terminate()
                    daemon._proc.wait(timeout=10)

            try:
                result = SecureApplication(ROOT, daemon, fixtures, FixtureProvider(mode="test")).run(
                    "Review the repository and request approval before checking the report in a process",
                    repository="fixture/secure-project", question="Review code", scope=("README.md",),
                    approval_required=True, on_hold=hold, changed=changed)
            except AgentError as exc:
                if case != "unavailable" or str(exc) != "siq_unavailable":
                    raise
                result = {"task": snapshot["task"], "intent": snapshot["intent"], "messages": fixtures.messages(),
                          "completion_readback": "unavailable"}
            process = next(a for a in result["task"]["actions"] if a["tool"] == "verify_report")
            materialized = process["d3_materialized"]
            if materialized != (case == "approved") or len(result["messages"]) != int(case == "approved"):
                raise ValueError("approval bypass: " + case)
            expected = {"approved": None, "rejected": "hold_denied", "revoked": "hold_authority_changed",
                        "parameters-changed": "hold_identity_mismatch", "unavailable": "siq_unavailable", "expired": "hold_expired"}[case]
            if result["task"]["error_code"] != expected or (case == "approved" and result["task"]["status"] != "verified"):
                raise ValueError("unexpected task state: " + case)
            env = {**os.environ, "SIQ_AGENT_SECURITY_STATE_DIR": str(daemon.state)}

            def command(argv, env=env):
                return subprocess.run(argv, env=env, text=True, capture_output=True, check=True).stdout

            bundle = evidence.capture(SimpleNamespace(state=daemon.state, binary=daemon.binary, command=command), case)
            _, count = evidence.verify_receipt_bundles([bundle])
            cases.append({"scenario": case, "result": result, "public_evidence": bundle,
                "verification": {"receipt_count": count, "receipt_signatures_and_chains": "verified",
                                 "pre_hold_effect_readbacks": checked_effects}})
            print(json.dumps({"scenario": case, "process_started": materialized, "status": result["task"]["status"]}), flush=True)
    report = {"schema_version": "hackathon-approval-checkpoint/v1", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "provider": "fixture", "approval_actor": "automated test operator using real admin API",
        "scope": "built-in verify_report process under required bound Intent V3; no arbitrary shell",
        "cases": cases}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
