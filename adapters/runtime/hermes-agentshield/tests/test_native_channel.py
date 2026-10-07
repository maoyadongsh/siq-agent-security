"""Real Linux Unix-packet credentials, including inherited-descriptor attacks."""

import array
import concurrent.futures
import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("siq_native_channel", Path(__file__).parents[1] / "native_channel.py")
channel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(channel)
pytestmark = pytest.mark.skipif(sys.platform != "linux" or os.getuid() == 0, reason="Linux non-root peer profile")


@pytest.fixture
def host(tmp_path):
    tmp_path.chmod(0o700)
    with channel.ProcessPin(os.getpid(), os.getuid()) as peer, channel.HostChannel(tmp_path, peer, timeout=.5) as server:
        yield server


def packet(sequence=1, event=None):
    return json.dumps({"schema_version": "native-host-event/v1", "sequence": sequence,
                       "event": event or {"kind": "synthetic-load", "digest": "a" * 64}}).encode()


def raw_socket(host):
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    connection.settimeout(1)
    connection.connect(str(host.path))
    return connection


def rejected(host, raw, ancillary=()):
    called = []
    with raw_socket(host) as connection:
        connection.sendmsg([raw], ancillary)
        with pytest.raises(channel.ChannelError, match="^native_host_channel_unavailable$"):
            host.serve_once(lambda event: called.append(event) or {})
    assert called == []


def test_actual_channel_allows_only_current_peer_metadata(host):
    client = channel.HermesChannel(host.path, timeout=.5)
    observed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        for index in range(2):
            task = pool.submit(host.serve_once, lambda event: observed.append(event) or {"accepted": True})
            assert client.exchange({"kind": "synthetic-call", "ordinal": index}) == {"accepted": True}
            task.result(timeout=2)
    assert observed == [{"kind": "synthetic-call", "ordinal": 0}, {"kind": "synthetic-call", "ordinal": 1}]


def test_concurrent_native_callbacks_keep_independent_responses(host):
    client = channel.HermesChannel(host.path, timeout=.5)
    observed = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        servers = [pool.submit(host.serve_once, lambda event: observed.append(event["ordinal"]) or event) for _ in range(2)]
        calls = [pool.submit(client.exchange, {"ordinal": ordinal}) for ordinal in range(2)]
        assert [call.result(timeout=2) for call in calls] == [{"ordinal": 0}, {"ordinal": 1}]
        for server in servers:
            server.result(timeout=2)
    assert sorted(observed) == [0, 1]


def test_inherited_connected_socket_cannot_impersonate_parent(host):
    with raw_socket(host) as connection:
        # SO_PEERCRED names this parent, but per-packet credentials must name
        # the child, even when it receives a fully connected descriptor.
        child = subprocess.run([sys.executable, "-I", "-c",
            "import os,socket,sys; s=socket.socket(fileno=int(sys.argv[1])); s.send(sys.argv[2].encode()); s.close()",
            str(connection.fileno()), packet().decode()], pass_fds=(connection.fileno(),),
            capture_output=True, timeout=3, check=False)
        assert child.returncode == 0
        observed = []
        with pytest.raises(channel.ChannelError):
            host.serve_once(lambda event: observed.append(event) or {})
        assert observed == []
    # Unauthorized traffic did not consume the genuine process's sequence.
    test_actual_channel_allows_only_current_peer_metadata(host)


@pytest.mark.parametrize("raw", [
    packet(2), packet(0), packet(True), packet(9007199254740992),
    b'{"schema_version":"native-host-event/v1","sequence":1,"sequence":1,"event":{}}',
    b'{"schema_version":"native-host-event/v1","sequence":1,"event":{"x":1,"x":2}}',
    b'{"schema_version":"native-host-event/v1","sequence":1,"event":{"x":1e999}}',
    b'{"schema_version":"native-host-event/v1","sequence":1,"event":{"x":NaN}}',
    packet().replace(b'"event"', b'"Event"'), packet() + b' {}', b'\xff',
    packet(event={str(i): i for i in range(33)}),
    packet(event={"synthetic": "x" * channel.MAX_PACKET}),
])
def test_invalid_unbounded_and_out_of_order_events_never_dispatch(host, raw):
    rejected(host, raw)


def test_replayed_event_is_rejected(host):
    with raw_socket(host) as connection:
        connection.send(packet())
        host.serve_once(lambda _: {"accepted": True})
        assert json.loads(connection.recv(channel.MAX_PACKET))["sequence"] == 1
    rejected(host, packet())


