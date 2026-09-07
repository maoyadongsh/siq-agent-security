#!/usr/bin/env python3
"""Validate paired approval checkpoint patches in independent temporary copies.

The installed OpenClaw and shipping SIQ adapter remain unchanged. Both ordinary
native approval cases and Grant revocation during platform wait must pass.
"""

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
PATCH_DIR = ROOT / "patches/openclaw"


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


def apply_patch(directory, patch):
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=directory, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=directory, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    runtime = args.openclaw_root.resolve()
    args.node = args.node.absolute()
    metadata_path = PATCH_DIR / "2026.5.12-approval-execution-recheck.json"
    metadata = json.loads(metadata_path.read_text())
    patch = PATCH_DIR / "2026.5.12-approval-execution-recheck.patch"
    adapter_patch = PATCH_DIR / "2026.5.12-approval-recheck-adapter.patch"
    source = runtime / metadata["target"]
    adapter_source = ROOT / metadata["adapter"]["source"]
    package = json.loads((runtime / "package.json").read_text())
    require(
        package["name"] == metadata["package"]
        and package["version"] == metadata["version"],
        "unsupported native package/version",
    )
    require(
        source.is_file()
        and not source.is_symlink()
        and source.resolve().is_relative_to(runtime),
        "patch target must be a regular package file",
    )
    for path, expected in [
        (source, metadata["before_sha256"]),
        (adapter_source, metadata["adapter"]["before_sha256"]),
        (patch, metadata["patch_sha256"]),
        (adapter_patch, metadata["adapter"]["patch_sha256"]),
    ]:
        require(digest(path) == expected, f"pinned source differs: {path.name}")

    class PatchedAdapter:
        def __init__(self, root, options):
            super().__init__(root, options)
            plugin = root / "openclaw/plugins/siq-agent-security"
            self.patched_adapter = plugin / "index.ts"
            require(
                digest(self.patched_adapter) == metadata["adapter"]["before_sha256"],
                "copied adapter differs",
            )
            apply_patch(plugin, adapter_patch)
            require(
                digest(self.patched_adapter) == metadata["adapter"]["after_sha256"],
                "patched adapter differs",
            )

        def run(self):
            result = super().run()
            result["runtime_kind"] = (
                "temporary paired native/adapter checkpoint patches"
            )
            result["executed_adapter_sha256"] = digest(self.patched_adapter)
            # Original harness fingerprints describe baseline inputs. Explicitly
            # distinguish the actually loaded patched adapter from that baseline.
            result["baseline_project_sources"] = result.pop("sources")
            return result

    ordinary = load("validate-intent-v2-openclaw-approval-gate")
    revocation = load("validate-intent-v2-openclaw-approval-revocation")

    class OrdinaryHarness(PatchedAdapter, ordinary.ApprovalHarness):
        pass

    class RevocationHarness(PatchedAdapter, revocation.ApprovalHarness):
        pass

    with tempfile.TemporaryDirectory(prefix="siq-openclaw-recheck-patch-") as tmp:
        root = Path(tmp)
        copy = root / "openclaw"
        shutil.copytree(
            runtime, copy, symlinks=True
        )  # Independent files, no hardlinks.
        copied_source = copy / metadata["target"]
        require(
            digest(copied_source) == metadata["before_sha256"], "copied source differs"
        )
        apply_patch(copy, patch)
        require(
            digest(copied_source) == metadata["after_sha256"], "patched source differs"
        )
        subprocess.run([str(args.node), "--check", str(copied_source)], check=True)
        args.openclaw_root = copy
        results = {}
        for name, cls in [
            ("ordinary", OrdinaryHarness),
            ("revocation", RevocationHarness),
        ]:
            case_root = root / name
            case_root.mkdir(mode=0o700)
            harness = cls(case_root, args)
            print(
                f"Starting native {name} cases with paired temporary patches.",
                flush=True,
            )
            try:
                results[name] = harness.run()
            finally:
                harness.stop()
        require(digest(source) == metadata["before_sha256"], "installed source changed")
        require(
            digest(adapter_source) == metadata["adapter"]["before_sha256"],
            "shipping adapter changed",
        )
        result = {
            "schema": "openclaw-approval-recheck-patch-validation/v1",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "passed": all(item["passed"] for item in results.values()),
            "installed_source_unchanged": True,
            "shipping_adapter_unchanged": True,
            "runtime_kind": "temporary OpenClaw 2026.5.12 and SIQ adapter with paired candidate patches",
            "patch": metadata,
            "runner_sha256": digest(Path(__file__)),
            "validation": results,
            "limitations": [
                "stock runtime and shipping adapter remain affected by the archived revocation gap",
                "new beforeExecute callback is a local candidate extension, not an upstream API",
                "checkpoint is not an atomic execution lease or proof against all concurrent mutations",
                "synthetic tools/operators; no human approval or OS isolation proof",
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
            f"isolated checkpoint validation failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
