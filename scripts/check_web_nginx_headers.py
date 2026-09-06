#!/usr/bin/env python3
"""DEV17-B: assert enterprise web nginx ships required security headers (no HSTS on HTTP)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INC = ROOT / "apps" / "web" / "security-headers.inc"
CONF = ROOT / "apps" / "web" / "nginx.conf"
DOCKER = ROOT / "apps" / "web" / "Dockerfile"

REQUIRED = [
    'X-Content-Type-Options "nosniff"',
    'X-Frame-Options "DENY"',
    'Referrer-Policy "strict-origin-when-cross-origin"',
    "Permissions-Policy",
    "Content-Security-Policy",
    "frame-ancestors 'none'",
]


def main() -> int:
    errors: list[str] = []
    if not INC.is_file():
        errors.append(f"missing {INC}")
    else:
        text = INC.read_text(encoding="utf-8")
        for needle in REQUIRED:
            if needle not in text:
                errors.append(f"security-headers.inc missing {needle}")
        if "Strict-Transport-Security" in text or "HSTS" in text.upper():
            errors.append("HTTP entry must not set HSTS/Strict-Transport-Security")

    conf = CONF.read_text(encoding="utf-8") if CONF.is_file() else ""
    if "security-headers.inc" not in conf:
        errors.append("nginx.conf must include security-headers.inc")
    if "listen 80" in conf and ("Strict-Transport-Security" in conf):
        errors.append("nginx.conf must not set HSTS on listen 80")

    docker = DOCKER.read_text(encoding="utf-8") if DOCKER.is_file() else ""
    if "security-headers.inc" not in docker:
        errors.append("web Dockerfile must COPY security-headers.inc")

    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print("OK: web nginx security headers present (no HTTP HSTS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
