#!/usr/bin/env python3
"""Offline guards for private OpenShell environment loading."""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
DRIVER = HERE / "openshell-o05v6-taskexec-journey.py"


def load_driver():
    spec = importlib.util.spec_from_file_location("o05v6_taskexec_env_test", DRIVER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load task-execution journey")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class EnvironmentScriptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = load_driver()

    def script(self, root: str, text: str) -> Path:
        path = Path(root) / "env.sh"
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)
        return path

    def test_parent_with_same_values_does_not_hide_script_exports(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.script(
                root,
                "export SIQ_OPENSHELL_BIN=/managed/openshell\n"
                "export XDG_CONFIG_HOME=/isolated/config\n",
            )
            with patch.dict(os.environ, {
                "SIQ_OPENSHELL_BIN": "/managed/openshell",
                "XDG_CONFIG_HOME": "/isolated/config",
            }, clear=False):
                loaded = self.driver.load_env_script(path)
            self.assertEqual(loaded["SIQ_OPENSHELL_BIN"], "/managed/openshell")
            self.assertEqual(loaded["XDG_CONFIG_HOME"], "/isolated/config")

    def test_ambient_relevant_value_not_defined_by_script_is_excluded(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.script(root, "export SIQ_OPENSHELL_BIN=/managed/openshell\n")
            with patch.dict(os.environ, {"OPENSHELL_GATEWAY": "ambient-gateway"}, clear=False):
                loaded = self.driver.load_env_script(path)
            self.assertNotIn("OPENSHELL_GATEWAY", loaded)
            self.assertEqual(loaded["SIQ_OPENSHELL_BIN"], "/managed/openshell")

    def test_unrelated_script_values_are_not_forwarded(self):
        with tempfile.TemporaryDirectory() as root:
            path = self.script(
                root,
                "export SIQ_OPENSHELL_BIN=/managed/openshell\n"
                "export PRIVATE_UNRELATED=do-not-forward\n",
            )
            loaded = self.driver.load_env_script(path)
            self.assertNotIn("PRIVATE_UNRELATED", loaded)


if __name__ == "__main__":
    unittest.main()
