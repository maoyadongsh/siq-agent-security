"""Linux owned-process reconciliation; pidfd prevents signalling a reused PID."""
import ctypes
import errno
import hashlib
import os
import platform
import select
import signal
from pathlib import Path

from lifecycle import process_state


def identity(pid):
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return {"pid": pid, "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(), "start_ticks": fields[19]}


def members(pgid, exclude=()):
    rows = []
    for p in Path("/proc").iterdir():
        if not p.name.isdigit() or int(p.name) in exclude:
            continue
        try:
            f = (p / "stat").read_text().rsplit(")", 1)[1].split()
            if int(f[2]) == pgid and f[0] != "Z":
                rows.append({"pid": int(p.name), "start_ticks": f[19]})
        except (FileNotFoundError, ProcessLookupError):
            continue
    return sorted(rows, key=lambda row: row["pid"])


def stop_owned(ref, command_sha256):
    before = process_state(ref)
    result = {"identity": ref, "before": before, "signalled": False}
    if before != "alive":
        return {**result, "stopped": True, "after": before}
    # Numbers verified against this host's asm-generic/unistd.h. Refuse other ABIs.
    if platform.machine() not in ("aarch64", "x86_64"):
        raise ValueError("pidfd reconciliation ABI unsupported")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long

    def syscall(number, *args):
        value = libc.syscall(ctypes.c_long(number), *(ctypes.c_long(a) for a in args))
        if value < 0:
            raise OSError(ctypes.get_errno(), "owned pidfd operation failed")
        return value

    try:
        fd = syscall(434, ref["pid"], 0)
    except OSError as exc:
        if exc.errno == errno.ESRCH and process_state(ref) != "alive":
            return {**result, "stopped": True, "after": process_state(ref)}
        raise
    try:
        if process_state(ref) != "alive":
            return {**result, "stopped": True, "after": process_state(ref)}
        if hashlib.sha256(Path(f"/proc/{ref['pid']}/cmdline").read_bytes()).hexdigest() != command_sha256:
            return {**result, "stopped": False, "after": "command_identity_differs"}
        syscall(424, fd, signal.SIGTERM, 0, 0)
        result["signalled"] = True
        if not select.select([fd], [], [], 8)[0]:
            syscall(424, fd, signal.SIGKILL, 0, 0)
        exited = bool(select.select([fd], [], [], 5)[0])
        return {**result, "stopped": exited, "after": process_state(ref)}
    finally:
        os.close(fd)
