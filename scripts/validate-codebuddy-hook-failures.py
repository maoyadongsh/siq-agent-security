#!/usr/bin/env python3
"""Native CodeBuddy hook bootstrap failure controls; local synthetic fixtures only."""

from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "codebuddy_base", REPO / "scripts/validate-intent-v2-codebuddy.py"
)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def run(h):
    h.build()
    h.start()
    h.command([str(h.binary), "adapter", "install", "codebuddy"])
    h.setup_authority()
    config = h.state / "config.json"
    token = h.state / "token"
    original_config, original_token = config.read_bytes(), token.read_bytes()
    normal = h.native([h.read("normal")])[0]["result"]
    h.assert_call(h.receipts(), "normal", "allow")
    cases = [
        {
            "name": "normal",
            "expected": "execute",
            "executed": "fixture-visible-company-a" in normal,
            "passed": "fixture-visible-company-a" in normal,
        }
    ]
    faults = [
        ("malformed-config", "block", "config"),
        ("partially-invalid-config", "block", "invalid-port"),
        ("short-token-block", "block", "token"),
        ("short-token-warn", "warn", "token"),
        ("short-token-audit", "audit_only", "token"),
        ("state-is-file", "block", "state"),
        ("missing-token", "block", "missing-token"),
        ("token-directory", "block", "token-directory"),
    ]
    try:
        for name, mode, fault in faults:
            if fault == "config":
                config.write_text('{"enforcement_mode":"warn", invalid')
            elif fault == "invalid-port":
                config.write_text(json.dumps({"enforcement_mode": "warn", "port": -1}))
            elif fault in ("missing-token", "token-directory"):
                token.unlink()
                if fault == "token-directory":
                    token.mkdir()
            elif fault == "token":
                cfg = json.loads(original_config)
                cfg["enforcement_mode"] = mode
                config.write_text(json.dumps(cfg))
                token.write_text("synthetic-invalid-token")
            else:
                file = h.root / "not-a-state-dir"
                file.write_text("fixture")
                h.env["SIQ_AGENT_SECURITY_STATE_DIR"] = str(file)
            pending_path = h.state / "pending/decisions.jsonl"
            pending_before = (
                len(pending_path.read_text().splitlines())
                if pending_path.exists()
                else 0
            )
            try:
                output = h.native([h.read(name)])[0]["result"]
                executed = "fixture-visible-company-a" in output
                own = [r for r in h.receipts() if r.get("tool_call_id") == name]
                # No usable HTTP credential/config: no normal decision/observation
                # may be manufactured. Advisory execution has pending evidence only.
                expected_execution = mode != "block"
                pending_after = (
                    len(pending_path.read_text().splitlines())
                    if pending_path.exists()
                    else 0
                )
                pending_added = pending_after - pending_before
                cases.append(
                    {
                        "name": name,
                        "expected": "execute_advisory"
                        if expected_execution
                        else "block",
                        "executed": executed,
                        "fail_closed_reason": "fail-closed" in output,
                        "online_receipts": len(own),
                        "pending_added": pending_added,
                        "passed": executed == expected_execution
                        and not own
                        and pending_added == (0 if fault == "state" else 1)
                        and (expected_execution or "fail-closed" in output),
                    }
                )
            finally:
                config.write_bytes(original_config)
                if token.is_dir():
                    token.rmdir()
                token.write_bytes(original_token)
                h.env["SIQ_AGENT_SECURITY_STATE_DIR"] = str(h.state)
        h.stop(kill=True)
        h.start()
        recovered = h.native([h.read("recovered")])[0]["result"]
        records = h.receipts()
        h.assert_call(records, "recovered", "allow")
        promoted = [
            r for r in records if "pending.fail_closed" in r.get("matched_rule_ids", [])
        ]
        expected_pending = sorted(
            "allow" if mode != "block" else "deny"
            for _, mode, fault in faults
            if fault != "state"
        )
        pending_recovery_verified = (
            sorted(r["action"] for r in promoted) == expected_pending
        )
        h.stop()
        h.start()
        replayed = h.receipts()
        pending_recovery_verified = pending_recovery_verified and [
            r["receipt_id"] for r in replayed
        ] == [r["receipt_id"] for r in records]
        cases.append(
            {
                "name": "recovered",
                "expected": "execute",
                "executed": "fixture-visible-company-a" in recovered,
                "passed": "fixture-visible-company-a" in recovered,
            }
        )
        h.stop()
        verified = json.loads(h.command([str(h.binary), "verify"]))
        return {
            "schema": "codebuddy-native-bootstrap-failures/v1",
            "passed": all(c["passed"] for c in cases)
            and verified["verified"]
            and pending_recovery_verified,
            "pending_recovery_verified": pending_recovery_verified,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "siq_commit": h.command(["git", "rev-parse", "HEAD"], cwd=REPO).strip(),
            "runtime_version": "2.146.0",
            "native_cli_invocations": h.native_count,
            "model_requests": h.model.request_count,
            "cases": cases,
            "receipt_count": len(records),
            "offline_verified": verified["verified"],
            "promoted_pending": [
                {"action": r["action"], "record_type": r.get("record_type")}
                for r in promoted
            ],
            "source_sha256": {
                p: base.digest(REPO / p)
                for p in [
                    "scripts/validate-codebuddy-hook-failures.py",
                    "scripts/validate-intent-v2-codebuddy.py",
                    "scripts/codebuddy-fixture-guard.mjs",
                    "apps/agentshield/cmd/agentshield/main.go",
                    "apps/agentshield/internal/adapters/adapters.go",
                ]
            },
            "runtime_sha256": base.digest(
                h.args.codebuddy_root / "dist/codebuddy-headless.js"
            ),
            "binary_sha256": base.digest(h.binary),
            "limitations": [
                "synthetic operator and loopback model",
                "runtime hook process crash/kill and missing binary are not covered",
                "no redaction or approval proof",
                "no OS isolation",
            ],
        }
    finally:
        config.write_bytes(original_config)
        token.write_bytes(original_token)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codebuddy-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.codebuddy_root = args.codebuddy_root.resolve(strict=True)
    args.node = args.node.resolve(strict=True)
    pkg = json.loads((args.codebuddy_root / "package.json").read_text())
    base.require(
        pkg["name"] == "@tencent-ai/codebuddy-code" and pkg["version"] == "2.146.0",
        "wrong runtime package",
    )
    with tempfile.TemporaryDirectory(prefix="siq-codebuddy-bootstrap-") as directory:
        h = base.Harness(Path(directory), args)
        try:
            report = run(h)
        finally:
            h.stop()
            h.model.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "cases": report["cases"],
                "receipt_count": report["receipt_count"],
            }
        )
    )
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
