#!/usr/bin/env python3
"""Measure unchanged historical OpenClaw/CodeBuddy adapters against today's daemon.

Exit 1 and passed=false mean full observation compatibility is not achieved,
even when authorization and rejection of ambiguous observations work correctly.
All execution/configuration uses temporary fixtures; no real model or user data.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = "0caacd3bd678051f80efb2737ea26a0c76f96a97"


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cb = load("legacy_cb_base", "validate-intent-v2-codebuddy.py")
oc = load("legacy_oc_base", "validate-intent-v2-openclaw.py")
require = cb.require


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install_legacy(h, platform):
    if platform == "openclaw":
        body = subprocess.check_output(
            ["git", "show", LEGACY + ":adapters/runtime/openclaw-agentshield/index.ts"],
            cwd=ROOT,
        )
        target = h.root / "openclaw/plugins/siq-agent-security/index.ts"
        target.write_bytes(body)
        # Old code ignores OPENCLAW_STATE_DIR when reading its config. Redirect
        # only those two config reads to fixture bytes, without changing HOME,
        # source, hooks, request payloads or authorization/observation behavior.
        preload = h.root / "legacy-config-fixture.cjs"
        preload.write_text("""const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { syncBuiltinESMExports } = require("node:module");
const read = fs.readFileSync;
const names = ["siq-agent-security.json", "agentshield.json"]
  .map(n => path.join(os.homedir(), ".openclaw", n));
