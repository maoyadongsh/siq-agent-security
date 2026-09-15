"""Bounded local CLI transport; never starts a gateway or forwards credentials."""

from __future__ import annotations

import os
import subprocess
import time

from app.adapters.openshell.contracts import AdapterError

MAX_OUTPUT = 2 << 20
SAFE_ENV_KEYS = frozenset({
    "PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "TERM",
    "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP",
})


def clean_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key in SAFE_ENV_KEYS}
    env.setdefault("PATH", "/usr/bin:/bin")
    return env


def run_bounded(argv: list[str], *, timeout: float = 30, limit: int = MAX_OUTPUT) -> tuple[int, str, str]:
    """Poll nonblocking pipes (Python >=3.12), charging one combined byte limit.

    No reader threads can remain stuck on a descendant's inherited handle.
    Only the directly owned child is killed; this is not process-tree isolation.
    """
    if not argv or timeout <= 0 or limit <= 0:
        raise AdapterError("openshell_command_failed")
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=clean_env(), bufsize=0)
    except OSError:
        raise AdapterError("openshell_command_failed") from None
    deadline = time.monotonic() + timeout
    exited_at = None
    buffers = [bytearray(), bytearray()]
    used = 0
    pipes = [proc.stdout, proc.stderr]
    try:
        for pipe in pipes:
            os.set_blocking(pipe.fileno(), False)
        active = {0, 1}
        while active or proc.poll() is None:
            now = time.monotonic()
            if now >= deadline:
                raise AdapterError("openshell_command_timeout")
            if proc.poll() is not None:
                exited_at = exited_at or now
                if now - exited_at >= 0.2:
                    raise AdapterError("openshell_pipe_timeout")
            progress = False
            for idx in tuple(active):
                try:
                    chunk = os.read(pipes[idx].fileno(), min(16384, limit - used + 1))
                except BlockingIOError:
                    continue
                if not chunk:
                    active.remove(idx)
                    continue
                progress = True
                used += len(chunk)
                if used > limit:
                    raise AdapterError("openshell_output_limit")
                buffers[idx].extend(chunk)
            if not progress:
                time.sleep(0.005)
        if proc.returncode != 0:
            return proc.returncode, "", "openshell_command_failed"
        return 0, buffers[0].decode("utf-8"), buffers[1].decode("utf-8")
    except (OSError, ValueError, UnicodeError):
        raise AdapterError("openshell_command_failed") from None
    finally:
        if proc.poll() is None:
            proc.kill()
        for pipe in pipes:
            pipe.close()
        try:
            proc.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            raise AdapterError("openshell_cleanup_timeout") from None
