"""Evaluation-only pause of one verified request relay, with external recovery.

Never signals by process name or port. A pidfd pins the selected process, and
an independent watchdog resumes it on timeout or evaluator pipe closure.
"""
from __future__ import annotations

import hashlib
import ctypes
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import time


class RelayFaultError(RuntimeError):
    pass


def open_pidfd(pid):
    # Some python-build-standalone distributions omit os.pidfd_open although
    # the host kernel/libc provide it. Still use a pidfd, never a PID signal.
    if hasattr(os, 'pidfd_open'):
        return os.pidfd_open(pid)
    libc = ctypes.CDLL(None, use_errno=True)
    function = libc.pidfd_open
    function.argtypes = [ctypes.c_int, ctypes.c_uint]
    function.restype = ctypes.c_int
    descriptor = function(pid, 0)
    if descriptor < 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    os.set_inheritable(descriptor, False)
    return descriptor


def snapshot(pid):
    root = Path('/proc') / str(pid)
    fields = (root / 'stat').read_text().rsplit(') ', 1)[1].split()
    return {'pid': pid, 'uid': root.stat().st_uid, 'state': fields[0],
            'start_ticks': int(fields[19]), 'exe': str((root / 'exe').resolve(strict=True)),
            'cgroup': (root / 'cgroup').read_text()}


def validate_owner(value, *, unit, binary, expected_sha256):
    if (not re.fullmatch(r'siq-qwen38-api-supervisor@[a-f0-9]{16}\.service', unit)
            or value['uid'] != os.geteuid() or value['exe'] != str(binary)
            or value['state'] in {'T', 't', 'Z', 'X'}
            or not value['cgroup'].startswith('0::/')
            or value['cgroup'].count('\n') != 1
            or not value['cgroup'].endswith('/' + unit + '\n')
            or binary.resolve() != binary
            or hashlib.sha256(binary.read_bytes()).hexdigest() != expected_sha256):
        raise RelayFaultError('candidate_relay_owner_invalid')


def discover(*, supervisor_pid, unit, binary, expected_sha256):
    parent = snapshot(supervisor_pid)
    if (parent['uid'] != os.geteuid() or parent['state'] in {'Z', 'X', 'T', 't'}
            or not parent['cgroup'].endswith('/' + unit + '\n')):
        raise RelayFaultError('candidate_relay_supervisor_invalid')
    candidates = []
    for item in Path('/proc').iterdir():
        if not item.name.isdigit():
            continue
        try:
            value = snapshot(int(item.name))
        except (OSError, ValueError, IndexError):
            continue
        if value['cgroup'] == parent['cgroup'] and value['exe'] == str(binary):
            candidates.append(value)
    if len(candidates) != 1:
        raise RelayFaultError('candidate_relay_process_not_unique')
    value = candidates[0]
    validate_owner(value, unit=unit, binary=binary, expected_sha256=expected_sha256)
    return value


WATCHDOG = '''import os,select,signal,sys
pidfd, pipefd, timeout, readyfd = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4])
os.write(readyfd, b'R')
os.close(readyfd)
ready = select.select([pipefd], [], [], timeout)[0]
try:
    signal.pidfd_send_signal(pidfd, signal.SIGCONT)
except ProcessLookupError:
    pass
sys.exit(0 if ready else 23)
'''


class PausedRelay:
    """Caller supplies a freshly discovered identity; all signals use pidfd."""

    def __init__(self, identity, *, timeout=65):
        if not 1 <= timeout <= 70:
            raise RelayFaultError('candidate_relay_watchdog_timeout_invalid')
        self.identity, self.timeout = dict(identity), timeout
        self.pidfd = self.release_fd = self.watchdog = None
        self.pause_requested = False
        self.evidence = {'process': dict(identity), 'watchdog_seconds': timeout}

    def _same(self):
        current = snapshot(self.identity['pid'])
        if any(current[key] != self.identity[key] for key in ('pid', 'uid', 'start_ticks', 'exe', 'cgroup')):
            raise RelayFaultError('candidate_relay_process_changed')
        return current

    def __enter__(self):
        try:
            self.pidfd = open_pidfd(self.identity['pid'])
            if self._same()['state'] in {'T', 't', 'Z', 'X'}:
                raise RelayFaultError('candidate_relay_not_running')
            read_fd, self.release_fd = os.pipe()
            ready_read, ready_write = os.pipe()
            try:
                self.watchdog = subprocess.Popen(
                    [sys.executable, '-c', WATCHDOG, str(self.pidfd), str(read_fd), str(self.timeout), str(ready_write)],
                    pass_fds=(self.pidfd, read_fd, ready_write), stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            finally:
                os.close(read_fd)
                os.close(ready_write)
            try:
                if not select.select([ready_read], [], [], 5)[0] or os.read(ready_read, 1) != b'R':
                    raise RelayFaultError('candidate_relay_watchdog_not_ready')
            finally:
                os.close(ready_read)
            signal.pidfd_send_signal(self.pidfd, signal.SIGSTOP)
            self.pause_requested = True
            self.evidence['pause_requested_unix'] = time.time()
            deadline = time.monotonic() + 2
            while self._same()['state'] not in {'T', 't'}:
                if time.monotonic() >= deadline:
                    raise RelayFaultError('candidate_relay_pause_unconfirmed')
                time.sleep(.01)
            self.evidence['paused_unix'] = time.time()
            self.evidence['paused_state'] = self._same()['state']
            return self
        except BaseException:
            self.close()
            raise

    def assert_paused(self):
        if self.watchdog.poll() is not None or self._same()['state'] not in {'T', 't'}:
            raise RelayFaultError('candidate_relay_fault_window_ended')

    def close(self):
        try:
            if self.pidfd is not None and self.pause_requested:
                try:
                    signal.pidfd_send_signal(self.pidfd, signal.SIGCONT)
                    self.evidence['resume_requested_unix'] = time.time()
                    deadline = time.monotonic() + 2
                    while self._same()['state'] in {'T', 't'} and time.monotonic() < deadline:
                        time.sleep(.01)
                    self.evidence['resumed_state'] = self._same()['state']
                    self.evidence['resumed_unix'] = time.time()
                except (ProcessLookupError, FileNotFoundError):
                    self.evidence['process_exited_before_resume'] = True
        finally:
            if self.release_fd is not None:
                os.close(self.release_fd)
                self.release_fd = None
            if self.watchdog is not None:
                self.evidence['watchdog_exit_code'] = self.watchdog.wait(timeout=5)
            if self.pidfd is not None:
                os.close(self.pidfd)
                self.pidfd = None

    def __exit__(self, *_):
        self.close()
