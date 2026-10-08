"""Supervisor liveness uses real pidfd; session composition uses explicit fixtures."""

import contextlib
import datetime
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

directory = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("host_session_test", directory / "host_session.py",
                                             submodule_search_locations=[str(directory)])
session = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = session
spec.loader.exec_module(session)
pytestmark = pytest.mark.skipif(sys.platform != "linux" or os.getuid() == 0, reason="Non-root Linux host")


def future(seconds):
    return datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=seconds)


class GuardFixture:
    artifact = "a" * 64
    peer = object()

    def __init__(self):
        self.closed, self.events = False, []

    def verify(self):
        if self.closed:
            raise RuntimeError("fixture guard closed")

    def verify_mount(self, *_):
        self.verify()

    def close(self):
        self.closed = True
        self.events.append("guard_close")

    @contextlib.contextmanager
    def namespace_channel_directory(self, _path):
        self.events.append("directory_enter")
        try:
            yield 123
        finally:
            assert not self.closed
            self.events.append("directory_exit")


def fence(guard, seconds=30, **kwargs):
    return session.BusinessGuard(guard, supervisor_pid=kwargs.get("supervisor_pid", os.getpid()),
        expires_at=future(120), authorization_expires_at=future(seconds))


def test_live_owner_renewal_and_stop():
    guard = GuardFixture()
    value = fence(guard)
    try:
        value.verify()
        value.renew(supervisor_pid=os.getpid(), authorization_expires_at=future(60))
        value.verify_mount("source", "target")
        value.stop()
        assert not guard.closed
        with pytest.raises(session.OnlineError):
            value.verify()
        with pytest.raises(session.OnlineError):
            value.renew(supervisor_pid=os.getpid(), authorization_expires_at=future(60))
    finally:
        value.close()
    assert guard.closed


def test_dead_supervisor_pidfd_cannot_be_kept_alive_by_heartbeat():
    process = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(30)"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    value = None
    try:
        value = fence(GuardFixture(), supervisor_pid=process.pid)
        value.verify()
        process.terminate()
        process.wait(timeout=3)
        with pytest.raises(session.OnlineError):
            value.verify()
        with pytest.raises(session.OnlineError):
            value.renew(supervisor_pid=process.pid, authorization_expires_at=future(60))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        if value:
            value.close()


def test_expired_heartbeat_never_revives():
    value = fence(GuardFixture(), .03)
    try:
        time.sleep(.04)
        with pytest.raises(session.OnlineError):
            value.renew(supervisor_pid=os.getpid(), authorization_expires_at=future(60))
        with pytest.raises(session.OnlineError):
            value.verify()
    finally:
        value.close()


@pytest.mark.parametrize("seconds", [-1, 100, 3601])
def test_invalid_initial_authorization_closes_guard(seconds):
    guard = GuardFixture()
    with pytest.raises(session.OnlineError):
        fence(guard, seconds)
    assert guard.closed


def test_foreign_owner_cannot_renew():
    value = fence(GuardFixture())
    try:
        with pytest.raises(session.OnlineError):
            value.renew(supervisor_pid=os.getpid() + 1, authorization_expires_at=future(60))
        with pytest.raises(session.OnlineError):
            value.verify()
    finally:
        value.close()


def test_expiry_during_actual_verification_refuses_success(monkeypatch):
    guard = GuardFixture()
    value = fence(guard, .03)
    try:
        monkeypatch.setattr(guard, "verify", lambda: time.sleep(.04))
        with pytest.raises(session.OnlineError):
            value.verify()
    finally:
        value.close()


def test_heartbeat_cannot_exceed_fixed_session_end():
    value = session.BusinessGuard(GuardFixture(), supervisor_pid=os.getpid(),
                                  expires_at=future(20), authorization_expires_at=future(10))
    try:
        with pytest.raises(session.OnlineError):
            value.renew(supervisor_pid=os.getpid(), authorization_expires_at=future(30))
    finally:
        value.close()


