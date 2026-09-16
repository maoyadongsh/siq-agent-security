#!/usr/bin/env python3
"""Exercise OpenClaw's public Skill install entry against an isolated SIQ policy.

Only local, static Skill fixtures are used. Raw CLI output remains private and
is never included in the JSON report.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "apps/agentshield/internal/admission/testdata/skills"


def run(command: list[str], env: dict[str, str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, timeout=120)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--openclaw", type=Path, required=True)
    parser.add_argument("--private-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    openclaw = args.openclaw.resolve(strict=True)
    root = args.private_root.absolute()
    root.mkdir(parents=True, mode=0o700, exist_ok=False)
    home, workspace, state = (root / name for name in ("home", "workspace", "state"))
    oc = home / ".openclaw"
    for directory in (home, oc, workspace, state):
        directory.mkdir(mode=0o700)
    config_path = oc / "openclaw.json"
    original = json.dumps({"agents": {"defaults": {"workspace": str(workspace)}}})
    config_path.write_text(original)
    env = {
        "HOME": str(home),
        "OPENCLAW_STATE_DIR": str(oc),
        "OPENCLAW_CONFIG_PATH": str(config_path),
        "SIQ_AGENT_SECURITY_STATE_DIR": str(state),
        "PATH": os.environ.get("PATH", ""),
        "TMPDIR": str(root),
        "LANG": "en_US.UTF-8",
    }
    report: dict[str, object] = {"schema": "openclaw-install-policy-native/v1", "checks": {}}
    checks: dict[str, object] = report["checks"]  # type: ignore[assignment]
    try:
        initialized = run([str(binary), "init", "--port", "47620"], env, workspace)
        checks["init"] = initialized.returncode == 0
        if initialized.returncode != 0:
            raise RuntimeError("isolated state initialization failed")
        preview = run([str(binary), "adapter", "preview", "openclaw", "install", "--enable-install-policy"], env, workspace)
        checks["preview"] = preview.returncode == 0 and json.loads(preview.stdout).get("install_policy") is True
        if not checks["preview"]:
            raise RuntimeError("explicit install-policy preview failed")
        installed = run([str(binary), "adapter", "install", "openclaw", "--enable-install-policy"], env, workspace)
        checks["adapter_install"] = installed.returncode == 0
        if installed.returncode != 0:
            raise RuntimeError("isolated adapter install failed")
        config = json.loads(config_path.read_text())
        checks["policy_configured"] = config.get("security", {}).get("installPolicy", {}).get("targets") == ["skill"]
        if not checks["policy_configured"]:
            raise RuntimeError("native policy config missing")
        version = run([str(openclaw), "--version"], env, workspace)
        report["host_version"] = version.stdout.strip() if version.returncode == 0 else "unavailable"
        validated = run([str(openclaw), "config", "validate"], env, workspace)
        checks["host_config_valid"] = validated.returncode == 0
        if validated.returncode != 0:
            raise RuntimeError("OpenClaw rejected isolated config")
        bad = run([str(openclaw), "skills", "install", str(FIXTURES / "malicious/env-webhook"), "--as", "siq-bad-fixture", "--force"], env, workspace)
        private_bad_log = root / "blocked-cli.log"
        private_bad_log.write_text(bad.stdout + "\n" + bad.stderr)
        private_bad_log.chmod(0o600)
        checks["blocked_install_rejected"] = bad.returncode != 0 and "blocked by policy" in (bad.stdout + bad.stderr).lower()
        checks["blocked_target_absent"] = not (workspace / "skills/siq-bad-fixture").exists()
        warn_source = str(FIXTURES / "benign/official-like")
        warn = run([str(openclaw), "skills", "install", warn_source, "--as", "siq-warn-fixture", "--force"], env, workspace)
        checks["warning_needs_acknowledgement"] = warn.returncode != 0 and not (workspace / "skills/siq-warn-fixture").exists()
        acknowledged = run([str(openclaw), "skills", "install", warn_source, "--as", "siq-warn-fixture", "--force", "--acknowledge-install-policy-warning"], env, workspace)
        checks["warning_explicitly_acknowledged"] = acknowledged.returncode == 0 and (workspace / "skills/siq-warn-fixture/SKILL.md").is_file()
        good = run([str(openclaw), "skills", "install", str(FIXTURES / "benign/pure-doc"), "--as", "siq-good-fixture", "--force"], env, workspace)
        checks["allowed_install_accepted"] = good.returncode == 0
        checks["allowed_target_present"] = (workspace / "skills/siq-good-fixture/SKILL.md").is_file()
        report["return_codes"] = {"blocked": bad.returncode, "warn": warn.returncode, "acknowledged": acknowledged.returncode, "allowed": good.returncode}
    finally:
        removed = run([str(binary), "adapter", "uninstall", "openclaw"], env, workspace)
        checks["adapter_uninstall"] = removed.returncode == 0
        checks["config_restored"] = config_path.read_text() == original
    report["passed"] = all(value is True for value in checks.values())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "checks": checks}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"native install-policy smoke failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
