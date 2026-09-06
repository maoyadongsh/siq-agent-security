#!/usr/bin/env python3
"""DEV16-D: honesty gate for the perf baseline harness (no prefilled SLA)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "apps" / "agentshield" / "internal" / "perfbaseline" / "perfbaseline.go"
CMD = ROOT / "apps" / "agentshield" / "cmd" / "perfbaseline" / "main.go"
README = ROOT / "docs" / "evidence" / "perf" / "README.md"

FORBIDDEN = [
    re.compile(r"SLA_PASS", re.I),
    re.compile(r"threshold_met\s*[:=]\s*true", re.I),
    re.compile(r"p95\s*<\s*\d+\s*.*pass", re.I),
    re.compile(r"guarantee(?:d)?\s+\d+\s*ms", re.I),
]


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    if not PKG.is_file():
        fail(f"missing {PKG.relative_to(ROOT)}")
    if not CMD.is_file():
        fail(f"missing {CMD.relative_to(ROOT)}")
    if not README.is_file():
        fail(f"missing {README.relative_to(ROOT)}")

    src = PKG.read_text(encoding="utf-8")
    if 'Format = "agentshield.perf_baseline.v1"' not in src:
        fail("perfbaseline Format constant missing")
    if "HonestyNote" not in src or "Observations only" not in src:
        fail("HonestyNote must refuse SLA framing")
    if "Thresholds" not in src:
        fail("Report must expose thresholds field (always null)")
    for pat in FORBIDDEN:
        if pat.search(src):
            fail(f"harness source matches forbidden SLA claim pattern: {pat.pattern}")

    readme = README.read_text(encoding="utf-8")
    if "不预填" not in readme and "no prefilled" not in readme.lower():
        fail("perf README must state no prefilled millisecond guarantees")
    if "smoke" not in readme or "medium" not in readme or "large" not in readme:
        fail("perf README must document smoke/medium/large scales")

    with tempfile.TemporaryDirectory(prefix="siq-perf-check-") as td:
        out = Path(td) / "smoke.json"
        proc = subprocess.run(
            [
                "go",
                "run",
                "./cmd/perfbaseline",
                "-scale",
                "smoke",
                "-receipts",
                "30",
                "-out",
                str(out),
            ],
            cwd=str(ROOT / "apps" / "agentshield"),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            fail(f"smoke run failed: {proc.stderr or proc.stdout}")
        doc = json.loads(out.read_text(encoding="utf-8"))
        if doc.get("format") != "agentshield.perf_baseline.v1":
            fail(f"bad format: {doc.get('format')!r}")
        if doc.get("thresholds") is not None:
            fail("thresholds must be JSON null")
        notes = doc.get("notes") or ""
        if "Observations only" not in notes:
            fail("report notes must carry honesty string")
        metrics = doc.get("metrics") or {}
        for key in ("append_total_ms", "read_limited_ms", "export_build_seal_ms", "rss_bytes_after"):
            if key not in metrics:
                fail(f"metrics missing {key}")
        for block in ("read_limited_ms", "export_build_seal_ms"):
            pct = metrics[block]
            for p in ("p50", "p95", "p99", "n"):
                if p not in pct:
                    fail(f"{block} missing {p}")
        env = doc.get("environment") or {}
        for key in ("go_version", "os", "arch", "num_cpu"):
            if key not in env:
                fail(f"environment missing {key}")

    print("OK: perf baseline harness honesty + smoke measurement")


if __name__ == "__main__":
    main()
