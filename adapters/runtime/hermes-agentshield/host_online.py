"""Trusted-launcher online publisher and private reverse verification service.

Never installed by the ordinary Hermes plugin or mounted into its sandbox.
Registration is an in-process launcher API, not an HTTP management endpoint.
"""

import datetime
import hmac
import http.client
import http.server
import json
import os
import re
import socketserver
import threading
import time
import urllib.parse
from pathlib import Path

from .host_runtime import _host_info
from .native_channel import ChannelIdle


class OnlineError(RuntimeError):
    pass


def _failure():
    return OnlineError("native_host_unavailable")


def _pairs(pairs):
    value = dict(pairs)
    if len(value) != len(pairs):
        raise _failure()
    return value


def _decode(raw):
    if len(raw) > 65536:
        raise _failure()
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(_failure()))


def _config(path):
    path = Path(path)
    info, parent = _host_info(str(path)), _host_info(str(path.parent))
    if info.st_mode & 0o777 != 0o600 or info.st_nlink != 1 or parent.st_mode & 0o777 != 0o700:
        raise _failure()
    with path.open("rb") as file:
        raw = file.read(16385)
        if len(raw) > 16384 or not os.path.samestat(info, os.fstat(file.fileno())):
            raise _failure()
    value = _decode(raw)
    if (type(value) is not dict or set(value) != {"schema_version", "credential", "verification_socket"}
            or value["schema_version"] != "native-host-connection/v1"
            or type(value["credential"]) is not str or not re.fullmatch(r"nhp-[a-f0-9]{64}", value["credential"])):
        raise _failure()
    socket = Path(value["verification_socket"])
    if not socket.is_absolute() or socket.parent.resolve(strict=True) != socket.parent:
        raise _failure()
    parent = _host_info(str(socket.parent))
    if parent.st_mode & 0o777 != 0o700 or parent.st_uid != os.getuid():
        raise _failure()
    return value


def _key(subject):
    if (type(subject) is not dict or set(subject) not in (
            {"platform", "instance_id", "agent_id", "session_id"},
            {"platform", "instance_id", "agent_id", "session_id", "task_id"})
            or any(type(value) is not str or not 0 < len(value.encode()) <= 256
                   or any(ord(c) < 32 or ord(c) == 127 for c in value) for value in subject.values())
            or subject["platform"] != "hermes"
            or not re.fullmatch(r"hi-[a-f0-9]{32}", subject["instance_id"])
            or subject["agent_id"] != "hri-" + subject["instance_id"][3:]):
        raise _failure()
    return tuple(subject[name] for name in ("platform", "instance_id", "agent_id", "session_id"))


