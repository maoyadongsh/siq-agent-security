"""Linux-only native-host metadata transport (ADR-056); not an authorizer.

The trusted launcher must pin the real Hermes process and protect its code and
the socket mount. No model claim selects the peer. Not installed/enabled by the
legacy plugin. Application event validation remains the dispatcher's job.
"""

from __future__ import annotations

import array
import ctypes
import json
import math
import os
import select
import socket
import stat
import struct
import sys
import threading
from pathlib import Path

MAX_PACKET = 65536
MAX_SEQUENCE = 9007199254740991
_CREDENTIALS = struct.Struct("3i")


class ChannelError(RuntimeError):
    """Value-free failure: do not log a raw payload or OS exception."""


class ChannelIdle(ChannelError):
    """No connection accepted; no request or sequence was consumed."""


def _failure():
    return ChannelError("native_host_channel_unavailable")


def _linux():
    if sys.platform != "linux" or not all(hasattr(socket, name) for name in (
        "SOCK_SEQPACKET", "SO_PASSCRED", "SCM_CREDENTIALS",
    )):
        raise _failure()


def _timeout(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 5:
        raise _failure()
    return value


def _pidfd_open(pid):
    if hasattr(os, "pidfd_open"):
        return os.pidfd_open(pid)
    # Some Linux Python builds omit the wrapper; never fall back to a numeric
    # PID liveness test that could accept a replacement process.
    libc = ctypes.CDLL(None, use_errno=True)
    opener = libc.pidfd_open
    opener.argtypes = (ctypes.c_int, ctypes.c_uint)
    opener.restype = ctypes.c_int
    fd = opener(pid, 0)
    if fd < 0:
        raise _failure()
    return fd


class ProcessPin:
    """Pinned by a trusted launcher, not an identity supplied in a message."""

    def __init__(self, pid: int, uid: int):
        _linux()
        if type(pid) is not int or not 0 < pid <= 2147483647 or type(uid) is not int or uid <= 0:
            raise _failure()
        self.pid, self.uid, self._fd = pid, uid, None
        try:
            self._fd = _pidfd_open(pid)
            os.set_inheritable(self._fd, False)
            self.check()
        except (OSError, AttributeError, ChannelError):
            self.close()
            raise _failure() from None

    def check(self):
        if self._fd is None:
            raise _failure()
        try:
            if select.select([self._fd], [], [], 0)[0]:
                raise _failure()
        except (OSError, ValueError):
            raise _failure() from None

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self):
        self.check()
        return self

    def __exit__(self, *_):
        self.close()


