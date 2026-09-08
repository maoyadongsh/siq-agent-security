#!/usr/bin/env python3
"""Archive five real application runs with an explicitly selected fixture model.

This is a development checkpoint, not the twenty-task competition benchmark.
Receipt verification reuses the existing runtime-security verifier.
"""

import argparse
import hashlib
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
from secure_agent.fixtures import FixtureServices
from secure_agent.models import FixtureProvider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True, help="new isolated directory; never reused")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.state_root.mkdir(parents=True, mode=0o700)
    spec = importlib.util.spec_from_file_location("runtime_evidence", ROOT / "benchmarks/runtime-security/evidence.py")
    evidence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evidence)
    files = {}
    for directory in ("apps/secure-agent/secure_agent", "demo/fixtures", "skills/secure-research",
                      "skills/secure-report", "skills/secure-delivery"):
        for path in sorted((ROOT / directory).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                files[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    cases = []
    for name, status, messages in (("normal", "verified", 1), ("mcp-attack", "blocked", 0),
                                   ("same-value", "blocked", 0), ("fake-success", "incomplete", 0),
                                   ("conflicting", "conflicting", 1)):
        mode = {"mcp-attack": "attack", "same-value": "same-value"}.get(name, "benign")
        model = FixtureProvider(mode="test", recipient_index=int(name in ("mcp-attack", "same-value")))
        with LocalDaemon(args.binary, args.state_root / name) as daemon, FixtureServices(ROOT / "demo/fixtures", mcp_mode=mode) as fixtures:
            result = SecureApplication(ROOT, daemon, fixtures, model).run(
                "Review the approved repository and deliver its security report to Alice",
                repository="fixture/secure-project", question="Review the supplied code",
                scope=("README.md", "service.py"), effect_mode=name if name in ("fake-success", "conflicting") else "normal")
            if result["task"]["status"] != status or len(result["messages"]) != messages:
                raise ValueError("unexpected application outcome: " + name)
            readbacks = 0
            for action in result["task"]["actions"]:
                if action["effect"] is None:
                    continue
                record = action["effect"]
                actual = daemon.admin.request("/v1/effect-evidence/" + record["evidence"]["effect_evidence_id"])
                if actual != record:
                    raise ValueError("effect readback mismatch")
                readbacks += 1
            env = {**os.environ, "SIQ_AGENT_SECURITY_STATE_DIR": str(daemon.state)}

            def command(argv, env=env):
                return subprocess.run(argv, env=env, text=True, capture_output=True, check=True).stdout

            bundle = evidence.capture(SimpleNamespace(state=daemon.state, binary=daemon.binary, command=command), name)
            _, count = evidence.verify_receipt_bundles([bundle])
            cases.append({"scenario": name, "expected_status": status, "result": result,
                "public_evidence": bundle, "verification": {"receipt_signatures_and_chains": "verified",
                    "receipt_count": count, "effect_server_readbacks": readbacks,
                    "effect_validation": "SIQ readback validates signatures and action binding"}})
    report = {"schema_version": "hackathon-e2e-checkpoint/v1", "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source_sha": subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "working_tree_dirty": bool(subprocess.check_output(["git", "-C", str(ROOT), "status", "--porcelain"])),
        "application_files_sha256": files, "coverage": "actual-agent-tools-and-siq-with-explicit-fixture-model",
        "hardware_evidence": "dgx-spark/local-environment-20260908.json", "stepfun_inference": "unverified", "cases": cases}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(args.out), "cases": len(cases), "provider": "fixture", "status": "passed"}))


if __name__ == "__main__":
    main()