def test_packet_byte_budget_accepts_exact_limit_and_rejects_one_more(host):
    empty = {"schema_version": "native-host-event/v1", "sequence": 1, "event": {"value": ""}}
    budget = channel.MAX_PACKET - len(json.dumps(empty, separators=(",", ":")).encode())
    client = channel.HermesChannel(host.path, timeout=.5)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(host.serve_once, lambda event: {"bytes": len(event["value"])})
        assert client.exchange({"value": "x" * budget}) == {"bytes": budget}
        task.result(timeout=2)
    with pytest.raises(channel.ChannelError):
        client.exchange({"value": "x" * (budget + 1)})


def test_actual_response_matches_public_contract_sample(host):
    root = Path(__file__).resolve().parents[4] / "apps/agentshield/testdata/contracts"
    event = json.loads((root / "native-host-event-v1.sample.json").read_text())
    response = json.loads((root / "native-host-response-v1.sample.json").read_text())
    with raw_socket(host) as connection:
        connection.send(json.dumps(event).encode())
        observed = []
        host.serve_once(lambda value: observed.append(value) or response["result"])
        assert json.loads(connection.recv(channel.MAX_PACKET)) == response
    assert observed == [event["event"]]


def test_extra_file_descriptors_rejected_without_leak(host):
    with open(os.devnull, "rb") as harmless:
        before = len(os.listdir("/proc/self/fd"))
        for _ in range(12):
            rights = array.array("i", [harmless.fileno()] * 8)
            rejected(host, packet(), [(socket.SOL_SOCKET, socket.SCM_RIGHTS, rights)])
        assert len(os.listdir("/proc/self/fd")) == before


def test_pinned_process_exit_invalidates_lease():
    child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(10)"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with channel.ProcessPin(child.pid, os.getuid()) as pin:
            pin.check()
            child.terminate()
            child.wait(timeout=3)
            with pytest.raises(channel.ChannelError):
                pin.check()
        with pytest.raises(channel.ChannelError):
            pin.check()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=3)


