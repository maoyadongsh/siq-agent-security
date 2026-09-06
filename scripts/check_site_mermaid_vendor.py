#!/usr/bin/env python3
"""DEV17-C / M-C2: architecture page must use pinned self-hosted Mermaid, not CDN."""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "site" / "architecture.html"
VENDOR = ROOT / "site" / "vendor" / "mermaid-11.4.1.min.js"
SHA_FILE = ROOT / "site" / "vendor" / "mermaid-11.4.1.min.js.sha256"

CDN_RE = re.compile(
    r"(cdn\.jsdelivr\.net|unpkg\.com|cdnjs\.cloudflare\.com|esm\.sh)/.*mermaid",
    re.I,
)
VENDOR_REF_RE = re.compile(r"""src=["']\./vendor/mermaid-11\.4\.1\.min\.js["']""")


def main() -> int:
    errors: list[str] = []
    html = PAGE.read_text(encoding="utf-8")

    if CDN_RE.search(html):
        errors.append("architecture.html still references a Mermaid CDN URL")
    if "import mermaid from" in html:
        errors.append("architecture.html still dynamically imports Mermaid")
    if not VENDOR_REF_RE.search(html):
        errors.append("architecture.html must load ./vendor/mermaid-11.4.1.min.js")
    if not VENDOR.is_file():
        errors.append(f"missing vendor file: {VENDOR.relative_to(ROOT)}")
    else:
        digest = hashlib.sha256(VENDOR.read_bytes()).hexdigest()
        if not SHA_FILE.is_file():
            errors.append(f"missing sha256 sidecar: {SHA_FILE.relative_to(ROOT)}")
        else:
            recorded = SHA_FILE.read_text(encoding="utf-8").split()[0].strip().lower()
            if recorded != digest:
                errors.append(
                    f"vendor sha256 mismatch: file={digest} sidecar={recorded}"
                )
        print(f"mermaid vendor sha256={digest}")

    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print("OK: Mermaid is self-hosted and pinned")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