@pytest.fixture
def composition(monkeypatch):
    guard = GuardFixture()
    controls = {"loop_stuck": False, "loop_start_failure": False}

    class ChannelFixture:
        def __init__(self, *_args, **_kwargs):
            guard.events.append("channel_open")

        def close(self):
            guard.events.append("channel_close")

    class LoopFixture:
        def __init__(self, _channel, relay, **_kwargs):
            self._relay = relay

        def start(self):
            if controls["loop_start_failure"]:
                raise RuntimeError("fixture start failure")
            guard.events.append("loop_start")

        def assert_running(self):
            self._relay.publisher.guard.verify()

        def close(self):
            if controls["loop_stuck"]:
                raise session.OnlineError("fixture worker still running")
            guard.events.append("loop_close")

    monkeypatch.setattr(session, "OpenShellBackend", lambda **kwargs: object())
    monkeypatch.setattr(session, "RuntimeGuard", lambda **kwargs: guard)
    monkeypatch.setattr(session, "NamespaceHostChannel", ChannelFixture)
    monkeypatch.setattr(session, "HostLoop", LoopFixture)
    with tempfile.TemporaryDirectory(prefix="siq-session-") as scratch:
        root = Path(scratch)
        config = root / "connection.json"
        config.write_text(json.dumps({"schema_version": "native-host-connection/v1", "credential": "nhp-" + "b" * 64,
                                     "verification_socket": str(root / "verify.sock")}))
        config.chmod(0o600)
        verifier = session.Verifier(config)
        value = session.HostSession(verifier, "http://127.0.0.1:12345")
        identity = {"pid": os.getpid(), "uid": os.getuid(), "gid": os.getgid(), "artifact_sha256": "a" * 64}
        args = {"backend": identity, "runtime": identity | {"executable_sha256": "c" * 64,
            "argv_sha256": "d" * 64, "mounts": [], "code_files": {}, "image_files": {"/fixture": "e" * 64},
            "image_skill_roots": []}, "subject": {"platform": "hermes", "instance_id": "hi-" + "f" * 32,
            "agent_id": "hri-" + "f" * 32, "session_id": "fixture-session"}, "installs": [],
            "channel_directory": "/fixture", "credential": "ri-" + "a" * 32 + "." + "b" * 64,
            "supervisor_pid": os.getpid(), "expires_at": future(120), "authorization_expires_at": future(30)}
        try:
            yield value, args, guard, controls, verifier
        finally:
            controls["loop_stuck"] = False
            value.close()
            verifier.close()


def test_session_composition_cleanup_order_and_no_restart(composition):
    value, args, guard, _, verifier = composition
    value.start(**args)
    value.assert_running()
    value.close()
    assert guard.events == ["directory_enter", "channel_open", "loop_start", "loop_close",
                            "channel_close", "directory_exit", "guard_close"]
    assert len(verifier._entries) == 1
    with pytest.raises(session.OnlineError):
        value.start(**args)


def test_unconfirmed_worker_shutdown_keeps_its_resources(composition):
    value, args, guard, controls, _ = composition
    value.start(**args)
    controls["loop_stuck"] = True
    with pytest.raises(session.OnlineError):
        value.close()
    assert not guard.closed and "directory_exit" not in guard.events
    with pytest.raises(session.OnlineError):
        value._fence.verify()
    controls["loop_stuck"] = False
    value.close()
    assert guard.closed and "directory_exit" in guard.events


def test_partial_startup_closes_only_its_own_resources(composition):
    value, args, guard, controls, verifier = composition
    controls["loop_start_failure"] = True
    with pytest.raises(session.OnlineError):
        value.start(**args)
    assert guard.closed and "directory_exit" in guard.events
    assert verifier._entries  # Not removed or replaced with an apparently new session.


@pytest.mark.parametrize("change", [{"verify_backend": lambda *_: None}, {"mounts": [{"target": "/"}]}, {"pid": 1}])
def test_caller_cannot_replace_backend_or_runtime_identity(composition, change):
    value, args, guard, _, _ = composition
    args["runtime"].update(change)
    with pytest.raises(session.OnlineError):
        value.start(**args)
    assert "directory_enter" not in guard.events


def test_closed_session_cannot_be_started_or_renewed(composition):
    value, args, _, _, _ = composition
    value.close()
    with pytest.raises(session.OnlineError):
        value.start(**args)
    with pytest.raises(session.OnlineError):
        value.renew(supervisor_pid=os.getpid(), authorization_expires_at=future(30))
