#!/usr/bin/env python3
"""Exercise native approval checkpoint callback faults and final-parameter binding.

Uses temporary state, a synthetic operator and a marker-writing tool; never
executes the command string, calls models, or configures a real installation.
Security failures are reported as passed=false and exit 1, not a success gate.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location(
    "openclaw_fixture", ROOT / "scripts/validate-intent-v2-openclaw.py"
)
native = importlib.util.module_from_spec(loader)
loader.loader.exec_module(native)
fixture = native.fixture
require = fixture.require


class ApprovalHarness(native.OpenClawHarness):
    def setup_grant(self):
        path = (
            ROOT
            / "apps/agentshield/internal/admission/testdata/skills/benign/official-like"
        )
        admitted = self.api("/v1/admit", {"path": str(path)})["admission"]
        result = self.api(
            "/v1/grants",
            {
                "admission_id": admitted["admission_id"],
                "platform": "openclaw",
                "subject_id": fixture.AGENT,
            },
        )
        route = "/v1/grants/" + result["grant"]["grant_id"]

        def action(name, **body):
            nonlocal result
            result = self.api(
                route + "/" + name,
                {
                    "expected_revision": result["state_revision"],
                    "actor_id": "synthetic-fixture-operator",
                    **body,
                },
            )
            return result

        action("patch-desired", models=["fixture-model"])
        challenge = action("challenge")["challenge"]
        action(
            "approve", challenge_id=challenge["challenge_id"], nonce=challenge["nonce"]
        )
        action("deploy")
        require(
            "exec" in result["grant"]["openclaw_tool_policy"]["require_approval"],
            "exec hold gate missing",
        )

    def wait_file(self, path, process, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path.is_file():
                return json.loads(path.read_text())
            error = path.parent / "error.json"
            if error.is_file():
                failure = json.loads(error.read_text())
                raise RuntimeError(
                    f"native worker failed at {failure['stage']}: {failure['category']}"
                )
            require(process.poll() is None, "native worker exited before result")
            time.sleep(0.025)
        raise RuntimeError("native worker result timeout")

    def run(self):
        self.config("optional")
        self.build()
        self.start()
        self.setup_grant()
        control = self.root / "control"
        control.mkdir(mode=0o700)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        oc = self.root / "openclaw"
        config_path = oc / "openclaw.json"
        config = json.loads(config_path.read_text())
        config.update(
            {
                "gateway": {
                    "mode": "local",
                    "port": port,
                    "bind": "loopback",
                    "auth": {"mode": "token", "token": secrets.token_hex(32)},
                    "controlUi": {"enabled": False},
                },
                "browser": {"enabled": False},
                "canvasHost": {"enabled": False},
                "discovery": {"mdns": {"mode": "off"}},
                "cron": {"enabled": False},
                "update": {"checkOnStart": False},
                "logging": {"file": str(oc / "gateway.log"), "consoleLevel": "silent"},
                "agents": {
                    "defaults": {"workspace": str(self.workspace)},
                    "list": [{"id": fixture.AGENT}],
                },
            }
        )
        config_path.write_text(json.dumps(config))
        (oc / "siq-agent-security.json").write_text(
            json.dumps({"timeoutMs": 1000, "holdWaitMs": 1500})
        )
        self.env.pop("OPENCLAW_DISABLE_BUNDLED_PLUGINS", None)
        self.env.update(
            {
                "OPENCLAW_HOME": str(self.root / "native-home"),
                "PI_CODING_AGENT_DIR": str(self.root / "pi"),
                "OPENCLAW_SKIP_CHANNELS": "1",
                "OPENCLAW_SKIP_CRON": "1",
                "OPENCLAW_NO_RESPAWN": "1",
                "NODE_DISABLE_COMPILE_CACHE": "1",
                "SIQ_FIXTURE_ENDPOINTS": json.dumps(
                    [
                        self.endpoint.removeprefix("http://"),
                        f"127.0.0.1:{port}",
                        f"localhost:{port}",
                    ]
                ),
            }
        )
        cases = [
            {"id": "normal", "platform": "allow-once", "local": True},
            *[
                {
                    "id": "checkpoint-" + fault,
                    "fault": fault,
                    "platform": "allow-once",
                    "local": True,
                }
                for fault in (
                    "throw",
                    "reject",
                    "undefined",
                    "truthy",
                    "timeout",
                    "cancel",
                    "params-changed",
                )
            ],
            {
                "id": "checkpoint-offline",
                "platform": "allow-once",
                "local": True,
                "disconnect": True,
            },
        ]
        spec = control / "spec.json"
        spec.write_text(
            json.dumps(
                {
                    "openclaw_root": str(self.args.openclaw_root),
                    "port": port,
                    "control_dir": str(control),
                    "workspace": str(self.workspace),
                    "agent_id": fixture.AGENT,
                    "session_id": fixture.SESSION,
                    "cases": cases,
                }
            )
        )
        outcomes = []
        command = [
            str(self.args.node),
            "--import",
            str(ROOT / "scripts/openclaw-fixture-guard.mjs"),
            str(ROOT / "scripts/openclaw-approval-checkpoint-fault-worker.mjs"),
            str(spec),
        ]
        with tempfile.TemporaryFile(mode="w+t") as log:
            process = subprocess.Popen(
                command, cwd=self.workspace, env=self.env, stdout=log, stderr=log
            )
            try:
                for case in cases:
                    call_id = case["id"]
                    deadline = time.monotonic() + 90
                    while True:
                        require(
                            process.poll() is None, "native worker exited before hold"
                        )
                        current = [
                            r
                            for r in self.receipts()
                            if r.get("tool_call_id") == call_id
                            and r.get("record_type") == "decision"
                        ]
                        if current:
                            break
                        require(time.monotonic() < deadline, "native hold timeout")
                        time.sleep(0.025)
                    decisions = [
                        r
                        for r in self.receipts()
                        if r.get("tool_call_id") == call_id
                        and r.get("record_type") == "decision"
                    ]
                    require(
                        len(decisions) == 1 and decisions[0]["action"] == "hold",
                        "native pre did not produce unique hold",
                    )
                    decision = decisions[0]
                    require(
                        decision["intent_binding"] == "unbound",
                        "fixture must test optional unbound holds",
                    )
                    require(
                        not (control / f"{call_id}.executed.json").exists(),
                        "tool ran before any platform resolution",
                    )
                    if case["local"] is not None:
                        self.api(
                            "/v1/hold/" + decision["receipt_id"],
                            {
                                "approve": case["local"],
                                "actor_id": "synthetic-fixture-operator",
                            },
                        )
                    if case["local"] is True:
                        self.wait_file(control / f"{call_id}.request.json", process)
                        if case.get("disconnect"):
                            self.stop(kill=True)
                        choice = control / f"{call_id}.choice.json"
                        temporary = choice.with_suffix(".tmp")
                        temporary.write_text(json.dumps({"decision": case["platform"]}))
                        temporary.replace(choice)
                    result = self.wait_file(control / f"{call_id}.done.json", process)
                    if case.get("disconnect"):
                        self.start()
                    require(
                        result["platform_requested"] == (case["local"] is True),
                        "platform approval order violated",
                    )
                    observations = [
                        r
                        for r in self.receipts()
                        if r.get("tool_call_id") == call_id
                        and r.get("record_type") == "observation"
                    ]
                    expected = case["id"] == "normal"
                    require(
                        len(observations) == int(result["executed"]),
                        "observation authorization invariant failed",
                    )
                    if observations:
                        require(
                            observations[0]["decision_receipt_id"]
                            == decision["receipt_id"]
                            and observations[0]["action_id"] == decision["action_id"],
                            "observation correlation lost",
                        )
                    outcomes.append(
                        {
                            **result,
                            "local_approval": case["local"],
                            "expected_execution": expected,
                            "observation_count": len(observations),
                            "execution_gate_passed": result["executed"] == expected,
                        }
                    )
                    print(
                        f"{call_id}: executed={result['executed']} observation_count={len(observations)}",
                        flush=True,
                    )
                runtime = self.wait_file(control / "result.json", process)
                require(
                    process.wait(timeout=30) == 0, "native worker did not close cleanly"
                )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
        records = self.receipts()
        self.stop()
        verified = json.loads(self.command([str(self.binary), "verify"]))
        require(verified["verified"], "offline receipt verification failed")
        sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        return {
            "schema": "intent-v2-openclaw-approval-checkpoint-fault-validation/v1",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "passed": all(item["execution_gate_passed"] for item in outcomes),
            "observation_identity_checks_passed": True,
            "configured_local_wait_ms": 1500,
            "daemon_kill_restarts": 1,
            "siq_commit": self.command(["git", "rev-parse", "HEAD"], cwd=ROOT).strip(),
            "siq_dirty": bool(
                self.command(["git", "status", "--porcelain"], cwd=ROOT).strip()
            ),
            "siq_binary_sha256": sha(self.binary),
            "cases": outcomes,
            "receipt_count": len(records),
            "receipt_chain_verified": True,
            "openclaw_runtime": runtime,
            "node_version": self.command([str(self.args.node), "--version"]).strip(),
            "sources": {
                str(path.relative_to(ROOT)): sha(path)
                for path in [
                    Path(__file__),
                    ROOT / "scripts/openclaw-approval-checkpoint-fault-worker.mjs",
                    ROOT / "scripts/openclaw-fixture-guard.mjs",
                    ROOT / "scripts/validate-intent-v2-openclaw.py",
                    ROOT / "scripts/validate-intent-v2-hermes.py",
                    ROOT / "adapters/runtime/openclaw-agentshield/index.ts",
                    ROOT / "apps/agentshield/internal/receipt/hold_status.go",
                    ROOT / "apps/agentshield/internal/receipt/action_state.go",
                    ROOT / "apps/agentshield/internal/receipt/engine.go",
                    ROOT / "apps/agentshield/internal/server/hold_status.go",
                    ROOT / "apps/agentshield/internal/server/server.go",
                    ROOT / "apps/agentshield/internal/server/authz.go",
                ]
            },
            "limitations": [
                "synthetic tool executor and operator; no model or human approval proof",
                "native gateway WebSocket, approval manager and before wrapper; after relay invoked by harness",
                "optional unbound exec; required bound opaque shell remains denied",
                "fault injection wraps the real SIQ hook callback; params-change injection uses native hook result merging",
                "test IO guard is not OS isolation; installed runtime and real settings unchanged",
            ],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.openclaw_root = args.openclaw_root.resolve()
    args.node = args.node.absolute()
    with tempfile.TemporaryDirectory(prefix="siq-openclaw-approval-") as temporary:
        harness = ApprovalHarness(Path(temporary), args)
        try:
            report = harness.run()
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {"passed": report["passed"], "receipt_count": report["receipt_count"]}
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (
        RuntimeError,
        OSError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"native approval validation failed: {exc}", file=sys.stderr)
        sys.exit(1)
