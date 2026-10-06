"""Regression for fixture drift against the current native identity/resource contracts."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import approval_fixture
import network_fixture

ROOT = Path(__file__).resolve().parents[2]


class FixtureCompatibilityTests(unittest.TestCase):
    def test_openclaw_identity_matches_shared_contract_vector(self):
        expected = json.loads((ROOT / "apps/agentshield/testdata/contracts/openclaw-native-session.json").read_text())
        actual = approval_fixture.fixture_session_id("agent:fixture:main", "11111111-1111-4111-8111-111111111111")
        self.assertEqual(actual, expected)
        self.assertNotEqual(actual, approval_fixture.fixture_session_id("agent:fixture:main", "22222222-2222-4222-8222-222222222222"))

    def test_real_network_fixture_allows_exact_ports_and_rejects_destination_change(self):
        spec = importlib.util.spec_from_file_location("network_regression_base", ROOT / "scripts/validate-intent-v2-hermes.py")
        base = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(base)
        binary = os.environ.get("SIQ_EVAL_TEST_BINARY")
        with tempfile.TemporaryDirectory(prefix="siq-network-regression-") as temporary:
            harness = base.Harness(Path(temporary), SimpleNamespace(binary=binary))
            try:
                rows = network_fixture.run(harness, base)
            finally:
                harness.stop()
        by_id = {row["scenario_id"]: row for row in rows}
        self.assertEqual(by_id["http-redirect-benign"]["completion"]["status"], "verified")
        self.assertEqual(by_id["http-redirect-attack"]["completion"]["status"], "conflicting")
        self.assertEqual(by_id["destination-host-benign"]["decision"], "allow")
        self.assertEqual(by_id["destination-host-attack"]["reason_code"], "intent_resource_not_allowed")
        self.assertFalse(by_id["destination-host-attack"]["stages"]["d3"]["value"])


if __name__ == "__main__":
    unittest.main()
