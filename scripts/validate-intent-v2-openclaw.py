#!/usr/bin/env python3
"""Native OpenClaw tool/HTTP verification in temporary, synthetic state only."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
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


class OpenClawHarness(fixture.Harness):
    platform = "openclaw"
    read_tool = "read"
    write_tool = "write"

    def __init__(self, root, args):
        super().__init__(root, args)
        self.native_metadata = None
        oc = root / "openclaw"
        plugin = oc / "plugins/siq-agent-security"
        plugin.mkdir(parents=True)
        for name in ("index.ts", "package.json", "openclaw.plugin.json"):
            shutil.copyfile(
                ROOT / "adapters/runtime/openclaw-agentshield" / name, plugin / name
            )
        self.env.update(
            {
                "OPENCLAW_STATE_DIR": str(oc),
                "OPENCLAW_CONFIG_PATH": str(oc / "openclaw.json"),
                "OPENCLAW_DISABLE_BUNDLED_PLUGINS": "1",
            }
        )
        config = {
            "plugins": {
                "enabled": True,
                "allow": ["siq-agent-security"],
                "load": {"paths": [str(plugin)]},
                "entries": {"siq-agent-security": {"enabled": True}},
                "slots": {"memory": "none"},
            }
        }
        (oc / "openclaw.json").write_text(json.dumps(config))
        (oc / "siq-agent-security.json").write_text(json.dumps({"timeoutMs": 1000}))

    def native(self, calls):
        spec = self.root / "openclaw-worker-input.json"
        result = self.root / "openclaw-worker-result.json"
        result.unlink(missing_ok=True)
        spec.write_text(
            json.dumps(
                {
                    "openclaw_root": str(self.args.openclaw_root),
                    "workspace": str(self.workspace),
                    "calls": calls,
                    "session_id": fixture.SESSION,
                    "agent_id": fixture.AGENT,
                    "result_path": str(result),
                }
            )
        )
        self.command(
            [
                str(self.args.node),
                str(ROOT / "scripts/openclaw-native-worker.mjs"),
                str(spec),
            ]
        )
        payload = json.loads(result.read_text())
        self.native_metadata = {k: v for k, v in payload.items() if k != "outputs"}
        return payload["outputs"]

    def runtime_evidence(self):
        return {
            "openclaw_runtime": self.native_metadata,
            "node_version": self.command([str(self.args.node), "--version"]).strip(),
            "adapter_sha256": hashlib.sha256(
                (ROOT / "adapters/runtime/openclaw-agentshield/index.ts").read_bytes()
            ).hexdigest(),
            "worker_sha256": hashlib.sha256(
                (ROOT / "scripts/openclaw-native-worker.mjs").read_bytes()
            ).hexdigest(),
            "openclaw_harness_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openclaw-root", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--load-samples", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    args.openclaw_root = args.openclaw_root.resolve()
    args.node = args.node.absolute()
    fixture.require(1 <= args.load_samples <= 4000, "--load-samples must be 1..4000")
    fixture.require(1 <= args.concurrency <= 32, "--concurrency must be 1..32")
    fixture.require(args.node.is_file(), "Node executable not found")
    with tempfile.TemporaryDirectory(prefix="siq-intent-openclaw-") as tmp:
        harness = OpenClawHarness(Path(tmp), args)
        try:
            report = harness.run()
        finally:
            harness.stop()
    report["scope"] = (
        "installed OpenClaw plugin loader, native before wrapper, Pi file tools and native after relay; actual Go HTTP and signed receipts"
    )
    report["limitations"] = [
        "synthetic calls and operator; no LLM session or human approval proof",
        "after relay is invoked by this harness, not a full agent session",
        "no live gateway, platform approval journey or CodeBuddy runtime",
        "no OS isolation or full platform support claim",
    ]
    raw = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(raw)
    print(raw, end="")


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
        print(f"native validation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
