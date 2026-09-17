#!/usr/bin/env python3
"""Protect the diagnostic's real-host versus isolated-HOME evidence boundary."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).with_name("workbuddy-linux-host-diagnostics.py")
SPEC = importlib.util.spec_from_file_location("workbuddy_host_diagnostics", MODULE_PATH)
assert SPEC and SPEC.loader
diagnostics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostics)


class HostScopeTests(unittest.TestCase):
    def test_isolated_home_does_not_inherit_real_layout_or_path(self):
        with tempfile.TemporaryDirectory(prefix="workbuddy-probe-fixture-") as temporary:
            home = Path(temporary)
            (home / ".workbuddy").mkdir()
            with patch.object(diagnostics.shutil, "which", side_effect=AssertionError("real PATH probed")):
                report = diagnostics.probe_host(home)
            self.assertEqual(report["home"], "<isolated-home>")
            self.assertFalse(report["runtime_confirmed"])
            self.assertEqual(report["adjacent_family_installs"], [])
            self.assertEqual(report["processes"], [])
            self.assertTrue(all(not row["found"] for row in report["executables"]))
            self.assertNotIn(temporary, json.dumps(report))

    def test_fixture_report_cannot_claim_host_grade_or_leak_home(self):
        with tempfile.TemporaryDirectory(prefix="workbuddy-probe-fixture-") as temporary:
            home = Path(temporary) / "isolated-home"
            home.mkdir()
            report_path = Path(temporary) / "report.json"
            exit_code = diagnostics.main(
                ["probe", "--home", str(home), "--grade", "host", "--out", str(report_path)]
            )
            self.assertEqual(exit_code, 0)
            report = json.loads(report_path.read_text())
            self.assertEqual(report["evidence_grade"], "component_fixture")
            self.assertFalse(report["host_home"])
            self.assertEqual(report["acceptance"]["verdict"], "blocked")
            self.assertNotIn(temporary, report_path.read_text())


if __name__ == "__main__":
    unittest.main()
