"""Trusted host lifecycle composition; not a public registration endpoint."""

import datetime
import math
import os
import threading
import time

from .host_online import DecisionRelay, HostLoop, OnlineError, Publisher, Verifier, _key
from .host_openshell import OpenShellBackend
from .host_runtime import RuntimeGuard
from .native_channel import NamespaceHostChannel, ProcessPin


def _failure():
    return OnlineError("native_host_session_unavailable")


def _remaining(value, maximum):
    if type(value) is not datetime.datetime or value.tzinfo is not datetime.UTC:
        raise _failure()
    seconds = (value - datetime.datetime.now(datetime.UTC)).total_seconds()
    if not 0 < seconds <= maximum:
        raise _failure()
    return seconds


class BusinessGuard:
    """A supervisor's short authorization window around the actual runtime guard."""

    def __init__(self, guard, *, supervisor_pid, expires_at, authorization_expires_at):
        self._process, self._pin = os.getpid(), None
        self._lock, self._stopped = threading.Lock(), threading.Event()
        self._guard = guard
        self._expires = expires_at
        self._until = time.monotonic() + _remaining(expires_at, 3600)
        self._supervisor = supervisor_pid
        try:
            if (type(supervisor_pid) is not int or supervisor_pid <= 0
                    or os.stat(f"/proc/{supervisor_pid}").st_uid != os.getuid()):
                raise _failure()
            self._pin = ProcessPin(supervisor_pid, os.getuid())
            self._set_window(authorization_expires_at)
            self.verify()
        except BaseException:  # noqa: BLE001 - release the owned pin on cancellation too.
            self.close()
            raise _failure() from None

    @property
    def artifact(self):
        return self._guard.artifact

    @property
    def peer(self):
        return self._guard.peer

    def _set_window(self, expires):
        remaining = _remaining(expires, 90)
        if expires > self._expires:
            raise _failure()
        self._authorization_expires = expires
        self._authorization_until = time.monotonic() + remaining

    def _check_locked(self):
        if (self._stopped.is_set() or self._pin is None
                or time.monotonic() >= min(self._until, self._authorization_until)
                or datetime.datetime.now(datetime.UTC) >= min(self._expires, self._authorization_expires)):
            raise _failure()
        self._pin.check()

    def _check(self):
        if os.getpid() != self._process:
            raise _failure()
        try:
            with self._lock:
                self._check_locked()
        except Exception:  # noqa: BLE001 - expiration or lost owner is terminal.
            self._stopped.set()
            raise _failure() from None

    def renew(self, *, supervisor_pid, authorization_expires_at):
        if os.getpid() != self._process:
            raise _failure()
        try:
            with self._lock:
                self._check_locked()
                if type(supervisor_pid) is not int or supervisor_pid != self._supervisor:
                    raise _failure()
                self._set_window(authorization_expires_at)
                self._check_locked()
        except Exception:  # noqa: BLE001 - no revival after bad control or stale heartbeat.
            self._stopped.set()
            raise _failure() from None

    def verify(self):
        self._check()
        try:
            self._guard.verify()
        except Exception:  # noqa: BLE001 - keep business wrapper terminal too.
            self._stopped.set()
            raise _failure() from None
        self._check()

    def verify_mount(self, source, target):
        self._check()
        try:
            self._guard.verify_mount(source, target)
        except Exception:  # noqa: BLE001 - source verification failure is terminal.
            self._stopped.set()
            raise _failure() from None
        self._check()

    def stop(self):
        if os.getpid() != self._process:
            raise _failure()
        self._stopped.set()

    def close(self):
        self.stop()
        with self._lock:
            if self._pin is not None:
                self._pin.close()
                self._pin = None
        self._guard.close()


class HostSession:
    """Own one runtime's resources while borrowing the host's shared Verifier."""

    def __init__(self, verifier, endpoint):
        if not isinstance(verifier, Verifier):
            raise _failure()
        self._process = os.getpid()
        self._verifier, self._endpoint = verifier, endpoint
        self._lock, self._stopped = threading.RLock(), threading.Event()
        self._attempted = False
        self._guard = self._fence = self._directory = self._channel = self._loop = None

    def start(self, *, backend, runtime, subject, installs, channel_directory, credential,
              supervisor_pid, expires_at, authorization_expires_at):
        if os.getpid() != self._process:
            raise _failure()
        with self._lock:
            if self._attempted or self._stopped.is_set():
                raise _failure()
            self._attempted = True
            try:
                _remaining(expires_at, 3600)
                _remaining(authorization_expires_at, 90)
                _key(subject)
                expected = {"pid", "uid", "gid", "artifact_sha256", "executable_sha256", "argv_sha256",
                            "mounts", "code_files", "image_files", "image_skill_roots"}
                if ("task_id" in subject or type(backend) is not dict or type(runtime) is not dict
                        or set(runtime) != expected or runtime["mounts"] != [] or runtime["code_files"] != {}
                        or any(runtime[k] != backend.get(k) for k in ("pid", "uid", "gid", "artifact_sha256"))):
                    raise _failure()
                actual_backend = OpenShellBackend(**backend)
                self._guard = RuntimeGuard(**runtime, verify_backend=actual_backend)
                self._fence = BusinessGuard(self._guard, supervisor_pid=supervisor_pid,
                    expires_at=expires_at, authorization_expires_at=authorization_expires_at)
                if self._stopped.is_set():
                    raise _failure()
                # Registration does not renew the caller's absolute lease.
                seconds = math.floor(_remaining(expires_at, 3600))
                self._verifier.register(subject, self._fence, installs, lifetime=seconds)
                publisher = Publisher(self._verifier.config_path, self._endpoint, subject, self._fence)
                relay = DecisionRelay(publisher, credential)
                directory = self._guard.namespace_channel_directory(channel_directory)
                fd = directory.__enter__()
                self._directory = directory
                self._channel = NamespaceHostChannel(fd, self._guard.peer, timeout=5)
                self._loop = HostLoop(self._channel, relay, expires_at=expires_at)
                if self._stopped.is_set():
                    raise _failure()
                self._loop.start()
                return self
            except BaseException:  # noqa: BLE001 - cleanup only this session's acquired resources.
                self.close()
                raise _failure() from None

    def assert_running(self):
        if os.getpid() != self._process or self._stopped.is_set() or self._loop is None:
            raise _failure()
        self._loop.assert_running()

    def renew(self, *, supervisor_pid, authorization_expires_at):
        if os.getpid() != self._process or self._stopped.is_set() or self._fence is None:
            raise _failure()
        self._fence.renew(supervisor_pid=supervisor_pid, authorization_expires_at=authorization_expires_at)

    def close(self):
        if os.getpid() != self._process:
            raise _failure()
        self._stopped.set()
        if self._fence is not None:
            self._fence.stop()
        with self._lock:
            # A still-running worker must keep its directory and guard alive.
            # A later close can confirm exit and finish resource cleanup.
            if self._loop is not None:
                self._loop.close()
            if self._channel is not None:
                self._channel.close()
                self._channel = None
            try:
                if self._directory is not None:
                    directory, self._directory = self._directory, None
                    directory.__exit__(None, None, None)
            finally:
                if self._fence is not None:
                    self._fence.close()
                elif self._guard is not None:
                    self._guard.close()

    def __enter__(self):
        self.assert_running()
        return self

    def __exit__(self, *_):
        self.close()
