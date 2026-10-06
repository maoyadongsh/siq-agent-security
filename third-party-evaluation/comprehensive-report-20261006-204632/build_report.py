#!/usr/bin/env python3
"""Compatibility entry: build the report at its canonical evaluations path."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[2] / "evaluations/reports/comprehensive-20261006/build_report.py"), run_name="__main__")
