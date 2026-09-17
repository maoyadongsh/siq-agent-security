"""Offline negative gates; never contacts a gateway or executes a live driver."""
import importlib.util
import json
import subprocess
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("perf", Path(__file__).with_name("openshell-b2b3-perf-protocol.py"))
perf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(perf)


class PerfGates(unittest.TestCase):
    def diagnosis(self):
        now = datetime.now(UTC)
        return {"state": "policy_readable", "probe_ok": True, "identity_ok": True,
                "started_gateway": False, "target": "owned", "revision": "2",
                "policy_digest": "a" * 64, "observed_at": (now - timedelta(seconds=1)).isoformat(),
                "expires_at": (now + timedelta(seconds=10)).isoformat()}

    def test_doctor_requires_readback_not_rc_zero(self):
        good = self.diagnosis()
        self.assertEqual(perf.validate_doctor(json.dumps(good), "owned")["revision"], "2")
        for key, value in [("state", "handshake_verified"), ("probe_ok", False), ("identity_ok", False),
                           ("target", "other"), ("revision", "01"), ("policy_digest", "invalid"),
                           ("started_gateway", True), ("expires_at", "2000-01-01T00:00:00Z")]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    perf.validate_doctor(json.dumps({**good, key: value}), "owned")
        for bad in ("not JSON", "[]", "{}"):
            with self.assertRaises(ValueError):
                perf.validate_doctor(bad, "owned")

    def test_unreachable_requires_exact_state_and_false_flags(self):
        d = {"state": "configured_unreachable", "probe_ok": False, "identity_ok": False, "started_gateway": False}
        perf.validate_doctor(json.dumps(d), "owned", True)
        for bad in ({"note": "configured_unreachable"}, {**d, "probe_ok": True}):
            with self.assertRaises(ValueError):
                perf.validate_doctor(json.dumps(bad), "owned", True)

    def test_skipped_or_noop_driver_does_not_pass(self):
        for text in ("PASS", "--- SKIP: TestO05LiveRollbackRestore (0.00s)\nPASS",
                     "--- PASS: TestO05LiveRollbackRestore (0.01s)\nno-op\nPASS"):
            with self.assertRaises(ValueError):
                perf.validate_driver(text)
        perf.validate_driver(f"--- PASS: TestO05LiveRollbackRestore (1.00s)\n{perf.MARKER}\nPASS")

    def test_absolute_miss_is_nonpassing_despite_relative_pass(self):
        samples = {f"{leg}:{name}": [{"wall_ms": 16000, "child_cpu_ms": 1}]
                   for leg in ("old", "new") for name in perf.SCENARIOS}
        verdicts = perf.summarize(samples)
        self.assertEqual(verdicts["relative:doctor_readback"]["verdict"], "pass")
        self.assertEqual(len(perf.budget_misses(verdicts)), 4)

    def test_nearest_rank_even_population(self):
        self.assertEqual(perf.percentile([1, 2, 3, 4], 50), 2)
        self.assertEqual(perf.percentile([1, 2, 3, 4], 99), 4)

    def test_rc_zero_invalid_report_rejected(self):
        p = subprocess.CompletedProcess(["doctor"], 0, "{}", "")
        with patch.object(perf.subprocess, "run", return_value=p):
            with self.assertRaises(ValueError):
                perf.run_once(["doctor"], {}, lambda s: perf.validate_doctor(s, "owned"))

    def test_failure_does_not_echo_secret(self):
        p = subprocess.CompletedProcess(["doctor"], 1, "", "SECRET_CANARY")
        with patch.object(perf.subprocess, "run", return_value=p):
            with self.assertRaises(RuntimeError) as cm:
                perf.run_once(["SECRET_CANARY"], {}, lambda _: {})
        self.assertNotIn("SECRET_CANARY", str(cm.exception))

    def test_cli_environment_control_is_not_candidate_comparison(self):
        self.assertNotIn("cli_sandbox_get", perf.RELATIVE_SCENARIOS)


if __name__ == "__main__":
    unittest.main()