fs.readFileSync = function(file, ...args) {
  if (names.includes(String(file))) {
    const bytes = JSON.stringify({timeoutMs: 1000,
      tokenPath: path.join(process.env.SIQ_AGENT_SECURITY_STATE_DIR, "token")});
    return args[0] ? bytes : Buffer.from(bytes);
  }
  return read.call(this, file, ...args);
};
syncBuiltinESMExports();
""")
        h.env["NODE_OPTIONS"] = "--require=" + str(preload)
        return {"index.ts": digest(target)}

    # Build the whole historical stdlib module, not an imitation of old payloads.
    archive = subprocess.check_output(
        ["git", "archive", LEGACY, "apps/agentshield"], cwd=ROOT
    )
    checkout = h.root / "legacy-source"
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        for member in bundle.getmembers():
            path = Path(member.name)
            require(not path.is_absolute() and ".." not in path.parts, "unsafe archive")
            require(member.isdir() or member.isfile(), "unsupported archive member")
            if member.isfile():
                dest = checkout / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(bundle.extractfile(member).read())
    old_binary = h.root / "legacy-siq-agent-security"
    h.command(
        ["go", "build", "-trimpath", "-o", str(old_binary), "./cmd/agentshield"],
        cwd=checkout / "apps/agentshield",
        timeout=180,
    )
    h.command([str(h.binary), "adapter", "install", "codebuddy"])
    settings = h.config_dir / "settings.json"
    config = json.loads(settings.read_text())
    changed = 0
    for groups in config["hooks"].values():
        for group in groups:
            for hook in group["hooks"]:
                command = hook.get("command", "")
                if str(h.binary) in command:
                    hook["command"] = command.replace(str(h.binary), str(old_binary))
                    changed += 1
    require(changed == 2, "expected only pre/post fixture commands")
    settings.write_text(json.dumps(config))
    return {
        "archive_sha256": hashlib.sha256(archive).hexdigest(),
        "binary_sha256": digest(old_binary),
        "adapters.go": digest(
            checkout / "apps/agentshield/internal/adapters/adapters.go"
        ),
    }


def exercise(h, platform):
    h.build()
    h.config("optional")
    h.start()
    historical = install_legacy(h, platform)
    cases = []

    def call(label, session, action, binding, observations, company="company-a"):
        before = len(h.receipts())
        request = h.read(label, company)
        if platform == "codebuddy":
            output = h.native([request], session)[0]["result"]
        else:
            request["session_id"] = session
            output = h.native([request])[0]["result"]
        records = h.receipts()[before:]
        decisions = [r for r in records if r.get("record_type") == "decision"]
        observed = [r for r in records if r.get("record_type") == "observation"]
        require(len(decisions) == 1, label + ": decision missing")
        decision = decisions[0]
        require(decision["action"] == action, label + ": wrong authorization")
        require(decision["intent_binding"] == binding, label + ": wrong binding")
        executed = "fixture-visible-" + company in output
        require(executed == (action == "allow"), label + ": native execution mismatch")
        require(len(observed) == observations, label + ": unexpected observation count")
        if observed:
            require(
                observed[0]["action_id"] == decision["action_id"]
                and observed[0]["decision_receipt_id"] == decision["receipt_id"],
                label + ": observation detached from decision",
            )
        cases.append(
            {
                "case": label,
                "action": action,
                "intent_binding": binding,
                "reason_code": decision["reason_code"],
                "native_executed": executed,
                "observations": len(observed),
                "decision_tool_call_id_present": bool(decision.get("tool_call_id")),
            }
        )

    call("before-grant", "legacy-before", "deny", "unbound", 0)
    h.setup_authority()
    call(
        "optional-first",
        "legacy-optional",
        "allow",
        "unbound",
        0,
    )
    call("optional-repeat", "legacy-optional", "allow", "unbound", 0)
    call(
        "optional-other-resource",
        "legacy-optional",
        "allow",
        "unbound",
        0,
        "company-b",
    )
    call("bound-denial", cb.SESSION, "deny", "bound", 0, "company-b")
    h.stop(kill=True)
    h.config("required")
    h.start()
    call("required-missing", "legacy-required", "deny", "unbound", 0)
    h.stop(kill=True)
    h.config("optional")
    h.start()
    call("optional-repeat-after-restart", "legacy-optional", "allow", "unbound", 0)
    legacy_cases = len(cases)
    # Upgrade only the adapter entry; retain the exact daemon state, bindings,
    # historical decisions and platform conversation/configuration.
    if platform == "openclaw":
        destination = h.root / "openclaw/plugins/siq-agent-security/index.ts"
        destination.write_bytes(
            (ROOT / "adapters/runtime/openclaw-agentshield/index.ts").read_bytes()
        )
        upgraded_hash = digest(destination)
    else:
        settings = h.config_dir / "settings.json"
        config = json.loads(settings.read_text())
        changed = 0
        for groups in config["hooks"].values():
            for group in groups:
                for hook in group["hooks"]:
                    old = str(h.root / "legacy-siq-agent-security")
                    if old in hook.get("command", ""):
                        hook["command"] = hook["command"].replace(old, str(h.binary))
                        changed += 1
        require(changed == 2, "upgrade did not replace both legacy hooks")
        require(
            config["env"]["SIQ_FIXTURE_USER_SETTING"] == "preserve",
            "upgrade lost user fixture setting",
        )
        settings.write_text(json.dumps(config))
        upgraded_hash = digest(h.binary)
    call("upgraded-first", "legacy-optional", "allow", "unbound", 1)
    call("upgraded-repeat", "legacy-optional", "allow", "unbound", 1)
    call("upgraded-bound-denial", cb.SESSION, "deny", "bound", 0, "company-b")
    h.stop(kill=True)
    h.start()
    call("upgraded-after-restart", "legacy-optional", "allow", "unbound", 1)
    records = h.receipts()
    h.stop()
    verified = json.loads(h.command([str(h.binary), "verify"]))
    require(verified["verified"], "offline chain validation failed")
    return {
        "platform": platform,
        "legacy_commit": LEGACY,
        "historical_artifacts": historical,
        "current_binary_sha256": digest(h.binary),
        "authorization_checks_passed": True,
        "offline_verified": True,
        "full_observation_compatibility": False,
        "upgrade_recovery_passed": True,
        "upgraded_artifact_sha256": upgraded_hash,
        "legacy_case_count": legacy_cases,
        "cases": cases,
        "receipt_count": len(records),
        "runtime": (
            {
                "version": json.loads(
                    (h.args.codebuddy_root / "package.json").read_text()
                )["version"],
                "headless_sha256": digest(
                    h.args.codebuddy_root / "dist/codebuddy-headless.js"
                ),
                "native_cli_invocations": h.native_count,
                "model_requests": h.model.request_count,
            }
            if platform == "codebuddy"
            else h.native_metadata
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=["openclaw", "codebuddy"], required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.codebuddy_root = args.openclaw_root = args.runtime_root.resolve(strict=True)
    args.node = args.node.resolve(strict=True)
    if args.platform == "codebuddy":
        pkg = json.loads((args.codebuddy_root / "package.json").read_text())
        require(
            pkg["name"] == "@tencent-ai/codebuddy-code" and pkg["version"] == "2.146.0",
            "unvalidated native runtime",
        )
    with tempfile.TemporaryDirectory(prefix="siq-legacy-platform-") as tmp:
        cls = cb.Harness if args.platform == "codebuddy" else oc.OpenClawHarness
        h = cls(Path(tmp), args)
        try:
            report = exercise(h, args.platform)
        finally:
            h.stop()
            if args.platform == "codebuddy":
                h.model.close()
    report.update(
        {
            "schema": "intent-v2-legacy-platform-validation/v1",
            "passed": False,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "siq_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "source_sha256": {
                name: digest(ROOT / name)
                for name in (
                    "scripts/validate-intent-v2-legacy-platforms.py",
                    "scripts/validate-intent-v2-hermes.py",
                    "scripts/validate-intent-v2-codebuddy.py",
                    "scripts/validate-intent-v2-openclaw.py",
                    "scripts/openclaw-native-worker.mjs",
                    "scripts/codebuddy-fixture-guard.mjs",
                )
            },
            "limitations": [
                "fixed historical source, not all released artifacts",
                "OpenClaw uses native tool components and harness-driven after relay",
                "CodeBuddy uses complete native CLI with synthetic loopback model",
                "no user configuration, human approval or OS isolation validation",
                "missing/ambiguous observations remain rejected; no matching by guess",
            ],
        }
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "platform",
                    "passed",
                    "authorization_checks_passed",
                    "receipt_count",
                )
            }
        )
    )
    return 1  # Full legacy compatibility is intentionally reported as unachieved.


if __name__ == "__main__":
    raise SystemExit(main())
