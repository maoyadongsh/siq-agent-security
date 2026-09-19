#!/usr/bin/env python3
"""Validate the shipping adapter against stock and checkpoint-capable OpenClaw.

Only temporary state and an independent patched runtime copy are written.
The stock runtime is also exercised to prove unsupported holds fail closed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH_DIR = ROOT / "patches/openclaw"
PATCH_PROFILES = {
    "2026.5.12": "2026.5.12-approval-execution-recheck-v2",
    "2026.9.4": "2026.9.4-approval-execution-recheck-v1",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--binary", type=Path, help="use a fixed SIQ candidate instead of building the worktree")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    runtime = args.openclaw_root.resolve()
    args.node = args.node.absolute()
    if args.binary:
        args.binary = args.binary.resolve(strict=True)
        require(args.binary.is_file(), "SIQ candidate must be a regular file")
    package = json.loads((runtime / "package.json").read_text())
    profile = PATCH_PROFILES.get(package.get("version"))
    require(package.get("name") == "openclaw" and profile is not None,
            "unsupported native package/version")
    metadata = json.loads((PATCH_DIR / (profile + ".json")).read_text())
    patch = PATCH_DIR / (profile + ".patch")
    source = runtime / metadata["target"]
    adapter = ROOT / metadata["adapter_source"]
    embedded = ROOT / "apps/agentshield/internal/adapterinstall/assets/openclaw/index.ts"
    require(
        package["name"] == metadata["package"] and package["version"] == metadata["version"],
        "unsupported native package/version",
    )
    require(
        source.is_file() and not source.is_symlink() and source.resolve().is_relative_to(runtime),
        "native patch target must be a regular package file",
    )
    for path, expected in [
        (source, metadata["before_sha256"]),
        (adapter, metadata["adapter_sha256"]),
        (embedded, metadata["adapter_sha256"]),
        (patch, metadata["patch_sha256"]),
    ]:
        require(digest(path) == expected, f"pinned source differs: {path.name}")
    ordinary = load("validate-intent-v2-openclaw-approval-gate")
    revocation = load("validate-intent-v2-openclaw-approval-revocation")
    faults = load("validate-intent-v2-openclaw-checkpoint-faults")

    class StockHarness(ordinary.ApprovalHarness):
        def run(self):
            result = super().run(cases=[{"id": "unsupported-host", "platform": "allow-once", "local": None}])
            case = result["cases"][0]
            require(
                case["blocked"] and not case["platform_requested"],
                "stock host entered approval",
            )
            require(
                not case["executed"] and case["observation_count"] == 0,
                "stock host executed hold",
            )
            return result

    with tempfile.TemporaryDirectory(prefix="siq-openclaw-checkpoint-integration-") as tmp:
        root = Path(tmp)
        results = {}

        def run_group(name, cls, native_root):
            args.openclaw_root = native_root
            case_root = root / name
            case_root.mkdir(mode=0o700)
            harness = cls(case_root, args)
            installed_adapter = case_root / "openclaw/plugins/siq-agent-security/index.ts"
            require(
                digest(installed_adapter) == metadata["adapter_sha256"],
                "loaded adapter differs",
            )
            print(f"Starting native integration: {name}.", flush=True)
            try:
                result = harness.run()
                result["runtime_kind"] = "stock" if native_root == runtime else "temporary checkpoint copy"
                result["executed_adapter_sha256"] = digest(installed_adapter)
                results[name] = result
            finally:
                harness.stop()

        run_group("stock_unsupported", StockHarness, runtime)
        copy = root / "openclaw"
        shutil.copytree(runtime, copy, symlinks=True)
        copied_source = copy / metadata["target"]
        require(digest(copied_source) == metadata["before_sha256"], "copied source differs")
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=copy, check=True)
        subprocess.run(["git", "apply", str(patch)], cwd=copy, check=True)
        require(digest(copied_source) == metadata["after_sha256"], "patched source differs")
        subprocess.run([str(args.node), "--check", str(copied_source)], check=True)
        for name, cls in [
            ("ordinary", ordinary.ApprovalHarness),
            ("revocation", revocation.ApprovalHarness),
            ("faults", faults.ApprovalHarness),
        ]:
            run_group(name, cls, copy)
        binary_sha256 = results["ordinary"]["siq_binary_sha256"]
        require(
            all(item["siq_binary_sha256"] == binary_sha256 for item in results.values()),
            "validation groups used different SIQ binaries",
        )
        if args.binary:
            require(binary_sha256 == digest(args.binary), "validation did not use the fixed SIQ candidate")
        require(
            all(item["receipt_chain_verified"] for item in results.values()),
            "a validation group did not verify its receipt chain",
        )
        require(digest(source) == metadata["before_sha256"], "installed runtime changed")
        require(
            digest(adapter) == metadata["adapter_sha256"],
            "shipping adapter changed during test",
        )
        result = {
            "schema": "openclaw-approval-integration-validation/v2",
            "recorded_at": datetime.now(UTC).isoformat(),
            "passed": all(item["passed"] for item in results.values()),
            "binary_sha256": binary_sha256,
            "runtime": {"platform": "openclaw", "os": "linux"},
            "checks": [
                "stock_host_refuses_unsupported_hold",
                "shipping_adapter_matches_embedded_source",
                "approved_execution_has_one_reservation_and_observation",
                "denial_missing_approval_and_offline_paths_fail_closed",
                "revoked_authority_blocks_after_platform_approval",
                "checkpoint_faults_and_parameter_changes_fail_closed",
                "reservation_response_loss_stays_uncertain",
                "all_receipt_chains_verified",
                "installed_runtime_remains_unchanged",
            ],
            "installed_source_unchanged": True,
            "shipping_adapter_used_without_patch": True,
            "runner_sha256": digest(Path(__file__)),
            "patch": metadata,
            "patch_profile": profile,
            "validation": results,
            "limitations": [
                "stock runtime cannot complete holds with this adapter; this is an explicit compatibility boundary",
                "context capability is trusted host metadata, not a cryptographic proof "
                "against malicious same-process plugins",
                "checkpoint-v2 host remains an isolated local candidate, not an upstream API or installed upgrade",
                "post-check races, real-world effects and human approval are not proven",
            ],
        }
    args.out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        output.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "cases": sum(len(x["cases"]) for x in results.values()),
            }
        )
    )
    return 0 if result["passed"] else 1


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
        print(
            f"native approval integration failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
