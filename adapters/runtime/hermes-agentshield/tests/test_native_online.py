"""Online mappings over real HTTP/Unix sockets; authority/guard are named fixtures.

Actual Go Authority and kernel runtime checks have their own integration probes.
"""

import concurrent.futures
import hashlib
import http.client
import http.server
import importlib.util
import json
import os
import socket
import sys
import tempfile
import threading
from pathlib import Path

import pytest

directory = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("siq_online_tests", directory / "host_online.py",
                                             submodule_search_locations=[str(directory)])
online = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = online
spec.loader.exec_module(online)
channel = sys.modules[spec.name + ".native_channel"]
native_spec = importlib.util.spec_from_file_location(spec.name + ".native_dispatch", directory / "native_dispatch.py")
native = importlib.util.module_from_spec(native_spec)
native_spec.loader.exec_module(native)
callback_spec = importlib.util.spec_from_file_location(spec.name + ".native_online", directory / "native_online.py")
callbacks = importlib.util.module_from_spec(callback_spec)
callback_spec.loader.exec_module(callbacks)
pytestmark = pytest.mark.skipif(sys.platform != "linux" or os.getuid() == 0, reason="Linux non-root profile")


class GuardFixture:
    artifact = "a" * 64

    def __init__(self):
        self.closed, self.checks = False, 0

    def verify(self):
        if self.closed:
            raise online.OnlineError("fixture_guard_closed")
        self.checks += 1

    def verify_mount(self, *_):
        self.verify()

    def close(self):
        self.closed = True


@pytest.fixture
def setup():
    # Short path preserves the native Unix socket pathname limit.
    with tempfile.TemporaryDirectory(prefix="siq-online-test-") as scratch:
        root = Path(scratch)
        config = root / "connection.json"
        value = {"schema_version": "native-host-connection/v1", "credential": "nhp-" + "b" * 64,
                 "verification_socket": str(root / "verify.sock")}
        config.write_text(json.dumps(value))
        config.chmod(0o600)
        subject = {"platform": "hermes", "instance_id": "hi-" + "c" * 32, "agent_id": "hri-" + "c" * 32,
                   "session_id": "online:" + hashlib.sha256(b"native").hexdigest()}
        guard = GuardFixture()
        yield root, config, value, subject, guard


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("native-host", timeout=3)
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def test_reverse_verification_is_private_scoped_and_fresh(setup):
    _, config, value, subject, guard = setup
    verifier = online.Verifier(config)
    verifier.register(subject, guard, [])
    verifier.start()
    try:
        request = {"schema_version": "native-host-verification/v1", "nonce": "d" * 32,
                   "subject": subject | {"task_id": "actual-task"}, "artifact_sha256": guard.artifact}
        cases = [(request, value["credential"], 200), (request, "ri-wrong", 503),
                 (request | {"subject": subject | {"session_id": "other"}}, value["credential"], 503),
                 (request | {"artifact_sha256": "e" * 64}, value["credential"], 503)]
        for body, credential, status in cases:
            connection = UnixConnection(value["verification_socket"])
            try:
                connection.request("POST", "/verify", json.dumps(body), {"Authorization": "Bearer " + credential})
                response = connection.getresponse()
                data = json.loads(response.read())
                assert response.status == status
                if status == 200:
                    assert data["subject"] == body["subject"] and data["nonce"] == body["nonce"]
                    assert data["install_mounts"] == [] and guard.checks >= 2
            finally:
                connection.close()
        guard.close()
        with pytest.raises(online.OnlineError):
            verifier.verify(request)
    finally:
        verifier.close()
    assert not Path(value["verification_socket"]).exists()


@pytest.mark.parametrize("action", ["allow", "deny", "hold"])
def test_runtime_channel_publisher_and_http_parameter_mapping(setup, action):
    root, config, value, subject, guard = setup
    events, decisions = [], []

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/v1/native-host/events":
                assert self.headers["Authorization"] == "Bearer " + value["credential"]
                events.append(body)
                result = {"schema_version": "native-host-published/v1", "accepted": True}
            else:
                assert self.path == "/v1/decide" and self.headers["Authorization"] == "Bearer ri-fixture-scoped"
                decisions.append(body)
                result = {"action": action, "receipt_id": "fixture-receipt"}
            raw = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
    worker.start()
    endpoint = "http://127.0.0.1:" + str(server.server_port)
    publisher = online.Publisher(config, endpoint, subject, guard)

    def decide(body):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            connection.request("POST", "/v1/decide", json.dumps(body), {"Authorization": "Bearer ri-fixture-scoped"})
            return json.loads(connection.getresponse().read())
        finally:
            connection.close()

    effect = root / "effect"
    try:
        with channel.ProcessPin(os.getpid(), os.getuid()) as pin, channel.HostChannel(root, pin, timeout=3) as host:
            mapped = callbacks.Callbacks(channel.HermesChannel(host.path, timeout=3), decide)
            runtime = native.Runtime(subject["agent_id"], "online", mapped.observe, mapped.authorize, mapped.observe)
            expected = 4 if action == "allow" else 3

            def serve():
                for _ in range(expected):
                    host.serve_once(publisher.dispatch)

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                waiter = pool.submit(serve)

                def run():
                    with runtime.task("actual-task", "native"), runtime.call("write_file", {"path": str(effect)}, "actual-task", "native", "call-one"):
                        effect.write_text("authorized fixture handler\n")

                if action == "allow":
                    run()
                else:
                    with pytest.raises(native.DispatchError):
                        run()
                waiter.result(timeout=5)
        assert effect.exists() is (action == "allow")
        assert [event["event"]["kind"] for event in events] == (["task_begin", "call_prepare", "call_finish", "task_end"] if action == "allow" else ["task_begin", "call_prepare", "task_end"])
        assert all(event["subject"] == subject | {"task_id": "actual-task"} for event in events)
        assert len(decisions) == 1 and "task_id" not in decisions[0]
        assert decisions[0]["runtime_task_id"] == "actual-task"
        assert value["credential"] not in json.dumps(decisions)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_publisher_rejects_cross_session_before_any_http(setup):
    _, config, _, subject, guard = setup
    publisher = online.Publisher(config, "http://127.0.0.1:1", subject, guard)
    result = publisher.dispatch({"schema_version": "native-hermes-lifecycle/v1", "kind": "task_begin",
                                 "agent_id": subject["agent_id"], "session_id": "other", "task_id": "task"})
    assert result == {"accepted": False}
    assert not guard.closed
