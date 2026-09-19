#!/usr/bin/env python3
"""Offline tests for the LX04 natural-expiry evidence harvester."""

import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
DRIVER = HERE / "lx04-admin-session-expiry-harvest.py"


def load_driver():
    spec = importlib.util.spec_from_file_location("lx04_admin_expiry_harvest_test", DRIVER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load harvester")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_private(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HarvestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.driver = load_driver()

    def fixture(self, root: Path):
        private = root / "expiry-private"
        private.mkdir(mode=0o700)
        private.chmod(0o700)
        seed = {
            "schema_version": self.driver.SEED_SCHEMA,
            "candidate_sha256": "a" * 64,
            "daemon_pid": 999_999_991,
            "daemon_starttime": "1",
            "port": 9,
            "state": str(private / "state"),
            "bearer": "must-never-be-public",
            "cookie": "must-never-be-public",
            "export_before_sha256": "b" * 64,
            "paired_after_epoch": 1000.0,
            "not_before_epoch": 44202.0,
            "paired_at_utc": "2026-01-01T00:00:00+00:00",
            "verify_after_utc": "2026-01-01T12:00:02+00:00",
        }
        result = {
            "schema_version": self.driver.RESULT_SCHEMA,
            "candidate_sha256": "a" * 64,
            "checked_at_utc": "2026-01-01T12:00:03+00:00",
            "real_wall_seconds": 43203.0,
            "same_daemon_alive": True,
            "health_ready": True,
            "expired_export_status": 401,
            "expired_restore_status": 401,
            "export_payload_absent": True,
            "restore_session_absent": True,
            "passed": True,
        }
        write_private(private / "seed.json", seed)
        write_private(private / "result.json", result)
        write_private(private / "worker.json", {"pid": 999_999_992, "starttime": "1"})
        for name in ("daemon.log", "worker.log"):
            path = private / name
            path.write_text("private material", encoding="utf-8")
            path.chmod(0o600)
        pending = root / "pending.json"
        pending.write_text(json.dumps({
            "schema_version": self.driver.PENDING_SCHEMA,
            "candidate_sha256": "a" * 64,
            "driver_sha256": "c" * 64,
            "private_seed_sha256": sha(private / "seed.json"),
            "pre_expiry_signed_task_export_sha256": "b" * 64,
            "verify_after_utc": seed["verify_after_utc"],
            "production_admin_ttl_seconds": 43200,
            "pre_expiry_signed_export_independently_verified": True,
        }), encoding="utf-8")
        return private, pending, result

    def args(self, private: Path, pending: Path, output: Path):
        class Args:
            pass
        args = Args()
        args.private = private
        args.pending_summary = pending
        args.output = output
        args.cleanup_wait_seconds = 0
        args.cleanup_owned_daemon = False
        return args

    def test_publishes_only_bound_safe_fields(self):
        with tempfile.TemporaryDirectory() as raw:
            private, pending, _ = self.fixture(Path(raw))
            output = Path(raw) / "summary.json"
            summary = self.driver.harvest(self.args(private, pending, output))
            self.assertEqual(summary["status"], "passed_real_wall_clock")
            public = output.read_text()
            self.assertNotIn("must-never-be-public", public)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o644)

    def test_rejects_short_wall_clock(self):
        with tempfile.TemporaryDirectory() as raw:
            private, pending, result = self.fixture(Path(raw))
            result["real_wall_seconds"] = 43199
            write_private(private / "result.json", result)
            with self.assertRaisesRegex(RuntimeError, "real_wall_expiry_not_proven"):
                self.driver.harvest(self.args(private, pending, Path(raw) / "summary.json"))

    def test_rejects_live_worker_identity(self):
        with tempfile.TemporaryDirectory() as raw:
            private, pending, _ = self.fixture(Path(raw))
            current = Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(") ", 1)[1].split()[19]
            write_private(private / "worker.json", {"pid": os.getpid(), "starttime": current})
            with self.assertRaisesRegex(RuntimeError, "expiry_worker_still_running"):
                self.driver.harvest(self.args(private, pending, Path(raw) / "summary.json"))


if __name__ == "__main__":
    unittest.main()
