"""Owned one-shot scan process: bounded pipes, wall time and process-group cleanup."""
from __future__ import annotations

import os
import signal
import subprocess
import time


class ScanFailure(Exception):
    """Only fixed categories cross the API boundary."""


def exchange(argv, payload, *, timeout=5.0, output_limit=2 * 1024 * 1024):
    if os.name != "posix":
        raise ScanFailure("threat_scan_isolation_unavailable")
    try:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env={"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin"},
                                   start_new_session=True, bufsize=0)
    except OSError:
        raise ScanFailure("threat_scan_isolation_unavailable") from None
    output = bytearray()
    used, written = 0, 0
    deadline = time.monotonic() + timeout
    readers = {process.stdout, process.stderr}
    try:
        for pipe in (process.stdin, process.stdout, process.stderr):
            os.set_blocking(pipe.fileno(), False)
        while readers or process.poll() is None:
            if time.monotonic() >= deadline:
                raise ScanFailure("threat_scan_timeout")
            progress = False
            if not process.stdin.closed:
                try:
                    written += os.write(process.stdin.fileno(), payload[written:written + 16384])
                    progress = True
                    if written == len(payload):
                        process.stdin.close()
                except BlockingIOError:
                    pass
                except BrokenPipeError:
                    process.stdin.close()
            for pipe in tuple(readers):
                try:
                    chunk = os.read(pipe.fileno(), min(16384, output_limit - used + 1))
                except BlockingIOError:
                    continue
                progress = True
                if not chunk:
                    readers.remove(pipe)
                    continue
                used += len(chunk)
                if used > output_limit:
                    raise ScanFailure("threat_scan_output_limit")
                if pipe is process.stdout:
                    output.extend(chunk)
            if not progress:
                time.sleep(0.005)
        if process.returncode != 0 or written != len(payload):
            raise ScanFailure("threat_scan_worker_failed")
        return bytes(output)
    except (OSError, ValueError):
        raise ScanFailure("threat_scan_transport_failed") from None
    finally:
        # Reap the owned group even if the leader has exited leaving inherited pipes.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        for pipe in (process.stdin, process.stdout, process.stderr):
            pipe.close()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            raise ScanFailure("threat_scan_cleanup_failed") from None
