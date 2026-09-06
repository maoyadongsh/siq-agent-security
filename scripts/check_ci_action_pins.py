#!/usr/bin/env python3
"""DEV17-B: assert ci.yml pins third-party Actions to full commit SHAs."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"

# Mutable tags are forbidden; comment may still mention @vN for humans.
USES_RE = re.compile(r"^\s*-\s*uses:\s*([^@\s]+)@([0-9a-f]{40})\b", re.M)
BAD_TAG_RE = re.compile(r"^\s*-\s*uses:\s*([^@\s]+)@(v?\d[\w.-]*)\s*$", re.M)

EXPECTED = {
    "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
    "actions/setup-go": "40f1582b2485089dde7abd97c1529aa768e1baff",
    "actions/setup-node": "49933ea5288caeca8642d1e84afbd3f7d6820020",
    "astral-sh/setup-uv": "d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86",
    "gitleaks/gitleaks-action": "ff98106e4c7b2bc287b24eaf42907196329070c7",
}


def main() -> int:
    text = CI.read_text(encoding="utf-8")
    errors: list[str] = []

    for m in BAD_TAG_RE.finditer(text):
        errors.append(f"unpinned action tag: {m.group(1)}@{m.group(2)}")

    found: dict[str, str] = {}
    for m in USES_RE.finditer(text):
        found[m.group(1)] = m.group(2)

    for name, sha in EXPECTED.items():
        got = found.get(name)
        if got is None:
            errors.append(f"missing pinned uses for {name}")
        elif got != sha:
            errors.append(f"{name} pinned to {got}, expected {sha} (update checker if intentional bump)")

    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print("OK: ci.yml Actions pinned to full commit SHAs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
