#!/usr/bin/env python3
"""DEV17-A: assert Control API Dockerfile consumes uv.lock (not unlocked pip)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "apps" / "control-api" / "Dockerfile"
LOCK = ROOT / "apps" / "control-api" / "uv.lock"


def main() -> int:
    if not LOCK.is_file():
        print(f"missing lock: {LOCK}", file=sys.stderr)
        return 1
    text = DOCKERFILE.read_text(encoding="utf-8")
    errors: list[str] = []

    if "uv.lock" not in text:
        errors.append("Dockerfile must COPY/reference uv.lock")
    if not re.search(r"uv\s+sync\s+[^\n]*--locked", text):
        errors.append("Dockerfile must run `uv sync --locked`")
    if not re.search(r"uv\s+sync\s+[^\n]*--no-dev", text):
        errors.append("Dockerfile must run `uv sync --no-dev` for runtime image")
    # Unlocked install of the project is the original M-P3 failure mode.
    code_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        code_lines.append(line)
    code = "\n".join(code_lines)
    if re.search(r"pip\s+install\s+(--no-cache-dir\s+)?\.", code):
        errors.append("Dockerfile must not `pip install .` (bypasses uv.lock)")
    if "UV_PROJECT_ENVIRONMENT" not in code and ".venv" not in code:
        errors.append("Dockerfile should isolate install into a venv for runtime copy")

    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print("OK: control-api Dockerfile uses locked uv install")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
