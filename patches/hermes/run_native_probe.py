#!/usr/bin/env python3
"""Run the synthetic-authority probe in the exact offline business image."""

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from build_native_overlay import IMAGE, SOURCES


def run(overlay, output):
    overlay, output = overlay.resolve(strict=True), output.resolve()
    manifest = json.loads((overlay / "manifest.json").read_text())
    if manifest["base_image_id"] != IMAGE or manifest["source_sha256"] != SOURCES:
        raise ValueError("native_probe_candidate_changed")
    for name, expected in manifest["overlay_sha256"].items():
        path = overlay / name
        if not path.resolve(strict=True).is_relative_to(overlay) or path.is_symlink():
            raise ValueError("native_probe_unsafe_candidate")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("native_probe_candidate_changed")
    cmd = ["/usr/bin/docker", "run", "--rm", "--pull=never", "--network=none", "--read-only",
           "--cap-drop=ALL", "--security-opt=no-new-privileges", "--user", f"{os.getuid()}:{os.getgid()}",
           "--tmpfs", "/tmp:rw,nosuid,nodev,size=256m"]
    for name in SOURCES:
        cmd += ["--mount", f"type=bind,src={overlay/name},dst=/opt/hermes-agent/{name},readonly"]
    cmd += ["--mount", f"type=bind,src={overlay/'siq_native_runtime'},dst=/opt/hermes-agent/siq_native_runtime,readonly",
            "--mount", f"type=bind,src={Path(__file__).with_name('native_probe.py').resolve()},dst=/native-probe.py,readonly",
            "--entrypoint", "/opt/siq/hermes/venv/bin/python", IMAGE, "-I", "-B", "/native-probe.py"]
    # Docker writes the exact owned container ID before starting it. Clean up
    # that ID on timeout as well as normal exit, never a user container by name.
    with tempfile.TemporaryDirectory(prefix="siq-native-probe-") as scratch:
        cidfile = Path(scratch) / "container-id"
        cmd[2:2] = ["--cidfile", str(cidfile)]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90, check=False)
        finally:
            if cidfile.exists():
                cid = cidfile.read_text().strip()
                if len(cid) == 64 and all(c in "0123456789abcdef" for c in cid):
                    subprocess.run(["/usr/bin/docker", "rm", "-f", cid],
                                   capture_output=True, timeout=15, check=False)
    output.with_suffix(".log").write_text(proc.stdout + proc.stderr)
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.startswith('{"schema_version": "siq.native-hermes-function-probe/v1"')]
    if len(rows) != 1:
        raise RuntimeError("native_probe_missing_result")
    result = rows[0]
    result["base_image_id"] = IMAGE
    result["overlay_manifest_sha256"] = hashlib.sha256((overlay / "manifest.json").read_bytes()).hexdigest()
    result["exit_code"] = proc.returncode
    output.write_text(json.dumps(result, indent=2) + "\n")
    if proc.returncode or not result["checks"] or not all(v is True for v in result["checks"].values()):
        raise RuntimeError("native_probe_failed")
    print(json.dumps({"checks_passed": len(result["checks"]), "model_calls": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.overlay, args.output)
