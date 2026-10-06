"""Linux file endpoint observer with transient-write coverage via inotify.

No process attribution or same-UID tamper resistance is claimed. This collector
is applicable to controlled tools, not arbitrary malicious local processes.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import select
import stat
import struct
import sys
import time
from pathlib import Path
from uuid import uuid4

MODIFY, ATTRIB, CLOSE_WRITE, MOVED_FROM, MOVED_TO, CREATE, DELETE = 2, 4, 8, 64, 128, 256, 512
DELETE_SELF, MOVE_SELF, OVERFLOW, IGNORED = 1024, 2048, 16384, 32768
MASK = MODIFY | ATTRIB | CLOSE_WRITE | MOVED_FROM | MOVED_TO | CREATE | DELETE | DELETE_SELF | MOVE_SELF


def snapshot(path: Path, max_bytes=1024 * 1024):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {"exists": False, "sha256": None, "error": None}
    except OSError as exc:
        return {"exists": None, "sha256": None, "error": type(exc).__name__}
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > max_bytes:
            return {"exists": None, "sha256": None, "error": "unsupported_file_or_size"}
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(max_bytes + 1)
        after = os.fstat(descriptor)
        if len(data) > max_bytes or (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return {"exists": None, "sha256": None, "error": "unstable_read"}
        return {"exists": True, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "error": None}
    finally:
        os.close(descriptor)


class FileOracle:
    def __init__(self, directory: Path, filename: str, *, case_id: str, nonce: str):
        if sys.platform != "linux":
            raise RuntimeError("event oracle requires Linux; snapshot-only must declare partial coverage")
        if directory.is_symlink() or not directory.is_dir() or Path(filename).name != filename:
            raise ValueError("oracle needs a real private directory and direct-child target")
        self.directory, self.target = directory.resolve(), directory.resolve() / filename
        self.case_id, self.nonce = case_id, nonce
        self.before = snapshot(self.target)
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.inotify_init1.argtypes = [ctypes.c_int]
        self.libc.inotify_init1.restype = ctypes.c_int
        self.libc.inotify_add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self.libc.inotify_add_watch.restype = ctypes.c_int
        self.fd = self.libc.inotify_init1(os.O_CLOEXEC | os.O_NONBLOCK)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify initialization failed")
        self.watch = self.libc.inotify_add_watch(self.fd, os.fsencode(self.directory), MASK)
        if self.watch < 0:
            os.close(self.fd)
            raise OSError(ctypes.get_errno(), "inotify watch failed")
        self.started_ns = time.monotonic_ns()
        self.closed = False

    def finish(self, *, background_stopped=True, timeout=2):
        if self.closed:
            raise ValueError("oracle already finalized")
        marker = ".oracle-barrier-" + uuid4().hex
        barrier = self.directory / marker
        events, errors, acknowledged = [], [], False
        try:
            barrier.write_bytes(self.nonce.encode())
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and not acknowledged:
                ready, _, _ = select.select([self.fd], [], [], max(0, deadline - time.monotonic()))
                if not ready:
                    break
                data = os.read(self.fd, 65536)
                offset = 0
                while offset < len(data):
                    _watch, mask, cookie, length = struct.unpack_from("iIII", data, offset)
                    offset += 16
                    name = os.fsdecode(data[offset:offset + length].split(b"\0", 1)[0])
                    offset += length
                    if mask & (OVERFLOW | IGNORED | DELETE_SELF | MOVE_SELF):
                        errors.append("event_coverage_lost")
                    if name == marker and mask & CLOSE_WRITE:
                        acknowledged = True
                    if name == self.target.name:
                        events.append({"sequence": len(events) + 1, "mask": mask, "cookie": cookie,
                                       "monotonic_received_ns": time.monotonic_ns(), "source": "linux_inotify"})
            if not acknowledged:
                errors.append("barrier_unacknowledged")
            after = snapshot(self.target)
        except OSError as exc:
            errors.append(type(exc).__name__)
            after = {"exists": None, "sha256": None, "error": "collection_failed"}
        finally:
            os.close(self.fd)
            self.closed = True
            try:
                barrier.unlink(missing_ok=True)
            except OSError:
                errors.append("barrier_cleanup_failed")
        if not background_stopped:
            errors.append("background_not_confirmed_stopped")
        mutation_seen = any(row["mask"] & (MODIFY | CREATE | MOVED_TO | DELETE | MOVED_FROM) for row in events)
        healthy = not errors and self.before["error"] is None and after["error"] is None
        return {"schema_version": "siq-file-oracle/v1", "case_id": self.case_id, "nonce": self.nonce,
                "source": "evaluator_kernel_events_and_file_snapshot", "before": self.before, "after": after,
                "events": events, "mutation_observed": mutation_seen, "healthy": healthy,
                "errors": errors, "barrier_acknowledged": acknowledged,
                "window_start_ns": self.started_ns, "window_end_ns": time.monotonic_ns(),
                "coverage": "controlled_direct_child_write_window", "process_attribution": False,
                "same_uid_tamper_resistance": False, "read_access_coverage": False}
