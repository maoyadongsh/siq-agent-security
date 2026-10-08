"""Real Unix control transport and owner pidfds; runtime backend is a fixture."""

import datetime
import importlib.util
import json
import os
import select
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

directory = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("host_control_test", directory / "host_control.py",
                                             submodule_search_locations=[str(directory)])
control = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = control
spec.loader.exec_module(control)
composition = sys.modules[spec.name + ".host_session"]
channel = sys.modules[spec.name + ".native_channel"]
pytestmark = pytest.mark.skipif(sys.platform != "linux" or os.getuid() == 0, reason="Non-root Linux control")


def future(seconds):
    return (datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


class SessionFixture:
    def __init__(self, *_):
        self._stopped, self._fence, self.arguments = threading.Event(), None, None
        self._loop = SimpleNamespace(_stop=self._stopped,
                                     _thread=SimpleNamespace(is_alive=lambda: not self._stopped.is_set()))

    def start(self, **arguments):
        self.arguments = arguments
        guard = SimpleNamespace(artifact="a" * 64, verify=lambda: None, close=lambda: None)
        self._fence = composition.BusinessGuard(guard, supervisor_pid=arguments["supervisor_pid"],
            expires_at=arguments["expires_at"], authorization_expires_at=arguments["authorization_expires_at"])

    def assert_running(self):
        if self._stopped.is_set() or self._fence is None:
            raise control.OnlineError("fixture session stopped")
        self._fence.verify()

    def renew(self, **arguments):
        self._fence.renew(**arguments)

    def close(self):
        self._stopped.set()
        if self._fence is not None:
            self._fence.close()


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(control, "HostSession", SessionFixture)
    with tempfile.TemporaryDirectory(prefix="siq-control-") as scratch:
        root = Path(scratch)
        config = root / "control.json"
        value = {"schema_version": "native-host-control-config/v1", "credential": "nhc-" + "a" * 64,
                 "control_socket": str(root / "control.sock")}
        config.write_text(json.dumps(value))
        config.chmod(0o600)
        service = control.HostControl(None, "http://127.0.0.1:12345", config).start()
        try:
            yield service, config, value
        finally:
            service.close()


def message(value, operation="start", handle="nhs-" + "b" * 32, **changes):
    args = {"backend": {}, "runtime": {}, "subject": {}, "installs": [], "channel_directory": "/fixture",
            "credential": "ri-" + "c" * 32 + "." + "d" * 64,
            "expires_at": future(120), "authorization_expires_at": future(60)} if operation == "start" else {}
    if operation == "renew":
        args = {"authorization_expires_at": future(80)}
    return {"schema_version": "native-host-control/v1", "request_id": "e" * 32,
            "credential": value["credential"], "operation": operation, "handle": handle, "arguments": args} | changes


def exchange(value, body, *, raw=False):
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as wire:
        wire.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        wire.settimeout(3)
        wire.connect(value["control_socket"])
        wire.send(body if raw else json.dumps(body).encode())
        response, owner = control._receive(wire)
        assert owner == (os.getpid(), os.getuid(), os.getgid())
        return json.loads(response)


def test_start_renew_status_stop_and_terminal_handle(server):
    service, _, config = server
    body = message(config)
    assert exchange(config, body)["state"] == "running"
    entry = service._entries[body["handle"]]
    assert entry["session"].arguments["supervisor_pid"] == os.getpid()
    assert exchange(config, message(config, "renew"))["state"] == "running"
    assert exchange(config, message(config, "status"))["state"] == "running"
    assert exchange(config, message(config, "stop"))["state"] == "closed"
    assert exchange(config, message(config, "status"))["state"] == "closed"
    assert exchange(config, message(config, "renew")) == control._ERROR
    assert exchange(config, message(config)) == control._ERROR


@pytest.mark.parametrize("change", [{"credential": "wrong"}, {"supervisor_pid": 1},
    {"operation": "exec"}, {"request_id": "bad"}, {"handle": "--help"}, {"arguments": {"supervisor_pid": 1}}])
def test_invalid_control_cannot_create_sessions(server, change):
    service, _, config = server
    assert exchange(config, message(config, **change)) == control._ERROR
    assert service._entries == {}


@pytest.mark.parametrize("raw", [b"not-json", b'{"schema_version":"x","schema_version":"y"}',
                                      b'{"arguments":NaN}', b"[]"])
def test_malformed_frames_return_only_fixed_error(server, raw):
    service, _, config = server
    assert exchange(config, raw, raw=True) == control._ERROR
    assert not service._entries


def test_duplicate_or_bad_auth_does_not_close_existing_session(server):
    service, _, config = server
    body = message(config)
    assert exchange(config, body)["state"] == "running"
    assert exchange(config, body) == control._ERROR
    assert exchange(config, message(config, "stop", credential="wrong")) == control._ERROR
    assert service._entries[body["handle"]]["state"] == "running"
    assert exchange(config, message(config, "status"))["state"] == "running"


def test_busy_handle_refuses_without_queuing_or_closing(server):
    service, _, config = server
    body = message(config)
    exchange(config, body)
    with service._entries[body["handle"]]["lock"]:
        assert exchange(config, message(config, "status")) == control._ERROR
    assert exchange(config, message(config, "status"))["state"] == "running"


def test_real_child_owner_is_kernel_derived_and_reaped_on_exit(server):
    service, _, config = server
    program = '''import json,socket,sys
v=json.load(sys.stdin)
with socket.socket(socket.AF_UNIX,socket.SOCK_SEQPACKET) as s:
 s.settimeout(3);s.connect(v['path']);s.send(json.dumps(v['request']).encode());print(s.recv(65536).decode())
'''
    body = message(config)
    process = subprocess.Popen([sys.executable, "-I", "-c", program], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    output, error = process.communicate(json.dumps({"path": config["control_socket"], "request": body}), timeout=5)
    assert process.returncode == 0 and error == "" and json.loads(output)["state"] == "running"
    entry = service._entries[body["handle"]]
    assert entry["session"].arguments["supervisor_pid"] == process.pid
    assert exchange(config, message(config, "renew")) == control._ERROR
    service.sweep()
    assert entry["state"] == "closed"


def test_forked_sender_cannot_use_parent_connection(server):
    service, _, config = server
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as wire:
        wire.settimeout(3)
        wire.connect(config["control_socket"])
        child = os.fork()
        if child == 0:
            signal.alarm(2)
            wire.send(json.dumps(message(config)).encode())
            os._exit(0)
        _, status = os.waitpid(child, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        assert json.loads(wire.recv(65536)) == control._ERROR
    assert not service._entries


def test_configuration_replacement_fences_existing_session(server):
    service, path, config = server
    exchange(config, message(config))
    new = path.with_suffix(".replacement")
    new.write_bytes(path.read_bytes())
    new.chmod(0o600)
    new.replace(path)
    try:
        assert exchange(config, message(config, "status")) == control._ERROR
    except ConnectionResetError:
        # Refusal can happen before reading the queued packet; Unix then
        # resets the connection instead of delivering the fixed error packet.
        pass
    entry = next(iter(service._entries.values()))
    with pytest.raises(control.OnlineError):
        entry["session"].assert_running()


def test_replaced_socket_object_is_preserved(server):
    service, _, config = server
    path = Path(config["control_socket"])
    path.unlink()
    path.write_text("unrelated replacement")
    with pytest.raises(control.OnlineError):
        service.assert_running()
    service.close()
    assert path.read_text() == "unrelated replacement"


def test_existing_socket_path_is_never_removed(server):
    _, path, config = server
    value = dict(config, control_socket=str(path.parent / "occupied"))
    target = Path(value["control_socket"])
    target.write_text("existing")
    other = path.parent / "other.json"
    other.write_text(json.dumps(value))
    other.chmod(0o600)
    service = control.HostControl(None, "http://127.0.0.1:12345", other)
    with pytest.raises(control.OnlineError):
        service.start()
    assert target.read_text() == "existing"


def test_active_session_budget_refuses_before_new_start(server):
    service, _, config = server
    for n in range(16):
        assert exchange(config, message(config, handle="nhs-" + f"{n:032x}"))["state"] == "running"
    assert exchange(config, message(config, handle="nhs-" + "f" * 32)) == control._ERROR
    assert len(service._entries) == 16
    assert exchange(config, message(config, "stop", handle="nhs-" + "0" * 32))["state"] == "closed"
    assert exchange(config, message(config, handle="nhs-" + "f" * 32))["state"] == "running"


def test_control_handler_budget_does_not_queue_a_fifth_packet(server):
    service, _, config = server
    wires = []
    try:
        for _ in range(4):
            wire = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            wire.settimeout(3)
            wire.connect(config["control_socket"])
            wires.append(wire)
        deadline = time.monotonic() + 3
        while service._inflight != 4:
            assert time.monotonic() < deadline
            time.sleep(.01)
        with pytest.raises((OSError, channel.ChannelError)):
            exchange(config, message(config))
        assert not service._entries and service._inflight == 4
    finally:
        for wire in wires:
            wire.close()


def test_used_handle_budget_refuses_without_reusing_tombstones(server):
    service, _, config = server
    closed = SessionFixture()
    closed.close()
    service._entries = {"nhs-" + f"{n:032x}": {"owner": (os.getpid(), os.getuid(), os.getgid()),
        "session": closed, "state": "closed", "lock": threading.Lock()} for n in range(4096)}
    assert exchange(config, message(config, handle="nhs-" + "f" * 32)) == control._ERROR
    assert len(service._entries) == 4096


def _line(process):
    assert select.select([process.stdout], [], [], 5)[0], "owned client did not respond"
    return json.loads(process.stdout.readline(4096))


def test_business_consumer_cross_process_interoperability(server):
    service, path, config = server
    business = Path("/home/maoyd/siq-research-engine/scripts/openshell/probe_agentshield_native_host.py")
    if not business.exists():
        pytest.skip("Explicit local business consumer unavailable")
    request = message(config)
    inputs = path.parent / "business-input.json"
    inputs.write_text(json.dumps({"schema_version": "siq.native-host-client-probe/v1", "control_config": str(path),
                                 "handle": request["handle"], "start_arguments": request["arguments"]}))
    inputs.chmod(0o600)
    process = subprocess.Popen([sys.executable, "-I", "-B", str(business), "--input", str(inputs)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
    try:
        assert _line(process) == {"schema_version": "siq.native-host-client-probe-ready/v1", "state": "running", "pid": process.pid}
        assert service._entries[request["handle"]]["owner"][0] == process.pid
        assert exchange(config, message(config, "status")) == control._ERROR
        for operation in ("renew", "status", "stop"):
            command = {"operation": operation}
            if operation == "renew":
                command["authorization_expires_at"] = future(80)
            process.stdin.write(json.dumps(command) + "\n")
            process.stdin.flush()
            assert _line(process) == {"operation": operation, "state": "closed" if operation == "stop" else "running"}
        process.wait(timeout=5)
        assert process.returncode == 0 and process.stderr.read() == ""
        assert service._entries[request["handle"]]["state"] == "closed"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def test_explicit_service_entry_starts_and_stops_owned_sockets():
    with tempfile.TemporaryDirectory(prefix="siq-host-service-") as scratch:
        root = Path(scratch)
        connection, config = root / "connection.json", root / "control.json"
        connection.write_text(json.dumps({"schema_version": "native-host-connection/v1", "credential": "nhp-" + "a" * 64,
                                         "verification_socket": str(root / "verify.sock")}))
        config.write_text(json.dumps({"schema_version": "native-host-control-config/v1", "credential": "nhc-" + "b" * 64,
                                     "control_socket": str(root / "control.sock")}))
        connection.chmod(0o600)
        config.chmod(0o600)
        process = subprocess.Popen([sys.executable, "-I", "-B", str(directory / "host_service.py"),
            "--connection", str(connection), "--control", str(config), "--port", "9"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            assert _line(process) == {"schema_version": "native-host-service-ready/v1", "runtime_state": "unverified", "pid": process.pid}
            assert (root / "verify.sock").exists() and (root / "control.sock").exists()
            process.terminate()
            process.wait(timeout=5)
            assert process.returncode == 0 and process.stderr.read() == ""
            assert not (root / "verify.sock").exists() and not (root / "control.sock").exists()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            process.stdout.close()
            process.stderr.close()