class Verifier:
    def __init__(self, config_path):
        self.config_path = Path(config_path)
        self.config = _config(config_path)
        self._entries, self._lock = {}, threading.RLock()
        self._server, self._thread, self._socket_info = None, None, None

    def register(self, subject, guard, installs, *, lifetime=3600):
        """Only the owning trusted launcher can register an already checked PID."""
        key = _key(subject)
        if "task_id" in subject or type(installs) is not list or len(installs) > 64 or type(lifetime) is not int or not 0 < lifetime <= 3600:
            raise _failure()
        guard.verify()
        mounts = []
        for item in installs:
            if (type(item) is not dict or set(item) != {"instance_id", "install_id", "claim_signature", "host_root", "runtime_root"}
                    or item["instance_id"] != subject["instance_id"]):
                raise _failure()
            guard.verify_mount(item["host_root"], item["runtime_root"])
            mounts.append(dict(item))
        with self._lock:
            if key in self._entries or len(self._entries) >= 4096:
                raise _failure()
            expires = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=lifetime)
            self._entries[key] = (guard, mounts, time.monotonic() + lifetime, expires)

    def verify(self, request):
        if (type(request) is not dict or set(request) != {"schema_version", "nonce", "subject", "artifact_sha256"}
                or request["schema_version"] != "native-host-verification/v1"
                or type(request["nonce"]) is not str or not re.fullmatch(r"[a-f0-9]{32}", request["nonce"])):
            raise _failure()
        key = _key(request["subject"])
        with self._lock:
            entry = self._entries.get(key)
        if entry is None:
            raise _failure()
        guard, mounts, until, expires = entry
        if request["artifact_sha256"] != guard.artifact or time.monotonic() >= until:
            raise _failure()
        guard.verify()  # Also verifies every immutable mount fixed at registration.
        remaining = until - time.monotonic()
        if remaining <= 0 or datetime.datetime.now(datetime.UTC) >= expires or _config(self.config_path) != self.config:
            raise _failure()
        # A signed call may be clamped to this lease. Recomputing the wall
        # timestamp from separate clock reads introduces microsecond jitter,
        # which can incorrectly invalidate a still-live signed call.
        return {"schema_version": "native-host-verified/v1", "nonce": request["nonce"],
                "subject": dict(request["subject"]), "artifact_sha256": guard.artifact,
                "expires_at": expires.isoformat().replace("+00:00", "Z"), "install_mounts": [dict(m) for m in mounts]}

    def start(self):
        if self._server is not None:
            raise _failure()
        verifier = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def do_POST(self):
                status, value = 503, {"error": "native_host_unavailable"}
                try:
                    credential = self.headers.get("Authorization", "")
                    lengths = self.headers.get_all("Content-Length", [])
                    if (self.path != "/verify" or self.headers.get("Origin") is not None
                            or len(self.headers.get_all("Authorization", [])) != 1
                            or not hmac.compare_digest(credential, "Bearer " + verifier.config["credential"])
                            or self.headers.get("Transfer-Encoding") is not None or len(lengths) != 1
                            or not lengths[0].isdigit() or not 0 < int(lengths[0]) <= 65536):
                        raise _failure()
                    value = verifier.verify(_decode(self.rfile.read(int(lengths[0]))))
                    status = 200
                except Exception:  # noqa: BLE001 - never serialize request, process or OS details
                    status, value = 503, {"error": "native_host_unavailable"}
                raw = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
                if len(raw) > 65536:
                    status, raw = 503, b'{"error":"native_host_unavailable"}'
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True
            slots = threading.BoundedSemaphore(8)

            def process_request(self, request, address):
                if not self.slots.acquire(blocking=False):
                    self.shutdown_request(request)
                    return
                try:
                    super().process_request(request, address)
                except BaseException:
                    self.slots.release()
                    raise

            def process_request_thread(self, request, address):
                try:
                    super().process_request_thread(request, address)
                finally:
                    self.slots.release()

            def handle_error(self, *_):
                pass

        path = Path(self.config["verification_socket"])
        try:
            # Unix bind fails if the pathname already exists; never unlink it.
            self._server = Server(str(path), Handler)
            self._socket_info = path.lstat()
            path.chmod(0o600)
            self._thread = threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": .05}, daemon=True)
            self._thread.start()
        except BaseException:  # noqa: BLE001 - cleanup owned listener on cancellation
            self.close()
            raise _failure() from None
        return self

    def close(self):
        if self._server is not None:
            if self._thread is not None:
                self._server.shutdown()
                self._thread.join(timeout=2)
            self._server.server_close()
            self._server = None
        path = Path(self.config["verification_socket"])
        if self._socket_info is not None:
            try:
                if os.path.samestat(self._socket_info, path.lstat()):
                    path.unlink()
            except FileNotFoundError:
                pass
            self._socket_info = None
        with self._lock:
            for guard, _, _, _ in self._entries.values():
                guard.close()


