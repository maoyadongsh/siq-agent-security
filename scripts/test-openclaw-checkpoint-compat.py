#!/usr/bin/env python3
"""Exercise upgrade recovery and refusal invariants using synthetic package files."""

from __future__ import annotations

import difflib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).with_name("openclaw-checkpoint-compat.py")
loader = importlib.util.spec_from_file_location("checkpoint_compat", TOOL)
compat = importlib.util.module_from_spec(loader)
loader.loader.exec_module(compat)


@unittest.skipUnless(os.name == "posix", "POSIX upgrade tool")
class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="siq-checkpoint-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime = self.root / "runtime"
        self.target = self.runtime / "dist/fixture.js"
        self.target.parent.mkdir(parents=True)
        (self.runtime / "package.json").write_text(
            json.dumps({"name": "openclaw", "version": "fixture"})
        )
        self.before = b"export const checkpoint = false;\n"
        self.after = b"export const checkpoint = true;\n"
        self.target.write_bytes(self.before)
        self.target.chmod(0o640)
        self.patch = "".join(
            difflib.unified_diff(
                self.before.decode().splitlines(True),
                self.after.decode().splitlines(True),
                fromfile="a/dist/fixture.js",
                tofile="b/dist/fixture.js",
            )
        ).encode()
        self.profile = {
            "package": "openclaw",
            "version": "fixture",
            "target": "dist/fixture.js",
            "before_sha256": compat.digest(self.before),
            "after_sha256": compat.digest(self.after),
            "patch_sha256": compat.digest(self.patch),
        }
        self.backup = self.root / "backup"

    def updater(self, backup=None):
        return compat.Updater(
            self.runtime, backup or self.backup, profile=self.profile, patch=self.patch
        )

    def test_apply_restore_idempotency_and_metadata(self):
        u = self.updater()
        self.assertEqual(u.state(), "stock")
        self.assertFalse(self.backup.exists())
        self.assertTrue(u.apply()["changed"])
        self.assertEqual(self.target.read_bytes(), self.after)
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o640)
        self.assertEqual(stat.S_IMODE(self.backup.stat().st_mode), 0o700)
        self.assertEqual(
            stat.S_IMODE((self.backup / "original.js").stat().st_mode), 0o600
        )
        prepared = (self.backup / "prepared.json").read_bytes()
        self.assertFalse(u.apply()["changed"])
        self.assertTrue(u.restore()["changed"])
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertFalse(u.restore()["changed"])
        self.assertEqual((self.backup / "prepared.json").read_bytes(), prepared)
        with self.assertRaisesRegex(RuntimeError, "fresh_backup_required"):
            u.apply()
        self.assertTrue(self.updater(self.root / "next-backup").apply()["changed"])

    def test_modified_source_is_never_overwritten(self):
        u = self.updater()
        self.target.write_bytes(b"later upstream update")
        self.assertEqual(u.state(), "modified")
        with self.assertRaisesRegex(RuntimeError, "modified_runtime_rejected"):
            u.apply()
        self.assertFalse(self.backup.exists())
        self.target.write_bytes(self.before)
        u.apply()
        self.target.write_bytes(b"later local modification")
        with self.assertRaisesRegex(RuntimeError, "modified_runtime_rejected"):
            u.restore()
        self.assertEqual(self.target.read_bytes(), b"later local modification")

    def test_wrong_version_or_patch_fails_before_backup(self):
        self.patch += b"modified"
        with self.assertRaisesRegex(RuntimeError, "patch_checksum"):
            self.updater()
        self.patch = self.patch[:-8]
        (self.runtime / "package.json").write_text(
            '{"name":"openclaw","version":"other"}'
        )
        with self.assertRaisesRegex(RuntimeError, "unsupported_package_version"):
            self.updater()
        self.assertFalse(self.backup.exists())

    def test_bad_after_digest_does_not_replace(self):
        self.profile["after_sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "patched_checksum"):
            self.updater().apply()
        self.assertEqual(self.target.read_bytes(), self.before)

    def test_corrupt_backup_refuses_restore(self):
        u = self.updater()
        u.apply()
        (self.backup / "original.js").write_bytes(b"corrupt")
        with self.assertRaisesRegex(RuntimeError, "backup_checksum"):
            u.restore()
        self.assertEqual(self.target.read_bytes(), self.after)

    def test_wrong_backup_identity_refuses_restore(self):
        u = self.updater()
        u.apply()
        record = self.backup / "prepared.json"
        value = json.loads(record.read_text())
        value["runtime"] = str(self.root / "different-runtime")
        record.write_text(json.dumps(value))
        with self.assertRaisesRegex(RuntimeError, "backup_identity_or_metadata"):
            u.restore()

    def test_permission_changes_refuse_restore(self):
        u = self.updater()
        u.apply()
        self.target.chmod(0o600)
        with self.assertRaisesRegex(RuntimeError, "backup_identity_or_metadata"):
            u.restore()
        self.assertEqual(stat.S_IMODE(self.target.stat().st_mode), 0o600)

    def test_unsafe_backup_directories_refused(self):
        for path in [self.runtime / "backup", self.root / "public-backup"]:
            path.mkdir(mode=0o755)
            with self.assertRaises(RuntimeError):
                self.updater(path).apply()
        self.backup.mkdir(mode=0o700)
        (self.backup / "unrelated.txt").write_text("keep")
        with self.assertRaisesRegex(RuntimeError, "backup_directory_not_owned"):
            self.updater().apply()
        self.assertEqual((self.backup / "unrelated.txt").read_text(), "keep")

    def test_symlink_and_hardlink_targets_refused(self):
        saved = self.root / "saved.js"
        self.target.rename(saved)
        self.target.symlink_to(saved)
        with self.assertRaises(RuntimeError):
            self.updater()
        self.target.unlink()
        os.link(saved, self.target)
        with self.assertRaises(RuntimeError):
            self.updater()
        self.assertEqual(saved.read_bytes(), self.before)

    def test_symlink_backup_refused(self):
        actual = self.root / "actual-backup"
        actual.mkdir(mode=0o700)
        self.backup.symlink_to(actual, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, "independent_backup"):
            self.updater().apply()
        self.assertEqual(list(actual.iterdir()), [])

    def test_corrupt_completion_marker_refuses_restore(self):
        u = self.updater()
        u.apply()
        (self.backup / "applied.json").write_text("corrupted marker")
        with self.assertRaisesRegex(RuntimeError, "backup_record_conflict"):
            u.restore()
        self.assertEqual(self.target.read_bytes(), self.after)

    def test_lock_contention_refuses_second_writer(self):
        first = self.updater()
        with (
            first.locked(),
            self.assertRaisesRegex(RuntimeError, "upgrade_already_running"),
        ):
            self.updater(self.root / "other-backup").apply()
        self.assertEqual(self.target.read_bytes(), self.before)
        first.apply()

    def crash(self, operation, method):
        spec = self.root / "crash.json"
        spec.write_text(
            json.dumps({"profile": self.profile, "patch": self.patch.decode()})
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import importlib.util,json,os,signal,sys; from pathlib import Path; "
                    "s=importlib.util.spec_from_file_location('compat',sys.argv[1]); "
                    "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                    "x=json.loads(Path(sys.argv[4]).read_text()); "
                    "u=m.Updater(sys.argv[2],sys.argv[3],profile=x['profile'],patch=x['patch'].encode()); "
                    "setattr(u,sys.argv[6],lambda *a:os.kill(os.getpid(),signal.SIGKILL)); "
                    "getattr(u,sys.argv[5])()"
                ),
                str(TOOL),
                str(self.runtime),
                str(self.backup),
                str(spec),
                operation,
                method,
            ],
            capture_output=True,
            check=False,
            timeout=15,
        )
        self.assertEqual(result.returncode, -9)

    def test_kill_after_backup_before_replace_retries(self):
        self.crash("apply", "publish")
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertTrue((self.backup / "prepared.json").exists())
        self.assertTrue(self.updater().apply()["changed"])

    def test_kill_after_apply_replace_finalizes(self):
        self.crash("apply", "marker")
        self.assertEqual(self.target.read_bytes(), self.after)
        self.assertFalse((self.backup / "applied.json").exists())
        self.assertFalse(self.updater().apply()["changed"])
        self.assertTrue((self.backup / "applied.json").exists())

    def test_kill_after_restore_replace_finalizes(self):
        self.updater().apply()
        self.crash("restore", "marker")
        self.assertEqual(self.target.read_bytes(), self.before)
        self.assertFalse((self.backup / "restored.json").exists())
        self.assertFalse(self.updater().restore()["changed"])


if __name__ == "__main__":
    unittest.main()
