#!/usr/bin/env python3
"""DEV18-B / M-T1: threat-model.md must cover local AgentShield threats."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "threat-model.md"

REQUIRED_IDS = [f"L{i}" for i in range(1, 13)]
REQUIRED_PHRASES = [
    "desktop-same-uid",
    "DNS rebinding",
    "同 UID",
    "readback_verified",
    "agentshield-capability-profiles-v1.md",
    "local-product-threats",
]


def main() -> int:
    text = DOC.read_text(encoding="utf-8")
    errors: list[str] = []

    if "本地产品威胁" not in text:
        errors.append("missing local product threat section heading")

    for phrase in REQUIRED_PHRASES:
        if phrase not in text:
            errors.append(f"missing required phrase: {phrase}")

    for lid in REQUIRED_IDS:
        # Table rows like | L1 | ...
        if not re.search(rf"\|\s*{lid}\s*\|", text):
            errors.append(f"missing local threat row {lid}")

    # Must not claim managed-linux or S2b as done in this section.
    bad_claims = [
        r"managed-linux\s*(已实现|通过|完成)",
        r"S2b\s*(通过|完成|已验证)",
        r"enforcement_verified\s*(已通过|完成)",
    ]
    for pat in bad_claims:
        if re.search(pat, text):
            errors.append(f"overclaim matched /{pat}/")

    if errors:
        for e in errors:
            print(f"FAIL: {e}", file=sys.stderr)
        return 1
    print("OK: threat-model.md includes local product threats L1–L12")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
