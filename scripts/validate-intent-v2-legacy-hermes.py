#!/usr/bin/env python3
"""Run the native integration fixture with an unchanged historical Hermes adapter."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location(
    "native_fixture", ROOT / "scripts/validate-intent-v2-hermes.py"
)
fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture)


class LegacyHermes(fixture.Harness):
    def __init__(self, root, args):
        super().__init__(root, args)
        self.revision = self.command(
            [
                "git",
                "rev-parse",
                "--verify",
                "--end-of-options",
                args.adapter_ref + "^{commit}",
            ],
            cwd=ROOT,
        ).strip()
        self.legacy_hashes = {}
        for name in ("__init__.py", "plugin.yaml"):
            body = self.command(
                [
                    "git",
                    "show",
                    self.revision + ":adapters/runtime/hermes-agentshield/" + name,
                ],
                cwd=ROOT,
            )
            destination = root / "hermes/plugins/siq-agent-security" / name
            destination.write_text(body)
            self.legacy_hashes[name] = hashlib.sha256(
                destination.read_bytes()
            ).hexdigest()

    def runtime_evidence(self):
        return {
            **super().runtime_evidence(),
            "adapter_sha256": self.legacy_hashes["__init__.py"],
            "legacy_adapter_commit": self.revision,
            "legacy_adapter_files": self.legacy_hashes,
            "legacy_harness_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-root", type=Path, required=True)
    parser.add_argument("--hermes-python", type=Path)
    parser.add_argument("--adapter-ref", default="0360731f842e73bc5ec8cbdbb298075d43776c88")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.hermes_root = args.hermes_root.resolve()
    args.hermes_python = args.hermes_python or args.hermes_root / "venv/bin/python"
    # This is a compatibility run, not a performance baseline.
    args.load_samples, args.concurrency = 1, 1
    with tempfile.TemporaryDirectory(prefix="siq-legacy-hermes-") as tmp:
        harness = LegacyHermes(Path(tmp), args)
        try:
            report = harness.run()
        finally:
            harness.stop()
    report["schema"] = "intent-v2-legacy-hermes-validation/v1"
    report["scope"] = (
        "unchanged historical Hermes adapter loaded by installed native dispatcher against current Go daemon"
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "legacy_adapter_commit": report["legacy_adapter_commit"],
                "checks": report["checks"],
            }
        ),
        flush=True,
    )


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
            f"legacy native validation failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)
