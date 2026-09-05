#!/usr/bin/env python3
"""Print year-on-year deltas for a statement JSON using exact decimals."""

import json
import sys
from decimal import Decimal, InvalidOperation


def main(argv):
    if len(argv) != 2:
        print(json.dumps({"status": "error", "error": "usage: summarize.py <statement.json>"}))
        return 1
    with open(argv[1], encoding="utf-8") as handle:
        statement = json.load(handle)
    rows = []
    for item in statement.get("items", []):
        try:
            current = Decimal(str(item["current"]))
            previous = Decimal(str(item["previous"]))
        except (KeyError, InvalidOperation):
            rows.append({"name": item.get("name"), "status": "evidence_gap"})
            continue
        delta = current - previous
        rate = None if previous == 0 else delta / abs(previous)
        rows.append({
            "name": item.get("name"),
            "delta": str(delta),
            "rate": None if rate is None else str(rate),
            "formula": f"({current} - {previous}) / abs({previous})",
        })
    print(json.dumps({"status": "ok", "rows": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
