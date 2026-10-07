"""Real channel/HTTP loop; permission Authority and process guard are fixtures."""

import concurrent.futures
import datetime
import os
import signal
import socket
import threading
import time

import pytest
from test_native_relay import channel, online, relay, setup  # noqa: F401


def expiry(seconds=30):
    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=seconds)


def event(subject):
    return {"schema_version": "native-decision-relay/v1", "request": {
        "platform": "hermes", "agent_id": subject["agent_id"], "session_id": subject["session_id"],
        "runtime_task_id": "task", "tool": "read_file", "tool_call_id": "call", "params": {"path": "/fixture"}}}


@pytest.fixture
def loop(relay):  # noqa: F811
    mapped, _reply, _received, (root, _, _, subject, guard) = relay
    with channel.ProcessPin(os.getpid(), os.getuid()) as pin, channel.HostChannel(root, pin, timeout=.05) as host:
        value = online.HostLoop(host, mapped, expires_at=expiry())
        client = channel.HermesChannel(host.path, timeout=1, server_credentials=(os.getpid(), os.getuid(), os.getgid()))
        try:
            yield value, client, event(subject), guard
        finally:
            value.close()


def test_idle_period_keeps_loop_live_and_genuine_request_succeeds(loop):
    value, client, request, guard = loop
    value.start()
    time.sleep(.12)  # More than two accept intervals, no request in flight.
    value.assert_running()
    assert client.exchange(request) == {"action": "allow", "receipt_id": "fixture-receipt"}
    value.close()
    assert not guard.closed  # Owner closes this after its namespace directory scope.
    with pytest.raises(online.OnlineError):
        value.assert_running()
    with pytest.raises(online.OnlineError):
        value.start()


def test_expired_idle_loop_cannot_forward(loop):
    initial, _, request, _ = loop
    with online.HostLoop(initial._channel, initial._relay, expires_at=expiry(.1)) as value:
        assert value._stop.wait(1)
        assert value._dispatch(request) == {"error": "native_host_unavailable"}
        with pytest.raises(online.OnlineError):
            value.assert_running()


def test_real_packet_failure_is_terminal(loop):
    value, client, _, _ = loop
    value.start()
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as wire:
        wire.settimeout(1)
        wire.connect(client._path)
        wire.send(b"not-json")
        assert wire.recv(65536) == b""
    assert value._stop.wait(1)
    with pytest.raises(online.OnlineError):
        value.start()


def test_closed_guard_is_terminal(loop):
    value, _, _, guard = loop
    value.start()
    guard.close()
    assert value._stop.wait(1)
    with pytest.raises(online.OnlineError):
        value.assert_running()


def test_accepted_connection_without_packet_is_terminal_not_idle(loop):
    value, client, _, _ = loop
    value.start()
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as wire:
        wire.settimeout(1)
        wire.connect(client._path)
        assert wire.recv(65536) == b""
    assert value._stop.wait(1)
    with pytest.raises(online.OnlineError):
        value.assert_running()


def test_application_deny_does_not_disable_unaffected_requests(loop, monkeypatch):
    value, client, request, _ = loop
    calls = []

    def decisions(event):
        calls.append(event)
        return {"action": "deny" if len(calls) == 1 else "allow", "receipt_id": "fixture"}

    monkeypatch.setattr(value._relay, "dispatch", decisions)
    value.start()
    assert client.exchange(request)["action"] == "deny"
    value.assert_running()
    assert client.exchange(request)["action"] == "allow"


def test_stop_during_allowed_response_never_delivers_allow(loop, monkeypatch):
    value, client, request, _ = loop
    entered, release = threading.Event(), threading.Event()

    def delayed(_request):
        entered.set()
        assert release.wait(2)
        return {"action": "allow", "receipt_id": "fixture"}

    monkeypatch.setattr(value._relay, "dispatch", delayed)
    value.start()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(client.exchange, request)
        assert entered.wait(1)
        closing = pool.submit(value.close)
        assert value._stop.wait(1)
        release.set()
        assert pending.result(timeout=2) == {"error": "native_host_unavailable"}
        closing.result(timeout=2)


def test_concurrent_close_is_idempotent(loop):
    value, _, _, _ = loop
    value.start()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        tasks = [pool.submit(value.close) for _ in range(3)]
        for task in tasks:
            task.result(timeout=2)
    assert not value._thread.is_alive()


@pytest.mark.parametrize("expires", [None, "tomorrow", expiry().replace(tzinfo=None), expiry(-1), expiry(3700)])
def test_invalid_expiry_refused_before_worker(loop, expires):
    value, _, _, _ = loop
    with pytest.raises(online.OnlineError):
        online.HostLoop(value._channel, value._relay, expires_at=expires)


def test_failed_start_cannot_resume_after_guard_returns(loop):
    value, _, _, guard = loop
    guard.close()
    with pytest.raises(online.OnlineError):
        value.start()
    guard.closed = False
    with pytest.raises(online.OnlineError):
        value.start()


def test_forked_controller_refuses_before_inherited_lock(loop):
    value, _, _, _ = loop
    # Hold the controller lock across fork: a child must not wait for a parent
    # thread which cannot release this inherited lock in the child process.
    with value._lock:
        pid = os.fork()
        if pid == 0:
            signal.alarm(2)
            for operation in (value.start, value.close, value.assert_running):
                try:
                    operation()
                except online.OnlineError:
                    continue
                os._exit(1)
            os._exit(0)
        _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