def _unique(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise _failure()
    return value


def _encode(value):
    try:
        raw = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()
    except (ValueError, TypeError, RecursionError):
        raise _failure() from None
    if not 0 < len(raw) <= MAX_PACKET:
        raise _failure()
    return raw


def _frame(raw, field, version):
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        if (type(value) is not dict or set(value) != {"schema_version", "sequence", field}
                or value["schema_version"] != version or type(value["sequence"]) is not int
                or not 1 <= value["sequence"] <= MAX_SEQUENCE
                or type(value[field]) is not dict or len(value[field]) > 32):
            raise _failure()
        _encode(value)  # Also rejects infinities, NaN, recursion and output inflation.
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise _failure() from None


def _receive(connection):
    raw, ancillary, flags, _ = connection.recvmsg(MAX_PACKET, socket.CMSG_SPACE(_CREDENTIALS.size))
    credentials, extra = [], False
    for level, kind, data in ancillary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
            # Received descriptors are installed in this process even when the
            # message is rejected. Close all delivered descriptors immediately.
            fds = array.array("i")
            fds.frombytes(data[:len(data) - len(data) % fds.itemsize])
            for fd in fds:
                os.close(fd)
            extra = True
        elif level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS and len(data) == _CREDENTIALS.size:
            credentials.append(_CREDENTIALS.unpack(data))
        else:
            extra = True
    if not raw or flags or extra or len(credentials) != 1:
        raise _failure()
    return raw, credentials[0]


class HostChannel:
    """One launcher's bounded listener, with kernel authentication per packet.

    Calls are serialized, including dispatch and sequence consumption. A
    dispatcher must validate the application event and bound its own work;
    socket timeouts do not cancel it.
    """

    def __init__(self, directory: Path, peer: ProcessPin, timeout=2):
        _linux()
        self._socket, self._inode = None, None
        self._lock = threading.Lock()
        self._peer, self._sequence, self._timeout = peer, 1, _timeout(timeout)
        self.path = Path(directory) / "native-host.sock"
        try:
            peer.check()
            info = Path(directory).lstat()
            if (not self.path.is_absolute() or Path(directory).resolve(strict=True) != Path(directory)
                    or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) != 0o700):
                raise _failure()
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            self._socket.settimeout(self._timeout)
            self._socket.bind(str(self.path))  # Never remove/overwrite a prior socket.
            self._inode = self.path.lstat()
            self.path.chmod(0o600)
            self._socket.listen(8)
        except (OSError, ValueError, ChannelError):
            self.close()
            raise _failure() from None

    def serve_once(self, dispatch):
        with self._lock:
            self._serve_once(dispatch)

    def _serve_once(self, dispatch):
        self._peer.check()
        if self._socket is None:
            raise _failure()
        try:
            connection, _ = self._socket.accept()
        except TimeoutError:
            raise ChannelIdle("native_host_channel_idle") from None
        except OSError:
            raise _failure() from None
        try:
            with connection:
                connection.settimeout(self._timeout)
                raw, (pid, uid, _) = _receive(connection)
                self._peer.check()
                if (pid, uid) != (self._peer.pid, self._peer.uid):
                    raise _failure()
                frame = _frame(raw, "event", "native-host-event/v1")
                if frame["sequence"] != self._sequence:
                    raise _failure()
                self._sequence += 1  # Consumed before dispatch, including uncertain failure.
                result = dispatch(frame["event"])
                self._peer.check()
                response = _encode({"schema_version": "native-host-response/v1", "sequence": frame["sequence"], "result": result})
                _frame(response, "result", "native-host-response/v1")
                if connection.send(response) != len(response):
                    raise _failure()
        except Exception:  # noqa: BLE001 - redact arbitrary dispatcher failures at this boundary.
            # Never return application exceptions, parameters or OS paths.
            raise _failure() from None

    def close(self):
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._inode is not None:
            try:
                current = self.path.lstat()
                if stat.S_ISSOCK(current.st_mode) and os.path.samestat(self._inode, current):
                    self.path.unlink()
            except OSError:
                pass  # An unavailable/changed path is not permission to remove another object.
            self._inode = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class NamespaceHostChannel(HostChannel):
    """Listener in a runtime directory already verified by RuntimeGuard.

    The trusted launcher supplies an open directory, never an arbitrary model
    path. The duplicate descriptor pins the directory across path replacement.
    The image-profile client must authenticate every response's credentials.
    """

    def __init__(self, directory_fd: int, peer: ProcessPin, timeout=2):
        _linux()
        self._socket, self._inode, self._directory_fd = None, None, None
        self._lock = threading.Lock()
        self._peer, self._sequence, self._timeout = peer, 1, _timeout(timeout)
        try:
            if type(directory_fd) is not int or directory_fd < 0:
                raise _failure()
            self._directory_fd = os.dup(directory_fd)
            os.set_inheritable(self._directory_fd, False)
            peer.check()
            info = os.fstat(self._directory_fd)
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_gid != os.getegid() or stat.S_IMODE(info.st_mode) != 0o700):
                raise _failure()
            self.path = Path(f"/proc/self/fd/{self._directory_fd}/native-host.sock")
            self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
            self._socket.settimeout(self._timeout)
            self._socket.bind(str(self.path))
            self._inode = os.stat("native-host.sock", dir_fd=self._directory_fd, follow_symlinks=False)
            os.chmod("native-host.sock", 0o600, dir_fd=self._directory_fd, follow_symlinks=False)
            self._socket.listen(8)
        except (OSError, ValueError, ChannelError):
            self.close()
            raise _failure() from None

    def close(self):
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._inode is not None and self._directory_fd is not None:
            try:
                current = os.stat("native-host.sock", dir_fd=self._directory_fd, follow_symlinks=False)
                if stat.S_ISSOCK(current.st_mode) and os.path.samestat(self._inode, current):
                    os.unlink("native-host.sock", dir_fd=self._directory_fd)
            except OSError:
                pass
            self._inode = None
        if self._directory_fd is not None:
            os.close(self._directory_fd)
            self._directory_fd = None


class HermesChannel:
    """Thin client for the launcher's protected mount; no authority or secrets.

    The protected mount, not a model-provided path, identifies the server. Any
    uncertain exchange poisons this client; no automatic retry of an event.
    """

    def __init__(self, path: Path, timeout=2, *, server_credentials=None):
        _linux()
        if not Path(path).is_absolute():
            raise _failure()
        if server_credentials is not None and (
                type(server_credentials) is not tuple or len(server_credentials) != 3
                or any(type(value) is not int for value in server_credentials)
                or not 0 <= server_credentials[0] <= 2147483647
                or any(not 0 < value <= 2147483647 for value in server_credentials[1:])):
            raise _failure()
        self._server_credentials = server_credentials
        self._path, self._timeout = str(path), _timeout(timeout)
        self._pid, self._sequence, self._failed = os.getpid(), 1, False
        self._lock = threading.Lock()

    def exchange(self, event: dict) -> dict:
        # Check before taking a potentially inherited, permanently locked lock.
        if os.getpid() != self._pid or self._failed:
            raise _failure()
        with self._lock:
            if self._failed:
                raise _failure()
            sequence = self._sequence
            self._sequence += 1
            try:
                raw = _encode({"schema_version": "native-host-event/v1", "sequence": sequence, "event": event})
                _frame(raw, "event", "native-host-event/v1")
                with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as connection:
                    connection.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
                    connection.settimeout(self._timeout)
                    connection.connect(self._path)
                    if connection.send(raw) != len(raw):
                        raise _failure()
                    response, credentials = _receive(connection)
                    if self._server_credentials is not None and credentials != self._server_credentials:
                        raise _failure()
                frame = _frame(response, "result", "native-host-response/v1")
                if frame["sequence"] != sequence:
                    raise _failure()
                return frame["result"]
            except (OSError, ValueError, TypeError, ChannelError, RecursionError):
                self._failed = True
                raise _failure() from None
