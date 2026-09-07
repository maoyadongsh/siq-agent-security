#!/usr/bin/env python3
"""Inspect/apply/restore the pinned OpenClaw checkpoint-v2 patch (POSIX writes).

Explicit paths only. Stop the target runtime before apply/restore, and restart
afterward. Disk inspection does not attest to code already loaded in a process.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "patches/openclaw/2026.5.12-approval-execution-recheck-v2.json"
PATCH = ROOT / "patches/openclaw/2026.5.12-approval-execution-recheck-v2.patch"


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular(path):
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
        "regular_unlinked_file_required",
    )
    require(path.resolve() == path, "symlink_path_rejected")
    return info


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def append_file(path, content):
    if path.exists() or path.is_symlink():
        regular(path)
        require(path.read_bytes() == content, "backup_record_conflict")
        return
    fd, temporary_name = tempfile.mkstemp(
        prefix=".siq-record-", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            regular(path)
            require(path.read_bytes() == content, "backup_record_conflict")
        sync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class Updater:
    def __init__(self, runtime, backup=None, *, profile=None, patch=None):
        self.runtime = Path(runtime).resolve()
        self.profile = (
            profile if profile is not None else json.loads(PROFILE.read_text())
        )
        self.patch = PATCH.read_bytes() if patch is None else patch
        relative = Path(self.profile["target"])
        require(
            not relative.is_absolute() and ".." not in relative.parts,
            "invalid_profile_target",
        )
        self.target = self.runtime / relative
        self.backup = Path(backup).absolute() if backup is not None else None
        self.validate()

    def validate(self):
        regular(self.runtime / "package.json")
        package = json.loads((self.runtime / "package.json").read_text())
        require(
            package.get("name") == self.profile["package"]
            and package.get("version") == self.profile["version"],
            "unsupported_package_version",
        )
        regular(self.target)
        require(
            self.target.resolve().is_relative_to(self.runtime), "target_outside_runtime"
        )
        require(
            digest(self.patch) == self.profile["patch_sha256"],
            "patch_checksum_mismatch",
        )

    def state(self):
        self.validate()
        current = digest(self.target.read_bytes())
        if current == self.profile["before_sha256"]:
            return "stock"
        if current == self.profile["after_sha256"]:
            return "checkpoint-v2"
        return "modified"

    @contextlib.contextmanager
    def locked(self):
        require(os.name == "posix", "posix_locking_required")
        import fcntl

        lock = self.target.parent / ".siq-approval-checkpoint.lock"
        fd = os.open(
            lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
        )
        try:
            info = os.fstat(fd)
            require(
                stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "invalid_lock_file"
            )
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("upgrade_already_running") from None
            yield
        finally:
            os.close(
                fd
            )  # Kernel releases the lock even if a previous process was killed.

    def backup_record(self, *, create):
        backup = self.backup
        require(backup is not None, "backup_dir_required")
        require(
            backup.resolve() == backup and not backup.is_relative_to(self.runtime),
            "independent_backup_required",
        )
        if create:
            backup.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(
            backup.is_dir() and not backup.is_symlink(), "backup_directory_required"
        )
        require(
            stat.S_IMODE(backup.stat().st_mode) == 0o700,
            "private_backup_directory_required",
        )
        require(
            {
                p.name
                for p in backup.iterdir()
                if not (p.name.startswith(".siq-record-") and p.name.endswith(".tmp"))
            }
            <= {"original.js", "prepared.json", "applied.json", "restored.json"},
            "backup_directory_not_owned",
        )
        info = regular(self.target)
        record = {
            "schema": "openclaw-checkpoint-backup/v1",
            "runtime": str(self.runtime),
            "target": self.profile["target"],
            "before_sha256": self.profile["before_sha256"],
            "after_sha256": self.profile["after_sha256"],
            "mode": stat.S_IMODE(info.st_mode),
            "uid": info.st_uid,
            "gid": info.st_gid,
        }
        encoded = (json.dumps(record, sort_keys=True) + "\n").encode()
        original = backup / "original.js"
        if create and self.state() == "stock":
            append_file(original, self.target.read_bytes())
            append_file(backup / "prepared.json", encoded)
        regular(original)
        regular(backup / "prepared.json")
        require(
            digest(original.read_bytes()) == record["before_sha256"],
            "backup_checksum_mismatch",
        )
        require(
            (backup / "prepared.json").read_bytes() == encoded,
            "backup_identity_or_metadata_mismatch",
        )
        for operation in ("applied", "restored"):
            marker = backup / f"{operation}.json"
            if marker.exists() or marker.is_symlink():
                regular(marker)
                expected = (json.dumps({"operation": operation}) + "\n").encode()
                require(marker.read_bytes() == expected, "backup_record_conflict")
        return record, original.read_bytes()

    def publish(self, content, expected):
        info = regular(self.target)
        fd, name = tempfile.mkstemp(prefix=".siq-checkpoint-", dir=self.target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fchown(stream.fileno(), info.st_uid, info.st_gid)
                os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
                os.fsync(stream.fileno())
            regular(self.target)
            require(
                digest(self.target.read_bytes()) == expected,
                "runtime_changed_before_replace",
            )
            os.replace(temporary, self.target)
            sync_dir(self.target.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def patched_bytes(self, original):
        with tempfile.TemporaryDirectory(prefix="siq-checkpoint-payload-") as temporary:
            root = Path(temporary)
            target = root / self.profile["target"]
            target.parent.mkdir(parents=True)
            target.write_bytes(original)
            patch = root / "payload.patch"
            patch.write_bytes(self.patch)
            for arguments in (["--check"], []):
                result = subprocess.run(
                    ["git", "apply", *arguments, str(patch)],
                    cwd=root,
                    capture_output=True,
                    check=False,
                )
                require(result.returncode == 0, "patch_application_failed")
            result = target.read_bytes()
        require(
            digest(result) == self.profile["after_sha256"], "patched_checksum_mismatch"
        )
        return result

    def marker(self, operation):
        append_file(
            self.backup / f"{operation}.json",
            (json.dumps({"operation": operation}) + "\n").encode(),
        )

    def apply(self):
        with self.locked():
            current = self.state()
            require(current != "modified", "modified_runtime_rejected")
            _, original = self.backup_record(create=current == "stock")
            require(
                not (self.backup / "restored.json").exists(),
                "fresh_backup_required_after_restore",
            )
            if current == "stock":
                require(
                    not (self.backup / "applied.json").exists(),
                    "restore_finalization_required",
                )
                self.publish(
                    self.patched_bytes(original), self.profile["before_sha256"]
                )
            self.marker("applied")
            return {
                "status": "checkpoint-v2",
                "changed": current == "stock",
                "restart_required": True,
                "disk_only": True,
            }

    def restore(self):
        with self.locked():
            current = self.state()
            require(current != "modified", "modified_runtime_rejected")
            _, original = self.backup_record(create=False)
            if current == "checkpoint-v2":
                self.publish(original, self.profile["after_sha256"])
            self.marker("restored")
            return {
                "status": "stock",
                "changed": current != "stock",
                "restart_required": True,
                "disk_only": True,
            }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["inspect", "apply", "restore"])
    parser.add_argument("--openclaw-root", type=Path, required=True)
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    updater = Updater(args.openclaw_root, args.backup_dir)
    if args.operation == "inspect":
        result = {"status": updater.state(), "disk_only": True}
    else:
        result = getattr(updater, args.operation)()
    print(json.dumps(result))
    return 1 if result["status"] == "modified" else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (
        RuntimeError,
        OSError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
    ) as exc:
        print(
            json.dumps(
                {
                    "error": str(exc)
                    if isinstance(exc, RuntimeError)
                    else type(exc).__name__
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)
