#!/usr/bin/env python3
"""Verify and launch the unpacked Linux candidate with external private state."""

import argparse
import os
import platform
import sys
from pathlib import Path

# Import verification code without adding an unmanifested cache file to the package.
sys.dont_write_bytecode = True
from package_rc import verify_package


def launch_configuration(package, state, machine=None, system=None):
    package = package.resolve()
    state = state.resolve()
    if state.exists() or state.is_relative_to(package):
        raise ValueError("state must be a new directory outside the candidate")
    if (system or platform.system()) != "Linux":
        raise ValueError("competition service requires Linux; other binaries are daemon-only cross-builds")
    arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "amd64": "amd64"}.get(machine or platform.machine())
    if arch is None:
        raise ValueError("unsupported host architecture")
    verify_package(package)
    binary = package / "bin" / ("siq-agent-security-linux-" + arch)
    if not os.access(binary, os.X_OK):
        raise ValueError("packaged daemon is not executable")
    return package / "source", binary, state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=47621)
    parser.add_argument("--provider", choices=("stepfun", "ornith"), default="stepfun")
    args = parser.parse_args()
    package = Path(__file__).resolve().parents[3]
    source, binary, state = launch_configuration(package, args.state_dir)
    if not 1024 <= args.port <= 65535:
        raise ValueError("port must be between 1024 and 65535")
    os.umask(0o077)
    os.environ.update(PYTHONPATH=str(source / "apps/secure-agent"), PYTHONDONTWRITEBYTECODE="1",
                      SIQ_MODEL_PROVIDER=args.provider)
    os.chdir(source)
    os.execv(sys.executable, [sys.executable, "-B", "-m", "secure_agent.service", "--binary", str(binary),
                             "--state-dir", str(state), "--port", str(args.port)])


if __name__ == "__main__":
    main()