class Publisher:
    """Call dispatch only from HostChannel after kernel authentication."""

    def __init__(self, config_path, endpoint, subject, guard):
        self.config_path, self.config = Path(config_path), _config(config_path)
        self.subject = dict(subject)
        _key(subject)
        if "task_id" in subject:
            raise _failure()
        parsed = urllib.parse.urlsplit(endpoint)
        if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port
                or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            raise _failure()
        self._port, self.guard = parsed.port, guard

    def dispatch(self, event):
        try:
            return self._dispatch(event)
        except Exception:  # noqa: BLE001 - return a known negative without exposing details
            # Kernel guard failures already poison that guard. An application
            # rejection must stop its task without invalidating other tasks or
            # confusing the channel's successfully consumed packet sequence.
            return {"accepted": False}

    def _dispatch(self, event):
        self.guard.verify()
        if _config(self.config_path) != self.config:
            raise _failure()
        if (type(event) is not dict or event.get("schema_version") != "native-hermes-lifecycle/v1"
                or event.get("agent_id") != self.subject["agent_id"] or event.get("session_id") != self.subject["session_id"]):
            raise _failure()
        subject = self.subject | {"task_id": event.get("task_id")}
        _key(subject)
        base = {"schema_version", "kind", "agent_id", "task_id", "session_id"}
        kind = event.get("kind")
        if kind == "task_begin" and set(event) == base:
            published = {"kind": kind, "artifact_sha256": self.guard.artifact}
        elif kind == "task_end" and set(event) == base | {"failed", "in_flight"} and type(event["failed"]) is bool and type(event["in_flight"]) is bool:
            published = {"kind": kind}
        elif kind == "skill_source" and set(event) == base | {"load_id", "parent_load_id", "source"}:
            if event["parent_load_id"] is not None and type(event["parent_load_id"]) is not str:
                raise _failure()
            published = {"kind": kind, "load_id": event["load_id"], "parent_load_id": event["parent_load_id"] or "", "source": event["source"]}
        elif kind == "call_prepare" and set(event) == base | {"tool", "tool_call_id", "request_binding", "load_id"}:
            published = {name: event[name] for name in ("kind", "tool", "tool_call_id", "request_binding", "load_id")}
        elif kind == "tool_result" and set(event) == base | {"tool_call_id", "request_binding", "decision_id", "outcome"} and event["outcome"] in ("returned", "raised"):
            published = {"kind": "call_finish", "tool_call_id": event["tool_call_id"], "request_binding": event["request_binding"]}
        else:
            raise _failure()
        raw = json.dumps({"schema_version": "native-host-publish/v1", "subject": subject, "event": published}, allow_nan=False).encode()
        if len(raw) > 65536:
            raise _failure()
        connection = http.client.HTTPConnection("127.0.0.1", self._port, timeout=5)
        try:
            connection.request("POST", "/v1/native-host/events", raw, {"Authorization": "Bearer " + self.config["credential"], "Content-Type": "application/json"})
            response = connection.getresponse()
            result = _decode(response.read(65537))
            if (response.status != 200 or type(result) is not dict or set(result) != {"schema_version", "accepted"}
                    or result["schema_version"] != "native-host-published/v1" or result["accepted"] is not True):
                raise _failure()
        finally:
            connection.close()
        self.guard.verify()
        return {"accepted": True}


