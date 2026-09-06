#!/usr/bin/env python3
"""盘点 Outbox 历史空对象引用（DEV11-F）。只读，不修复。"""

from __future__ import annotations

import json
import sys

from app.config import load_settings
from app.db import init_db, session_scope
from app.outbox_null_inventory import inventory_report


def main() -> int:
    settings = load_settings()
    init_db(settings)
    with session_scope() as session:
        report = inventory_report(session)
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if report["events_with_null_refs"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
