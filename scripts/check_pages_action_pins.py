#!/usr/bin/env python3
"""DEV17-D / M-C1a: pages.yml must pin Actions to full commit SHAs."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows" / "pages.yml"

# Match both `- uses:` and nested `uses:` under a named step.
USES_RE = re.compile(r"^\s*-?\s*uses:\s*([^@\s#]+)@([0-9a-f]{40})\b", re.M)
# Mutable tags only (v4, 4.0.4) — not 40-char hex SHAs.
BAD_TAG_RE = re.compile(
    r"^\s*-?\s*uses:\s*([^@\s#]+)@(v?\d[\w.-]*)\s*(?:#.*)?$",
    re.M,
)

EXPECTED = {
    "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
    "peaceiris/actions-gh-pages": "84c30a85c19949d7eee79c4ff27748b70285e453",
}


def main() -> int:
    text = WF.read_text(encoding="utf-8")
    errors: list[str] = []

    for m in BAD_TAG_RE.finditer(text):
        tag = m.group(2)
        if re.fullmatch(r"[0-9a-f]{40}", tag):
            continue
        errors.append(f"unpinned action tag: {m.group(1)}@{tag}")

    found: dict[str, str] = {}
    for m in USES_RE.finditer(text):
        found[m.group(1)] = m.group(2)

    for name, sha in EXPECTED.items():
        got = found.get(name)
        if got is None:
            errors.append(f"missing pinned uses for {name}")
        elif got != sha:
            errors.append(f"{name} pinned to {got}, expected {sha}")

    if "timeout-minutes:" not in text:
        errors.append("job must set timeout-minutes")

    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print("OK: pages.yml Actions pinned to full commit SHAs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