class DecisionRelay:
    """Authenticated peer -> fixed scoped /v1/decide; never an authorizer."""

    def __init__(self, publisher, runtime_credential):
        if (not isinstance(publisher, Publisher) or type(runtime_credential) is not str
                or not re.fullmatch(r"ri-[a-f0-9]{32}\.[a-f0-9]{64}", runtime_credential)):
            raise _failure()
        self.publisher, self._credential = publisher, runtime_credential

    def dispatch(self, event):
        if type(event) is dict and event.get("schema_version") == "native-hermes-lifecycle/v1":
            return self.publisher.dispatch(event)
        try:
            return self._decide(event)
        except Exception:  # noqa: BLE001 - never reflect credentials, parameters or transport exceptions
            return {"error": "native_host_unavailable"}

    def _decide(self, event):
        publisher = self.publisher
        publisher.guard.verify()
        if _config(publisher.config_path) != publisher.config:
            raise _failure()
        if (type(event) is not dict or set(event) != {"schema_version", "request"}
                or event["schema_version"] != "native-decision-relay/v1"):
            raise _failure()
        request = event["request"]
        if (type(request) is not dict or set(request) != {
                "platform", "agent_id", "session_id", "runtime_task_id", "tool", "tool_call_id", "params"}
                or type(request["params"]) is not dict
                or any(request[k] != publisher.subject[k] for k in ("platform", "agent_id", "session_id"))):
            raise _failure()
        for key in ("runtime_task_id", "tool", "tool_call_id"):
            value = request[key]
            if (type(value) is not str or not 0 < len(value.encode()) <= 256
                    or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                raise _failure()
        raw = json.dumps(request, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
        if len(raw) > 65536:
            raise _failure()
        deadline = time.monotonic() + 5
        connection = http.client.HTTPConnection("127.0.0.1", publisher._port, timeout=5)
        try:
            connection.request("POST", "/v1/decide", raw,
                {"Authorization": "Bearer " + self._credential, "Content-Type": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                raise _failure()
            chunks, total = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _failure()
                # The retained response socket can be detached from connection
                # when HTTP/1.0 closes; set its deadline before each short read.
                response.fp.raw._sock.settimeout(remaining)
                chunk = response.read1(min(4096, 65537 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > 65536:
                    raise _failure()
                chunks.append(chunk)
                if response.isclosed():
                    break
            result = _decode(b"".join(chunks))
            if (type(result) is not dict or result.get("action") not in ("allow", "deny", "hold")
                    or type(result.get("receipt_id")) is not str or not 0 < len(result["receipt_id"].encode()) <= 256
                    or any(ord(c) < 32 or ord(c) == 127 for c in result["receipt_id"]) or "params" in result):
                raise _failure()
            publisher.guard.verify()
            if time.monotonic() >= deadline:
                raise _failure()
            return {"action": result["action"], "receipt_id": result["receipt_id"]}
        finally:
            connection.close()


class HostLoop:
    """One bounded worker for an owning launcher's authenticated host channel."""

    def __init__(self, channel, relay, *, expires_at):
        self._pid = os.getpid()
        self._channel, self._relay = channel, relay
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._close_lock, self._channel_closed = threading.Lock(), False
        self._thread, self._attempted, self._failed = None, False, False
        if (not isinstance(relay, DecisionRelay) or type(expires_at) is not datetime.datetime
                or expires_at.tzinfo is not datetime.UTC):
            raise _failure()
        remaining = (expires_at - datetime.datetime.now(datetime.UTC)).total_seconds()
        if not 0 < remaining <= 3600:
            raise _failure()
        self._expires, self._until = expires_at, time.monotonic() + remaining

    def _live(self):
        if (os.getpid() != self._pid or self._stop.is_set()
                or time.monotonic() >= self._until or datetime.datetime.now(datetime.UTC) >= self._expires):
            raise _failure()
        self._relay.publisher.guard.verify()
        if self._stop.is_set() or time.monotonic() >= self._until or datetime.datetime.now(datetime.UTC) >= self._expires:
            raise _failure()

    def _dispatch(self, event):
        try:
            self._live()
            result = self._relay.dispatch(event)
            self._live()
            return result
        except Exception:  # noqa: BLE001 - never reflect lifecycle/transport exceptions.
            self._failed = True
            self._stop.set()
            return {"error": "native_host_unavailable"}

    def _run(self):
        try:
            while not self._stop.is_set():
                self._live()
                try:
                    self._channel.serve_once(self._dispatch)
                except ChannelIdle:
                    continue
        except Exception:  # noqa: BLE001 - only the categorical liveness result escapes.
            if not self._stop.is_set():
                self._failed = True
        finally:
            self._stop.set()
            self._close_channel()

    def _close_channel(self):
        with self._close_lock:
            if not self._channel_closed:
                self._channel_closed = True
                self._channel.close()

    def start(self):
        if os.getpid() != self._pid:
            raise _failure()
        with self._lock:
            if self._attempted:
                raise _failure()
            self._attempted = True
            try:
                self._live()
                self._thread = threading.Thread(target=self._run, name="siq-native-host", daemon=True)
                self._thread.start()
            except Exception:  # noqa: BLE001 - failed startup cannot be retried.
                self._failed = True
                self._stop.set()
                self._close_channel()
                raise _failure() from None
        return self

    def assert_running(self):
        self._live()
        if self._thread is None or not self._thread.is_alive() or self._failed:
            raise _failure()

    def close(self):
        if os.getpid() != self._pid:
            raise _failure()
        self._stop.set()
        with self._lock:
            self._close_channel()
            thread = self._thread
        if thread is not None and thread.ident is not None:
            if thread is threading.current_thread():
                raise _failure()
            thread.join(timeout=6)
            if thread.is_alive():
                raise _failure()

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.close()
