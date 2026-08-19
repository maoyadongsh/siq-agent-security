#!/usr/bin/env python3
"""ENG-03: agent-security core envelope must match the documented checksum."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "packages" / "contracts" / "event-envelope-core.schema.json"
CHECKSUM = ROOT / "packages" / "contracts" / "event-envelope-core.sha256"


def main() -> int:
    digest = hashlib.sha256(CORE.read_bytes()).hexdigest()
    recorded = CHECKSUM.read_text(encoding="utf-8").strip().split()[0]
    if digest != recorded:
        print(f"checksum drift: {digest} != {recorded}")
        return 1
    print("event-envelope-core checksum ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
