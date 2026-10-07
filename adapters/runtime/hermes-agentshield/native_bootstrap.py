"""One protected image bootstrap per process; never an authorizer or launcher.

The owning host must independently verify the image, argv, process and this
module. Ready/configured only describe startup coordination, not permission.
"""

# ruff: noqa: BLE001 - cancellation also closes bootstrap; only fixed errors escape.

from __future__ import annotations

import math
import os
import re
import stat
import sys
import threading
import time
from pathlib import Path

from . import native_dispatch
from .native_channel import HermesChannel
from .native_online import Callbacks

_process = os.getpid()
_attempted = False
_lock = threading.Lock()


class BootstrapError(RuntimeError):
    pass


def _failure():
    return BootstrapError("native_runtime_bootstrap_unavailable")


def _claim():
    global _attempted
    # A fork must not wait on a lock inherited from a vanished parent thread.
    if os.getpid() != _process:
        raise _failure()
    with _lock:
        if _attempted:
            raise _failure()
        _attempted = True


class ImageBootstrap:
    def __init__(self, agent_id, session_namespace, channel_directory):
        _claim()
        self._nodes, self._state = [], "preparing"
        self._lock = threading.RLock()
        self._pid = os.getpid()
        self._uid, self._gid = None, None
        self._channel, self._endpoint_identity = None, None
        try:
            if sys.platform != "linux":
                raise _failure()
            self._uid, self._gid = os.getuid(), os.getgid()
            if (self._uid <= 0 or self._gid <= 0
                    or os.geteuid() != self._uid or os.getegid() != self._gid
                    or type(agent_id) is not str or not re.fullmatch(r"hri-[a-f0-9]{32}", agent_id)
                    or not native_dispatch.valid_session_namespace(session_namespace)
                    or type(channel_directory) is not str or not channel_directory.startswith("/")
                    or "\\" in channel_directory or any(ord(c) < 32 or ord(c) == 127 for c in channel_directory)):
                raise _failure()
            parts = channel_directory.split("/")[1:]
            if (not 1 <= len(parts) <= 128 or any(p in ("", ".", "..") for p in parts)
                    or len((channel_directory + "/native-host.sock").encode("utf-8")) > 107):
                raise _failure()
            self._agent, self._namespace, self._directory = agent_id, session_namespace, channel_directory
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            root = os.open("/", flags)
            self._nodes.append((root, None, None, os.fstat(root)))
            self._check(leaf=False)
            for index, name in enumerate(parts):
                parent = self._nodes[-1][0]
                if index == len(parts) - 1:
                    os.mkdir(name, 0o700, dir_fd=parent)  # Never reuse an existing directory.
                fd = os.open(name, flags, dir_fd=parent)
                self._nodes.append((fd, parent, name, os.fstat(fd)))
                self._check(leaf=False)
            self._state = "prepared"
            self._check()
        except BaseException:
            self.close()
            raise _failure() from None

    def _check(self, *, leaf=True):
        if (os.getpid() != self._pid or self._state == "closed" or not self._nodes
                or os.getuid() != self._uid or os.geteuid() != self._uid
                or os.getgid() != self._gid or os.getegid() != self._gid):
            raise _failure()
        for fd, parent, name, before in self._nodes:
            info = os.fstat(fd)
            path = os.stat(name, dir_fd=parent, follow_symlinks=False) if parent is not None else os.stat("/", follow_symlinks=False)
            if (not os.path.samestat(before, info) or not os.path.samestat(before, path)
                    or not stat.S_ISDIR(info.st_mode) or not stat.S_ISDIR(path.st_mode)
                    or os.get_inheritable(fd) or info.st_uid not in (0, self._uid)):
                raise _failure()
            sticky_root = info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if info.st_mode & 0o022 and not sticky_root:
                raise _failure()
        info = os.fstat(self._nodes[-1][0])
        if leaf and (info.st_uid != self._uid or info.st_gid != self._gid or stat.S_IMODE(info.st_mode) != 0o700):
            raise _failure()

    def _endpoint(self):
        info = os.stat("native-host.sock", dir_fd=self._nodes[-1][0], follow_symlinks=False)
        if (not stat.S_ISSOCK(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != self._uid or info.st_gid != self._gid or info.st_nlink != 1
                or self._endpoint_identity is not None and not os.path.samestat(self._endpoint_identity, info)):
            raise _failure()
        return info

    def ready(self):
        # Metadata is a locating hint. The host does not trust the advertised PID.
        if os.getpid() != self._pid:
            raise _failure()
        with self._lock:
            try:
                self._check()
                return {"schema_version": "native-runtime-bootstrap-ready/v1", "pid": self._pid,
                        "uid": self._uid, "gid": self._gid, "agent_id": self._agent,
                        "session_namespace": self._namespace, "channel_directory": self._directory,
                        "runtime_state": "unverified"}
            except BaseException:
                self.close()
                raise _failure() from None

    def configure(self, *, timeout=30):
        if os.getpid() != self._pid:
            raise _failure()
        try:
            with self._lock:
                self._check()
                if (self._state != "prepared" or type(timeout) not in (int, float)
                        or not math.isfinite(timeout) or not 0 < timeout <= 60):
                    raise _failure()
                self._state = "waiting"
            deadline = time.monotonic() + timeout
            while True:
                with self._lock:
                    self._check()
                    try:
                        self._endpoint_identity = self._endpoint()
                        break
                    except FileNotFoundError:
                        pass
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _failure()
                time.sleep(min(.05, remaining))
            with self._lock:
                self._check()
                self._endpoint()
                self._channel = HermesChannel(Path(self._directory) / "native-host.sock", timeout=5,
                                              server_credentials=(0, self._uid, self._gid))
                callbacks = Callbacks.via_host(self)
                runtime = native_dispatch.Runtime(self._agent, self._namespace, callbacks.observe,
                                                  callbacks.authorize, callbacks.observe)
                native_dispatch.configure(runtime)
                self._state = "configured"
        except BaseException:
            self.close()
            raise _failure() from None

    def exchange(self, event):
        # Concurrent tasks share the channel's own bounded, sequenced exchange.
        # Keep the descriptor lock out of that wait so close can invalidate now.
        if os.getpid() != self._pid:
            raise _failure()
        try:
            with self._lock:
                self._check()
                self._endpoint()
                if self._state != "configured":
                    raise _failure()
            result = self._channel.exchange(event)
            with self._lock:
                self._check()
                self._endpoint()
            return result
        except BaseException:
            self.close()
            raise _failure() from None

    def close(self):
        # Never acquire a potentially inherited lock in a forked child.
        if os.getpid() != self._pid:
            raise _failure()
        with self._lock:
            self._state = "closed"
            for fd, _, _, _ in reversed(self._nodes):
                os.close(fd)
            self._nodes.clear()
