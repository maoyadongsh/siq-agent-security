#!/usr/bin/env python3
"""Apply the pinned OpenClaw compatibility patch only to a temporary copy.

The installed runtime is read-only. The full native idle-reset fixture remains
the acceptance gate; a patched version is never reported as stock OpenClaw.
"""

from __future__ import annotations

import argparse
import hashlib
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    runtime = args.openclaw_root.resolve()
    metadata_path = PATCH_DIR / "2026.5.12-idle-transcript-reset.json"
    metadata = json.loads(metadata_path.read_text())
    patch = PATCH_DIR / "2026.5.12-idle-transcript-reset.patch"
    target = runtime / metadata["target"]
    package = json.loads((runtime / "package.json").read_text())
    require(
        package["name"] == metadata["package"]
        and package["version"] == metadata["version"],
        "unsupported runtime version",
    )
    require(
        not target.is_symlink() and target.resolve().is_relative_to(runtime),
        "patch target must be a regular package file",
    )
    require(
        digest(target) == metadata["before_sha256"],
        "installed target differs from pinned source",
    )
    require(digest(patch) == metadata["patch_sha256"], "patch checksum mismatch")
    with tempfile.TemporaryDirectory(prefix="siq-openclaw-patch-") as tmp:
        copy = Path(tmp) / "openclaw"
        # Full independent files, not hardlinks: runtime writes cannot change
        # the installed package. Preserve package-relative dependency symlinks.
        shutil.copytree(runtime, copy, symlinks=True)
        copied_target = copy / metadata["target"]
        require(
            digest(copied_target) == metadata["before_sha256"],
            "copied target checksum mismatch",
        )
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=copy, check=True)
        subprocess.run(["git", "apply", str(patch)], cwd=copy, check=True)
        require(
            digest(copied_target) == metadata["after_sha256"],
            "patched target checksum mismatch",
        )
        subprocess.run(
            [str(args.node.absolute()), "--check", str(copied_target)], check=True
        )
        evidence = Path(tmp) / "validation.json"
        print(
            "Pinned patch applied to an independent temporary runtime; starting native idle-reset validation.",
            flush=True,
        )
        process = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/validate-intent-v2-openclaw-reset.py"),
                "--openclaw-root",
                str(copy),
                "--node",
                str(args.node.absolute()),
                "--out",
                str(evidence),
            ],
            check=False,
            timeout=600,
        )
        require(evidence.is_file(), "native validation did not produce evidence")
        validation = json.loads(evidence.read_text())
        require(
            digest(target) == metadata["before_sha256"],
            "installed source changed during fixture",
        )
        result = {
            "schema": "openclaw-idle-patch-validation/v1",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "passed": process.returncode == 0 and validation["passed"],
            "installed_source_unchanged": True,
            "runtime_kind": "temporary OpenClaw 2026.5.12 copy with SIQ compatibility patch",
            "patch": metadata,
            "runner_sha256": digest(Path(__file__)),
            "validation": validation,
            "limitations": [
                "installed runtime not updated; stock failure evidence remains valid",
                "no gateway manual-reset, approval or channel acceptance",
                "not an upstream release or upstream-approved fix",
            ],
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps({"passed": result["passed"], "installed_source_unchanged": True}),
        flush=True,
    )
    if not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except (
        RuntimeError,
        OSError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
    ) as exc:
        print(
            f"isolated patch validation failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
