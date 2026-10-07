"""Private, kernel-authenticated lifecycle control for trusted host supervisors."""

import datetime
import hmac
import os
import re
import socket
import socketserver
import stat
import struct
import threading
import time
from pathlib import Path

from .host_online import OnlineError, _decode
from .host_runtime import _host_info, _stamp
from .host_session import HostSession
from .native_channel import ProcessPin, _encode, _receive

_REQUEST_KEYS = {"schema_version", "request_id", "credential", "operation", "handle", "arguments"}
_START_KEYS = {"backend", "runtime", "subject", "installs", "channel_directory", "credential",
               "expires_at", "authorization_expires_at"}
_ERROR = {"error": "native_host_control_unavailable"}


def _failure():
    return OnlineError("native_host_control_unavailable")


def _directory_stamp(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid


def _config(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise _failure()
    info, parent = _host_info(str(path)), _host_info(str(path.parent))
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 16384
            or parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) != 0o700):
        raise _failure()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        raw = os.read(fd, 16385)
        if (len(raw) != info.st_size or _stamp(os.fstat(fd)) != _stamp(info)
                or _stamp(_host_info(str(path))) != _stamp(info)):
            raise _failure()
    finally:
        os.close(fd)
    value = _decode(raw)
    if (type(value) is not dict or set(value) != {"schema_version", "credential", "control_socket"}
            or value["schema_version"] != "native-host-control-config/v1"
            or type(value["credential"]) is not str or not re.fullmatch(r"nhc-[a-f0-9]{64}", value["credential"])
            or type(value["control_socket"]) is not str):
        raise _failure()
    target = Path(value["control_socket"])
    if (not target.is_absolute() or target.parent.resolve(strict=True) != target.parent
            or not 0 < len(os.fsencode(target)) <= 107):
        raise _failure()
    directory = _host_info(str(target.parent))
    if directory.st_uid != os.getuid() or stat.S_IMODE(directory.st_mode) != 0o700:
        raise _failure()
    return value, (_stamp(info), _directory_stamp(parent), _directory_stamp(directory))


def _date(value):
    if (type(value) is not str
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value)):
        raise _failure()
    return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))


