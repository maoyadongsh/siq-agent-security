#!/usr/bin/env python3
"""Run the actual unpacked candidate launcher, API task and signed evidence."""

import argparse
import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from package_rc import verify_package

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    package, state = args.package.resolve(), args.state_dir.resolve()
    manifest = verify_package(package)
    if state.exists() or args.out.exists():
        raise ValueError("checkpoint state and report must be new")
    state.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    log_path = state.with_name(state.name + "-private.log")
    opener = build_opener(ProxyHandler({}))
    config = None

    def request(path, body=None, identity=None):
        headers = {"Authorization": "Bearer " + config["token"], "X-SIQ-Demo": "1", "Content-Type": "application/json"}
        if identity:
            headers["Idempotency-Key"] = identity
        with opener.open(Request(config["endpoint"] + path, headers=headers,
                data=None if body is None else json.dumps(body).encode()), timeout=5) as response:
            return json.load(response)

    started = time.monotonic()
    with os.fdopen(os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as log:
        process = subprocess.Popen([sys.executable, "-B", str(package / "source/scripts/hackathon/launch_rc.py"),
            "--state-dir", str(state), "--port", str(port)], stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 30
            while not (state / "service.json").exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("candidate launcher did not become ready; inspect its private log")
                time.sleep(0.1)
            config = json.loads((state / "service.json").read_text())
            health = request("/health")
            identity = request("/hackathon/v1/tasks", {"scenario": "normal",
                "prompt": "Analyze the selected repository files, write a security report and deliver it to Alice."}, uuid4().hex)["id"]
            deadline = time.monotonic() + 240
            while True:
                snapshot = request("/hackathon/v1/tasks/" + identity)
                if snapshot["phase"] in ("finished", "failed"):
                    break
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("candidate task did not finish within checkpoint observation window")
                time.sleep(0.2)
            spec = importlib.util.spec_from_file_location("rc_evidence", ROOT / "benchmarks/runtime-security/evidence.py")
            evidence = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(evidence)
            binary = package / "bin/siq-agent-security-linux-arm64"
            if os.uname().machine in ("x86_64", "amd64"):
                binary = package / "bin/siq-agent-security-linux-amd64"

            def command(argv):
                return subprocess.check_output(argv, env={**os.environ, "SIQ_AGENT_SECURITY_STATE_DIR": str(state / "siq-state")},
                                               text=True)

            bundle = evidence.capture(SimpleNamespace(state=state / "siq-state", binary=binary, command=command), "rc-stepfun")
            actions, count = evidence.verify_receipt_bundles([bundle])
            effects = [a["effect"] for a in snapshot.get("task", {}).get("actions", []) if a["effect"]]
            for effect in effects:
                evidence.verify_effect_envelope(effect, actions)
            verify_package(package)  # launching may not add bytecode, credentials or state to the package
            report = {"schema_version": "hackathon-package-checkpoint/v1", "version": manifest["version"],
                "official_signature": False, "manifest_sha256": hashlib.sha256((package / "candidate-manifest.json").read_bytes()).hexdigest(),
                "health": health, "result": snapshot, "public_evidence": bundle,
                "verified_receipts": count, "verified_effect_envelopes": len(effects),
                "package_unchanged_after_execution": True, "elapsed_ms": (time.monotonic() - started) * 1000,
                "limitations": ["Actual Linux launcher and configured StepFun; controlled source/delivery.",
                                "Local unsigned candidate, not official publisher authentication or native non-Linux validation."]}
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with args.out.open("x") as output:
                output.write(json.dumps(report, indent=2) + "\n")
            print(json.dumps({"status": snapshot.get("task", {}).get("status"), "verified_receipts": count,
                              "verified_effect_envelopes": len(effects), "package_unchanged": True}))
            return 0 if snapshot.get("task", {}).get("status") == "verified" else 1
        finally:
            if process.poll() is None:
                if config is not None:
                    request("/hackathon/v1/shutdown", {})
                else:
                    process.terminate()
                process.wait(timeout=90)


if __name__ == "__main__":
    raise SystemExit(main())
