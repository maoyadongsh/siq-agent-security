#!/usr/bin/env python3
"""Exercise the real upgrade CLI and native approval before/after rollback in a copy."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts/openclaw-checkpoint-compat.py"


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
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    runtime = args.openclaw_root.resolve()
    args.node = args.node.absolute()
    profile = json.loads(
        (
            ROOT / "patches/openclaw/2026.5.12-approval-execution-recheck-v2.json"
        ).read_text()
    )
    source = runtime / profile["target"]
    require(
        digest(source) == profile["before_sha256"],
        "installed source differs from pinned original",
    )
    adapter = ROOT / profile["adapter_source"]
    require(digest(adapter) == profile["adapter_sha256"], "adapter source differs")
    revocation = load("validate-intent-v2-openclaw-approval-revocation")
    ordinary = load("validate-intent-v2-openclaw-approval-gate")
    with tempfile.TemporaryDirectory(prefix="siq-checkpoint-upgrade-native-") as tmp:
        root = Path(tmp)
        copy = root / "runtime"
        backup = root / "backup"
        shutil.copytree(runtime, copy, symlinks=True)
        args.openclaw_root = copy

        def cli(operation):
            result = subprocess.run(
                [
                    sys.executable,
                    str(TOOL),
                    operation,
                    "--openclaw-root",
                    str(copy),
                    "--backup-dir",
                    str(backup),
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            require(result.returncode == 0, f"compat CLI {operation} failed")
            return json.loads(result.stdout)

        statuses = {
            "before": cli("inspect"),
            "apply": cli("apply"),
            "apply_retry": cli("apply"),
        }
        require(
            statuses["before"]["status"] == "stock", "original inspection incorrect"
        )
        require(
            statuses["apply"]["changed"] and not statuses["apply_retry"]["changed"],
            "apply not idempotent",
        )
        require(
            digest(copy / profile["target"]) == profile["after_sha256"],
            "upgrade installed wrong bytes",
        )
        case_root = root / "upgraded-cases"
        case_root.mkdir(mode=0o700)
        harness = revocation.ApprovalHarness(case_root, args)
        print(
            "Upgrade CLI applied; running native approval and revocation cases.",
            flush=True,
        )
        try:
            upgraded = harness.run()
        finally:
            harness.stop()
        statuses.update(
            {
                "restore": cli("restore"),
                "restore_retry": cli("restore"),
                "after": cli("inspect"),
            }
        )
        require(
            statuses["restore"]["changed"] and not statuses["restore_retry"]["changed"],
            "restore not idempotent",
        )
        require(statuses["after"]["status"] == "stock", "restored inspection incorrect")
        require(
            digest(copy / profile["target"]) == profile["before_sha256"],
            "original bytes not restored",
        )
        case_root = root / "restored-case"
        case_root.mkdir(mode=0o700)
        harness = ordinary.ApprovalHarness(case_root, args)
        print(
            "Rollback CLI restored stock bytes; checking unsupported hold in a fresh native process.",
            flush=True,
        )
        try:
            restored = harness.run(
                cases=[
                    {
                        "id": "restored-unsupported",
                        "platform": "allow-once",
                        "local": None,
                    }
                ]
            )
        finally:
            harness.stop()
        case = restored["cases"][0]
        require(
            case["blocked"] and not case["platform_requested"] and not case["executed"],
            "rollback bypassed host capability gate",
        )
        require(digest(source) == profile["before_sha256"], "installed source changed")
        require(
            digest(adapter) == profile["adapter_sha256"], "shipping adapter changed"
        )
        require(
            digest(backup / "original.js") == profile["before_sha256"],
            "backup differs from original",
        )
        result = {
            "schema": "openclaw-checkpoint-upgrade-validation/v1",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "passed": upgraded["passed"] and restored["passed"],
            "installed_source_unchanged": True,
            "runtime_kind": "independent temporary copy; real compat CLI apply/restore",
            "statuses": statuses,
            "patch": profile,
            "sources": {
                str(path.relative_to(ROOT)): digest(path)
                for path in [Path(__file__), TOOL]
            },
            "backup_sha256": digest(backup / "original.js"),
            "native_upgraded": upgraded,
            "native_restored": restored,
            "limitations": [
                "no actual installed runtime or user settings changed",
                "fresh native process after upgrade and rollback; no hot swap or user-session migration proof",
                "disk state is not proof of code loaded in an existing process",
                "POSIX locking; Windows mutations unsupported",
            ],
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "installed_source_unchanged": True}))
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
            f"native upgrade validation failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
