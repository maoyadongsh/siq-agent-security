#!/usr/bin/env python3
"""Offline guards for the S1-S4 measurement driver's imported dependencies."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
DRIVER = HERE / "openshell-o05v6-taskexec-perf.py"


def load_driver():
    spec = importlib.util.spec_from_file_location("o05v6_taskexec_perf_dependency_test", DRIVER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load performance driver")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DependencyBindingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = load_driver()

    def test_real_dependencies_match_frozen_hashes(self):
        bound = self.driver.bind_driver_dependencies()
        self.assertEqual(set(bound), {"base_driver", "b2b3_helper"})
        for name, item in bound.items():
            self.assertEqual(item["sha256"], self.driver.DEPENDENCY_SHA256[name])

    def test_drift_fails_before_import_or_live_access(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "helper.py"
            path.write_text("# changed\n", encoding="utf-8")
            with self.assertRaisesRegex(SystemExit, "dependency drifted: helper"):
                self.driver.bind_driver_dependencies(
                    paths={"helper": path},
                    expected={"helper": "0" * 64},
                )

    def test_name_set_mismatch_is_rejected(self):
        with self.assertRaisesRegex(SystemExit, "names do not match"):
            self.driver.bind_driver_dependencies(paths={}, expected={"helper": "0" * 64})


if __name__ == "__main__":
    unittest.main()