def test_unknown_socket_and_replacement_are_preserved(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "native-host.sock"
    path.write_text("unrelated user object")
    with channel.ProcessPin(os.getpid(), os.getuid()) as peer:
        with pytest.raises(channel.ChannelError):
            channel.HostChannel(tmp_path, peer)
        assert path.read_text() == "unrelated user object"
        path.unlink()  # Only this test's synthetic fixture.
        host = channel.HostChannel(tmp_path, peer)
        path.unlink()
        path.write_text("replacement")
        host.close()
        assert path.read_text() == "replacement"


def test_dispatch_failure_consumes_sequence_and_client_never_retries(host):
    client = channel.HermesChannel(host.path, timeout=.5)
    observed = []

    def fail(event):
        observed.append(event)
        raise ValueError("synthetic secret must not be reflected")

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(host.serve_once, fail)
        with pytest.raises(channel.ChannelError, match="^native_host_channel_unavailable$"):
            client.exchange({"kind": "synthetic-load"})
        with pytest.raises(channel.ChannelError):
            task.result(timeout=2)
    with pytest.raises(channel.ChannelError):
        client.exchange({"kind": "synthetic-load"})
    assert len(observed) == 1
    rejected(host, packet())


@pytest.mark.parametrize("bad_result", [None, {str(i): i for i in range(33)}, {"value": "x" * channel.MAX_PACKET}])
def test_invalid_dispatch_response_cannot_become_success(host, bad_result):
    client = channel.HermesChannel(host.path, timeout=.5)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(host.serve_once, lambda _: bad_result)
        with pytest.raises(channel.ChannelError):
            client.exchange({"kind": "synthetic-call"})
        with pytest.raises(channel.ChannelError):
            task.result(timeout=2)


def test_missing_os_capability_and_unsafe_paths_fail_closed(tmp_path, monkeypatch):
    with channel.ProcessPin(os.getpid(), os.getuid()) as peer:
        tmp_path.chmod(0o755)
        with pytest.raises(channel.ChannelError):
            channel.HostChannel(tmp_path, peer)
        tmp_path.chmod(0o700)
        link = tmp_path / "link"
        link.symlink_to(tmp_path, target_is_directory=True)
        with pytest.raises(channel.ChannelError):
            channel.HostChannel(link, peer)
    with pytest.raises(channel.ChannelError):
        channel.ProcessPin(os.getpid(), 0)
    monkeypatch.setattr(channel, "_pidfd_open", lambda _: (_ for _ in ()).throw(OSError("unavailable")))
    with pytest.raises(channel.ChannelError):
        channel.ProcessPin(os.getpid(), os.getuid())


def test_transport_timeout_poisoning_is_bounded(host):
    client = channel.HermesChannel(host.path, timeout=.03)
    # Listener exists but no server loop handles it; cannot become a success.
    with pytest.raises(channel.ChannelError):
        client.exchange({"kind": "synthetic-load"})
    with pytest.raises(channel.ChannelError):
        client.exchange({"kind": "synthetic-load"})


def test_wrong_uid_cannot_supply_an_event(tmp_path):
    tmp_path.chmod(0o700)
    with channel.ProcessPin(os.getpid(), os.getuid() + 1) as peer, channel.HostChannel(tmp_path, peer) as host:
        rejected(host, packet())


def test_client_rejects_another_process_before_connecting(host, monkeypatch):
    client = channel.HermesChannel(host.path)
    parent = os.getpid()
    monkeypatch.setattr(channel.os, "getpid", lambda: parent + 1)
    with pytest.raises(channel.ChannelError):
        client.exchange({"kind": "synthetic-load"})


def test_non_linux_is_explicitly_unsupported(monkeypatch):
    monkeypatch.setattr(channel.sys, "platform", "win32")
    with pytest.raises(channel.ChannelError):
        channel.ProcessPin(os.getpid(), os.getuid())


@pytest.mark.parametrize("expected", ["actual", (0, os.getuid(), os.getgid()),
                                      (os.getpid(), os.getuid() + 1, os.getgid()),
                                      (os.getpid(), os.getuid(), os.getgid() + 1)])
def test_client_authenticates_kernel_response_and_poisoning(host, expected):
    valid = expected == "actual"
    if valid:
        expected = (os.getpid(), os.getuid(), os.getgid())
    client = channel.HermesChannel(host.path, server_credentials=expected)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(host.serve_once, lambda _: {"accepted": True})
        if valid:
            assert client.exchange({"kind": "synthetic-call"}) == {"accepted": True}
        else:
            # A same-namespace imposter cannot impersonate a PID-0 outer host,
            # even when it owns and replaces the well-known socket path.
            with pytest.raises(channel.ChannelError):
                client.exchange({"kind": "synthetic-call"})
            with pytest.raises(channel.ChannelError):
                client.exchange({"kind": "synthetic-call"})
        task.result(timeout=2)


@pytest.mark.parametrize("credentials", [(), [0, 1000, 1000], (False, 1000, 1000),
                                         (-1, 1000, 1000), (0, 0, 1000), (0, 1000, 0)])
def test_invalid_explicit_server_credentials_rejected(host, credentials):
    with pytest.raises(channel.ChannelError):
        channel.HermesChannel(host.path, server_credentials=credentials)


def test_namespace_channel_pins_directory_and_owns_only_its_socket(tmp_path):
    original = tmp_path / "original"
    original.mkdir(mode=0o700)
    fd = os.open(original, os.O_RDONLY | os.O_DIRECTORY)
    with channel.ProcessPin(os.getpid(), os.getuid()) as peer:
        server = channel.NamespaceHostChannel(fd, peer)
        os.close(fd)  # The listener owns its independent duplicate.
        moved = tmp_path / "moved"
        original.rename(moved)
        original.mkdir(mode=0o700)
        replacement = original / "native-host.sock"
        replacement.write_text("unrelated object")
        try:
            client = channel.HermesChannel(moved / "native-host.sock",
                server_credentials=(os.getpid(), os.getuid(), os.getgid()))
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                task = pool.submit(server.serve_once, lambda _: {"accepted": True})
                assert client.exchange({}) == {"accepted": True}
                task.result(timeout=2)
        finally:
            server.close()
        assert not (moved / "native-host.sock").exists()
        assert replacement.read_text() == "unrelated object"


def test_namespace_channel_refuses_existing_object_and_preserves_replacement(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "native-host.sock"
    path.write_text("existing")
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with channel.ProcessPin(os.getpid(), os.getuid()) as peer:
            with pytest.raises(channel.ChannelError):
                channel.NamespaceHostChannel(fd, peer)
            assert path.read_text() == "existing"
            path.unlink()
            server = channel.NamespaceHostChannel(fd, peer)
            path.unlink()
            path.write_text("replacement")
            server.close()
            assert path.read_text() == "replacement"
    finally:
        os.close(fd)
