#!/usr/bin/env python3
"""DEV17-D: Dockerfiles must pin base images by digest (not mutable tags alone)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DOCKERFILES = [
    ROOT / "apps" / "control-api" / "Dockerfile",
    ROOT / "apps" / "web" / "Dockerfile",
]

DIGEST_RE = re.compile(r"@sha256:[0-9a-f]{64}\b")

EXPECTED = {
    "apps/control-api/Dockerfile": {
        "python:3.12-slim-bookworm": "sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254",
        "ghcr.io/astral-sh/uv:0.11.7": "sha256:240fb85ab0f263ef12f492d8476aa3a2e4e1e333f7d67fbdd923d00a506a516a",
    },
    "apps/web/Dockerfile": {
        "node:22-bookworm-slim": "sha256:83f487e0a63425e5b4d146fb5e5be574bcbe1b7b843d3ebafdd95eaf7767a7e5",
        "nginx:1.29.7-alpine3.23": "sha256:e7257f1ef28ba17cf7c248cb8ccf6f0c6e0228ab9c315c152f9c203cd34cf6d1",
    },
}


def main() -> int:
    errors: list[str] = []
    for path in DOCKERFILES:
        rel = str(path.relative_to(ROOT))
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"^FROM\s+(\S+)", text, re.M):
            ref = m.group(1)
            if not DIGEST_RE.search(ref):
                errors.append(f"{rel}: unpinned FROM: {ref}")
        for m in re.finditer(r"^COPY --from=(\S+)", text, re.M):
            ref = m.group(1)
            if "/" in ref and not DIGEST_RE.search(ref):
                errors.append(f"{rel}: unpinned COPY --from=: {ref}")
        expected = EXPECTED.get(rel, {})
        for name, digest in expected.items():
            needle = f"{name}@{digest}"
            if needle not in text:
                errors.append(f"{rel}: missing expected pin {needle}")

    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print("OK: Dockerfiles pin base images by digest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
