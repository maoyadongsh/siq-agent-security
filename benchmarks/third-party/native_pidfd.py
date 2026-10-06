"""Bounded, immediate SIGKILL of a verified owned process on Linux pidfd ABIs."""
import ctypes
import hashlib
import os
import platform
import signal
from pathlib import Path

from process_resources import identity


def kill_owned(ref, command_sha256):
    # Python builds can omit os.pidfd_open and signal.pidfd_send_signal.
    # These syscall numbers match the existing process_resources reconciler.
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'aarch64'):
        raise ValueError('native crash pidfd ABI unavailable')
    if identity(ref['pid']) != ref:
        raise ValueError('owned process identity changed')
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long

    def syscall(number, *args):
        value = libc.syscall(ctypes.c_long(number), *(ctypes.c_long(x) for x in args))
        if value < 0:
            raise OSError(ctypes.get_errno(), 'owned native crash pidfd syscall failed')
        return value

    fd = syscall(434, ref['pid'], 0)
    try:
        if identity(ref['pid']) != ref or hashlib.sha256(Path(f"/proc/{ref['pid']}/cmdline").read_bytes()).hexdigest() != command_sha256:
            raise ValueError('owned process identity/command changed after pidfd acquisition')
        syscall(424, fd, signal.SIGKILL, 0, 0)
    finally:
        os.close(fd)
