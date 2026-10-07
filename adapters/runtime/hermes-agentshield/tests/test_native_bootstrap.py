"""Protected startup coordination; real privileged namespace proof is live E2E."""

# ruff: noqa: SIM117 - keep exception assertions separate from guarded execution.

import concurrent.futures
import importlib.util
import os
import select
import signal
import socket
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux" or os.getuid() == 0, reason="Linux non-root image profile")
AGENT = "hri-" + "a" * 32


@pytest.fixture
def fixture():
    name = "siq_bootstrap_test_" + uuid.uuid4().hex
    directory = Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location(name, directory / "native_bootstrap.py",
                                                 submodule_search_locations=[str(directory)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(prefix="siq-boot-") as scratch:
        yield module, Path(scratch)
    for key in list(sys.modules):
        if key == name or key.startswith(name + "."):
            del sys.modules[key]


def bootstrap(fixture):
    module, root = fixture
    return module.ImageBootstrap(AGENT, "owned", str(root / "channel"))


def endpoint(root):
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    path = root / "channel/native-host.sock"
    listener.bind(str(path))
    path.chmod(0o600)
    return listener


def test_ready_and_configuration_never_claim_authority(fixture, monkeypatch):
    module, root = fixture
    monkeypatch.setenv("SIQ_AGENT_SECURITY_AGENT_ID", "model-selected-agent")
    monkeypatch.setenv("SIQ_AGENT_SECURITY_SESSION_NAMESPACE", "model-selected-namespace")
    value = bootstrap(fixture)
    try:
        ready = value.ready()
        assert ready["runtime_state"] == "unverified"
        assert ready["agent_id"] == AGENT and ready["session_namespace"] == "owned"
        assert ready["pid"] == os.getpid() and ready["uid"] == os.getuid()
        assert (root / "channel").stat().st_mode & 0o777 == 0o700
        with pytest.raises(module.native_dispatch.DispatchError):
            with module.native_dispatch.task_scope("unconfigured", "session"):
                pytest.fail("unconfigured runtime began a task")
        with endpoint(root):
            value.configure(timeout=.1)
            assert value.ready()["runtime_state"] == "unverified"
        value.close()
        with pytest.raises(module.native_dispatch.DispatchError):
            with module.native_dispatch.task_scope("closed", "session"):
                pytest.fail("closed bootstrap began a task")
        assert (root / "channel/native-host.sock").exists()  # Never deletes host objects.
    finally:
        value.close()


@pytest.mark.parametrize("field,value", [
    ("agent", "other"), ("agent", None), ("namespace", "../other"), ("namespace", "x" * 65),
    ("path", "relative"), ("path", "/tmp/../escape"), ("path", "/tmp//escape"),
    ("path", "/tmp/line\nbreak"), ("path", "/tmp/back\\slash"),
    ("path", "/tmp/" + "x" * 100), ("path", "/"),
])
def test_invalid_bootstrap_cannot_be_retried_with_another_identity(fixture, field, value):
    module, root = fixture
    args = {"agent": AGENT, "namespace": "owned", "path": str(root / "channel")}
    args[field] = value
    with pytest.raises(module.BootstrapError, match="^native_runtime_bootstrap_unavailable$"):
        module.ImageBootstrap(args["agent"], args["namespace"], args["path"])
    assert not (root / "channel").exists()
    with pytest.raises(module.BootstrapError):
        bootstrap(fixture)


def test_existing_directory_and_contents_are_preserved(fixture):
    module, root = fixture
    path = root / "channel"
    path.mkdir(mode=0o700)
    (path / "user-marker").write_text("preserve")
    with pytest.raises(module.BootstrapError):
        bootstrap(fixture)
    assert (path / "user-marker").read_text() == "preserve"


@pytest.mark.parametrize("unsafe", ["symlink", "writable"])
def test_unsafe_ancestor_never_receives_a_channel_directory(fixture, unsafe):
    module, root = fixture
    target = root / "target"
    target.mkdir(mode=0o700)
    parent = target
    if unsafe == "symlink":
        parent = root / "link"
        parent.symlink_to(target, target_is_directory=True)
    else:
        target.chmod(0o777)
    with pytest.raises(module.BootstrapError):
        module.ImageBootstrap(AGENT, "owned", str(parent / "channel"))
    assert not (target / "channel").exists()


@pytest.mark.parametrize("change", ["replacement", "permissions", "symlink"])
def test_directory_change_permanently_closes_bootstrap(fixture, change):
    module, root = fixture
    value = bootstrap(fixture)
    path = root / "channel"
    if change == "permissions":
        path.chmod(0o777)
    else:
        path.rename(root / "original")
        if change == "replacement":
            path.mkdir(mode=0o700)
        else:
            path.symlink_to(root / "original", target_is_directory=True)
    with pytest.raises(module.BootstrapError):
        value.ready()
    with pytest.raises(module.BootstrapError):
        value.configure(timeout=.01)
    value.close()
    assert path.exists()


@pytest.mark.parametrize("kind", ["file", "symlink", "fifo", "socket-mode"])
def test_nonprivate_endpoint_is_rejected_without_deleting_it(fixture, kind):
    module, root = fixture
    value = bootstrap(fixture)
    path = root / "channel/native-host.sock"
    listener = None
    if kind == "file":
        path.write_text("user-marker")
    elif kind == "symlink":
        path.symlink_to(root / "not-a-host")
    elif kind == "fifo":
        os.mkfifo(path, 0o600)
    else:
        listener = endpoint(root)
        path.chmod(0o666)
    try:
        with pytest.raises(module.BootstrapError):
            value.configure(timeout=.01)
        assert path.lstat() is not None
    finally:
        value.close()
        if listener:
            listener.close()


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf"), 61, "1"])
def test_invalid_wait_budget_refused(fixture, timeout):
    module, _ = fixture
    value = bootstrap(fixture)
    with pytest.raises(module.BootstrapError):
        value.configure(timeout=timeout)
    value.close()


def test_timeout_is_bounded_and_terminal(fixture):
    module, root = fixture
    value = bootstrap(fixture)
    started = time.monotonic()
    with pytest.raises(module.BootstrapError):
        value.configure(timeout=.02)
    assert time.monotonic() - started < 1
    with endpoint(root), pytest.raises(module.BootstrapError):
        value.configure(timeout=.1)
    assert module.native_dispatch._runtime is None
    value.close()


def test_close_interrupts_startup_wait(fixture):
    module, _ = fixture
    value = bootstrap(fixture)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        waiting = pool.submit(value.configure, timeout=30)
        value.close()
        with pytest.raises(module.BootstrapError):
            waiting.result(timeout=1)


def test_only_one_concurrent_initialization_can_claim_process(fixture):
    module, root = fixture
    barrier = threading.Barrier(2)

    def attempt(index):
        barrier.wait(timeout=1)
        try:
            return module.ImageBootstrap(AGENT, "owned", str(root / ("channel" + str(index))))
        except module.BootstrapError:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        values = list(pool.map(attempt, (1, 2)))
    successful = [v for v in values if v is not None]
    assert len(successful) == 1
    successful[0].close()


def test_reconfiguration_invalidates_instead_of_replacing_callbacks(fixture):
    module, root = fixture
    value = bootstrap(fixture)
    with endpoint(root):
        value.configure(timeout=.1)
        with pytest.raises(module.BootstrapError):
            value.configure(timeout=.1)
        with pytest.raises(module.native_dispatch.DispatchError):
            with module.native_dispatch.task_scope("after-reconfiguration", "session"):
                pytest.fail("reconfigured runtime executed")
    value.close()


def test_endpoint_replacement_refuses_execution_and_preserves_replacement(fixture):
    module, root = fixture
    value = bootstrap(fixture)
    with endpoint(root):
        value.configure(timeout=.1)
        (root / "channel/native-host.sock").rename(root / "old.sock")
        with endpoint(root):
            with pytest.raises(module.native_dispatch.DispatchError):
                with module.native_dispatch.task_scope("replacement", "session"):
                    (root / "effect").write_text("must-not-execute")
            assert (root / "channel/native-host.sock").exists()
    assert not (root / "effect").exists()
    value.close()


@pytest.mark.parametrize("change", ["platform", "effective-uid", "effective-gid"])
def test_unsupported_process_profile_is_rejected(fixture, monkeypatch, change):
    module, root = fixture
    with monkeypatch.context() as patched:
        if change == "platform":
            patched.setattr(sys, "platform", "unsupported-test-platform")
        elif change == "effective-uid":
            patched.setattr(os, "geteuid", lambda: 0)
        else:
            patched.setattr(os, "getegid", lambda: 0)
        with pytest.raises(module.BootstrapError):
            bootstrap(fixture)
    assert not (root / "channel").exists()


def test_same_namespace_fake_host_cannot_authorize_a_task(fixture):
    module, root = fixture
    value = bootstrap(fixture)
    channel = sys.modules[module.__name__ + ".native_channel"]
    events = []

    def forged_allow(event):
        events.append(event["kind"])
        return {"accepted": True}

    with channel.ProcessPin(os.getpid(), os.getuid()) as peer:
        with channel.HostChannel(root / "channel", peer) as host:
            value.configure(timeout=.1)
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                serving = pool.submit(host.serve_once, forged_allow)
                with pytest.raises(module.native_dispatch.DispatchError):
                    with module.native_dispatch.task_scope("task", "session"):
                        (root / "forbidden-effect").write_text("must-not-execute")
                serving.result(timeout=2)
    assert events == ["task_begin"] and not (root / "forbidden-effect").exists()
    with pytest.raises(module.BootstrapError):
        value.ready()
    value.close()


def test_forked_child_never_waits_on_inherited_bootstrap_lock(fixture):
    module, _ = fixture
    value = bootstrap(fixture)
    entered, release = threading.Event(), threading.Event()

    def hold_lock():
        with value._lock:
            entered.set()
            release.wait(timeout=5)

    thread = threading.Thread(target=hold_lock)
    thread.start()
    assert entered.wait(timeout=1)
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            for operation in (value.ready, value.configure, lambda: value.exchange({}), value.close):
                try:
                    operation()
                except module.BootstrapError:
                    continue
                os._exit(3)
            os.write(write_fd, b"refused")
            os._exit(0)
        except BaseException:  # noqa: BLE001 - child failure exits; never returns into pytest.
            os._exit(4)
    os.close(write_fd)
    try:
        ready, _, _ = select.select([read_fd], [], [], 2)
        if not ready:
            os.kill(pid, signal.SIGKILL)  # Only this test's own stuck child.
        _, status = os.waitpid(pid, 0)
        assert ready and os.read(read_fd, 32) == b"refused" and status == 0
    finally:
        os.close(read_fd)
        release.set()
        thread.join(timeout=1)
        value.close()