class HostControl:
    def __init__(self, verifier, endpoint, config_path):
        self._pid = os.getpid()
        self._verifier, self._endpoint, self._config_path = verifier, endpoint, Path(config_path)
        self._config, self._config_stamp = _config(config_path)
        self._entries, self._lock = {}, threading.Lock()
        self._workers, self._inflight = threading.Condition(), 0
        self._stopped, self._attempted = threading.Event(), False
        self._server = self._thread = self._socket_info = None

    def _check(self):
        if os.getpid() != self._pid or self._stopped.is_set():
            raise _failure()
        try:
            if _config(self._config_path) != (self._config, self._config_stamp):
                raise _failure()
            info = _host_info(self._config["control_socket"])
            if (self._socket_info is None or _stamp(info) != self._socket_info
                    or not stat.S_ISSOCK(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600):
                raise _failure()
        except Exception:  # noqa: BLE001 - config loss fences all sessions before cleanup.
            self._stopped.set()
            with self._lock:
                entries = list(self._entries.values())
            for entry in entries:
                entry["session"]._stopped.set()
                if entry["session"]._fence is not None:
                    entry["session"]._fence.stop()
            raise _failure() from None

    def _closed(self, entry):
        try:
            entry["session"].close()
            entry["state"] = "closed"
        except Exception:  # noqa: BLE001 - keep ambiguous cleanup visible internally.
            entry["state"] = "cleanup_pending"
            raise _failure() from None

    def _request(self, owner, value):
        self._check()
        if (type(value) is not dict or set(value) != _REQUEST_KEYS
                or value["schema_version"] != "native-host-control/v1"
                or type(value["credential"]) is not str
                or not hmac.compare_digest(value["credential"], self._config["credential"])
                or type(value["request_id"]) is not str or not re.fullmatch(r"[a-f0-9]{32}", value["request_id"])
                or type(value["handle"]) is not str or not re.fullmatch(r"nhs-[a-f0-9]{32}", value["handle"])
                or type(value["operation"]) is not str or value["operation"] not in ("start", "renew", "status", "stop")
                or type(value["arguments"]) is not dict):
            raise _failure()
        operation, handle, arguments = value["operation"], value["handle"], value["arguments"]
        expected = _START_KEYS if operation == "start" else {"authorization_expires_at"} if operation == "renew" else set()
        if set(arguments) != expected:
            raise _failure()
        dates = {k: _date(arguments[k]) for k in ("expires_at", "authorization_expires_at") if k in arguments}
        with self._lock:
            entry = self._entries.get(handle)
            if operation == "start":
                if (entry is not None or len(self._entries) >= 4096
                        or sum(e["state"] != "closed" for e in self._entries.values()) >= 16):
                    raise _failure()
                entry = {"owner": owner, "session": HostSession(self._verifier, self._endpoint),
                         "state": "starting", "lock": threading.Lock()}
                self._entries[handle] = entry
            if entry is None or entry["owner"] != owner or not entry["lock"].acquire(blocking=False):
                raise _failure()
        try:
            if operation == "start":
                try:
                    entry["session"].start(**(arguments | dates), supervisor_pid=owner[0])
                    self._check()
                    entry["session"].assert_running()
                    entry["state"] = "running"
                except Exception:  # noqa: BLE001 - a failed handle cannot be started again.
                    self._closed(entry)
                    raise _failure() from None
            elif operation == "stop":
                self._closed(entry)
            elif operation == "renew":
                if entry["state"] != "running":
                    raise _failure()
                entry["session"].renew(supervisor_pid=owner[0], **dates)
                entry["session"].assert_running()
            elif entry["state"] == "running":
                entry["session"].assert_running()
            elif entry["state"] != "closed":
                raise _failure()
            self._check()
            return {"schema_version": "native-host-controlled/v1", "request_id": value["request_id"],
                    "handle": handle, "state": entry["state"]}
        finally:
            entry["lock"].release()

    def _lost_response(self, owner, value):
        if type(value) is not dict or type(value.get("handle")) is not str:
            return
        with self._lock:
            entry = self._entries.get(value["handle"])
        if entry is not None and entry["owner"] == owner and entry["lock"].acquire(blocking=False):
            try:
                self._closed(entry)
            except Exception:  # noqa: BLE001 - sweeper retains failed cleanup for another attempt.
                entry["state"] = "cleanup_pending"
            finally:
                entry["lock"].release()

    def start(self):
        if os.getpid() != self._pid or self._attempted or self._stopped.is_set():
            raise _failure()
        self._attempted = True
        control = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                value, owner, completed = None, None, False
                try:
                    control._check()
                    self.request.settimeout(5)
                    self.request.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
                    peer = struct.unpack("3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    if peer[0] <= 0 or peer[1:] != (os.getuid(), os.getgid()):
                        raise _failure()
                    with ProcessPin(peer[0], peer[1]) as pin:
                        raw, owner = _receive(self.request)
                        if owner != peer:
                            raise _failure()
                        pin.check()
                        value = _decode(raw)
                        response = control._request(owner, value)
                        completed = True
                        pin.check()
                        raw = _encode(response)
                        if self.request.send(raw) != len(raw):
                            raise _failure()
                except Exception:  # noqa: BLE001 - never echo credentials or private launch material.
                    if completed and owner is not None:
                        control._lost_response(owner, value)
                    try:
                        self.request.send(_encode(_ERROR))
                    except OSError:
                        pass

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            socket_type = socket.SOCK_SEQPACKET
            daemon_threads = True
            block_on_close = False
            request_queue_size = 4

            def server_bind(self):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
                super().server_bind()

            def process_request(self, request, address):
                with control._workers:
                    if control._inflight >= 4:
                        self.shutdown_request(request)
                        return
                    control._inflight += 1
                try:
                    super().process_request(request, address)
                except BaseException:
                    with control._workers:
                        control._inflight -= 1
                        control._workers.notify_all()
                    raise

            def process_request_thread(self, request, address):
                try:
                    super().process_request_thread(request, address)
                finally:
                    with control._workers:
                        control._inflight -= 1
                        control._workers.notify_all()

            def handle_error(self, *_):
                pass

        path = Path(self._config["control_socket"])
        try:
            if _config(self._config_path) != (self._config, self._config_stamp):
                raise _failure()
            self._server = Server(str(path), Handler)
            path.chmod(0o600)
            self._socket_info = _stamp(path.lstat())
            self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
            self._thread.start()
            self._check()
            return self
        except BaseException:  # noqa: BLE001 - never replace another service's socket on failure.
            self.close()
            raise _failure() from None

    def sweep(self):
        self._check()
        with self._lock:
            entries = list(self._entries.values())
        for entry in entries:
            if entry["state"] == "closed" or not entry["lock"].acquire(blocking=False):
                continue
            try:
                if entry["state"] == "running":
                    try:
                        entry["session"]._fence._check()
                        loop = entry["session"]._loop
                        if loop._stop.is_set() or not loop._thread.is_alive():
                            raise _failure()
                        continue
                    except Exception:  # noqa: BLE001 - expired or failed sessions are terminal.
                        entry["state"] = "cleanup_pending"
                self._closed(entry)
            except Exception:  # noqa: BLE001 - keep cleanup_pending for a later bounded attempt.
                entry["state"] = "cleanup_pending"
            finally:
                entry["lock"].release()

    def assert_running(self):
        self._check()
        if self._thread is None or not self._thread.is_alive():
            raise _failure()
        self.sweep()

    def close(self):
        if os.getpid() != self._pid:
            raise _failure()
        self._stopped.set()
        with self._lock:
            entries = list(self._entries.values())
        for entry in entries:
            entry["session"]._stopped.set()
            if entry["session"]._fence is not None:
                entry["session"]._fence.stop()
        if self._server is not None:
            if self._thread is not None and self._thread.ident is not None:
                self._server.shutdown()
                self._thread.join(timeout=2)
            self._server.server_close()
        deadline = time.monotonic() + 30
        with self._workers:
            while self._inflight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _failure()
                self._workers.wait(timeout=remaining)
        deadline, failed = time.monotonic() + 20, False
        for entry in entries:
            if time.monotonic() >= deadline or not entry["lock"].acquire(blocking=False):
                failed = True
                continue
            try:
                self._closed(entry)
            except Exception:  # noqa: BLE001 - do not declare global cleanup complete on failure.
                failed = True
            finally:
                entry["lock"].release()
        if self._socket_info is not None:
            path = Path(self._config["control_socket"])
            try:
                if _stamp(path.lstat()) == self._socket_info:
                    path.unlink()
            except FileNotFoundError:
                pass
        if failed:
            raise _failure()
