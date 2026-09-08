#!/usr/bin/env python3
"""Run the existing browser smoke against an owned, fresh fixture service.

The output directory is PRIVATE: service metadata includes authentication and
pairing material. Only browser/result.json is a public evidence candidate.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.out_dir.resolve()
    output.mkdir(mode=0o700)  # refuse reuse; never reset someone else's profile
    state = output / "state"
    state.mkdir(mode=0o700)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "apps/secure-agent")}
    with (state / "service.log").open("x") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "secure_agent.service", "--binary",
             str(args.binary.resolve()), "--state-dir", str(state),
             "--mode", "test", "--port", str(port)],
            cwd=ROOT, env=env, stdout=log, stderr=log,
        )
        try:
            deadline = time.monotonic() + 30
            while not ((state / "service.json").exists()
                       and (state / "service.log").stat().st_size):
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("fixture startup failed; inspect private output")
                time.sleep(0.2)
            subprocess.run(
                [sys.executable, str(ROOT / "scripts/hackathon/browser-smoke.py"),
                 "--state-dir", str(state), "--out-dir", str(output / "browser")],
                cwd=ROOT, env=env, check=True,
            )
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=30)
    print(json.dumps({"result": "passed", "provider": "fixture",
                      "public_summary_candidate": str(output / "browser/result.json"),
                      "private_state_must_not_be_uploaded": True}))


if __name__ == "__main__":
    main()
