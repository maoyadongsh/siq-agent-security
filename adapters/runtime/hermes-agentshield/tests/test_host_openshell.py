"""Backend contract negatives; actual Docker/OpenShell integration is separate."""

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

directory = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("openshell_backend_test", directory / "host_openshell.py",
                                             submodule_search_locations=[str(directory)])
backend = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backend
spec.loader.exec_module(backend)


@pytest.fixture
def fixture(monkeypatch):
    options = {"container_id": "a" * 64, "image_id": "sha256:" + "b" * 64, "namespace": "owned",
               "sandbox": "owned-hermes", "pid": 123, "init_pid": 124, "uid": 1000, "gid": 1000,
               "artifact_sha256": "c" * 64, "cgroup": "0::/docker/owned\n"}
    actual = [options["container_id"], options["image_id"], 124, True, False, "", "owned",
              "owned", "owned-hermes", "sandbox-id"]
    monkeypatch.setattr(backend, "_inspect", lambda _: actual[:])
    monkeypatch.setattr(backend, "_members", lambda _: {123, 124})
    monkeypatch.setattr(backend, "_pid_chain", lambda pid: [pid, 1 if pid == 124 else 43])
    monkeypatch.setattr(backend, "_trusted", lambda *_, **__: (1, 2, 3))
    monkeypatch.setattr(backend, "_bounded", lambda *_: options["cgroup"].encode())
    monkeypatch.setattr(backend, "_namespace", lambda pid: (1, 10 if pid in (123, 124) else 20))
    return options, actual


def check(value):
    return value(123, 1000, 1000, "c" * 64)


def test_matching_backend_can_be_checked_repeatedly(fixture):
    options, _ = fixture
    value = backend.OpenShellBackend(**options)
    assert check(value) is None
    assert check(value) is None


def test_non_root_host_does_not_require_root_init_namespace_inode(fixture, monkeypatch):
    options, _ = fixture

    def namespace(pid):
        if pid == 124:
            raise PermissionError("root init namespace is not readable")
        return (1, 10 if pid == 123 else 20)

    monkeypatch.setattr(backend, "_namespace", namespace)
    value = backend.OpenShellBackend(**options)
    assert check(value) is None


@pytest.mark.parametrize("change", [
    {"container_id": "a" * 12}, {"container_id": "--help"}, {"image_id": "latest"},
    {"pid": True}, {"init_pid": 0}, {"uid": 0}, {"gid": False}, {"artifact_sha256": "not-a-digest"},
    {"namespace": "--other"}, {"sandbox": "name\nsecret"}, {"cgroup": ""}, {"cgroup": "x" * 65537},
])
def test_invalid_binding_never_calls_docker(fixture, monkeypatch, change):
    options, _ = fixture
    monkeypatch.setattr(backend, "_inspect", lambda _: pytest.fail("invalid input reached Docker"))
    with pytest.raises(backend.RuntimeGuardError):
        backend.OpenShellBackend(**(options | change))


@pytest.mark.parametrize("index,replacement", [
    (0, "d" * 64), (1, "sha256:" + "d" * 64), (2, 125), (2, True), (3, False),
    (4, True), (5, "host"), (6, "host"), (6, "container:other"), (7, "other"),
    (8, "other"), (9, ""), (9, "changed-id"),
])
def test_changed_ownership_permanently_invalidates(fixture, index, replacement):
    options, actual = fixture
    value = backend.OpenShellBackend(**options)
    old, actual[index] = actual[index], replacement
    with pytest.raises(backend.RuntimeGuardError):
        check(value)
    actual[index] = old
    with pytest.raises(backend.RuntimeGuardError):
        check(value)


@pytest.mark.parametrize("target", ["_bounded", "_namespace", "_trusted"])
def test_real_process_or_endpoint_drift_refused(fixture, monkeypatch, target):
    options, _ = fixture
    value = backend.OpenShellBackend(**options)
    monkeypatch.setattr(backend, target, lambda *_, **__: b"changed")
    with pytest.raises(backend.RuntimeGuardError):
        check(value)


def test_transport_failure_redacted_and_terminal(fixture, monkeypatch):
    options, _ = fixture
    value = backend.OpenShellBackend(**options)

    def fail(_):
        raise RuntimeError("private daemon output")

    monkeypatch.setattr(backend, "_inspect", fail)
    with pytest.raises(backend.RuntimeGuardError, match="^native_openshell_backend_unverified$"):
        check(value)


def test_process_identity_mismatch_refused(fixture):
    options, _ = fixture
    value = backend.OpenShellBackend(**options)
    with pytest.raises(backend.RuntimeGuardError):
        value(125, 1000, 1000, "c" * 64)


@pytest.mark.parametrize("members", [{123}, {124}, {125, 126}])
def test_cgroup_alone_does_not_replace_docker_process_membership(fixture, monkeypatch, members):
    options, _ = fixture
    value = backend.OpenShellBackend(**options)
    monkeypatch.setattr(backend, "_members", lambda _: members)
    with pytest.raises(backend.RuntimeGuardError):
        check(value)


@pytest.mark.parametrize("chain", [[124], [124, 2], [124, 8, 1]])
def test_init_namespace_chain_must_match_runtime_depth(fixture, monkeypatch, chain):
    options, _ = fixture
    value = backend.OpenShellBackend(**options)
    monkeypatch.setattr(backend, "_pid_chain", lambda pid: chain if pid == 124 else [123, 43])
    with pytest.raises(backend.RuntimeGuardError):
        check(value)


@pytest.mark.parametrize("raw", [b"PID\n123\n123\n", b"PID\n--help\n", b"PID\n0\n", b"other\n123\n"])
def test_invalid_membership_output_refused(monkeypatch, raw):
    monkeypatch.setattr(backend, "_capture", lambda *_: raw)
    with pytest.raises(backend.RuntimeGuardError):
        backend._members("a" * 64)


def test_fixed_membership_projection(monkeypatch):
    def capture(argv, limit):
        assert argv == ["top", "a" * 64, "-eo", "pid"] and limit == 65536
        return b"PID\n 123\n 124\n"
    monkeypatch.setattr(backend, "_capture", capture)
    assert backend._members("a" * 64) == {123, 124}


def test_fork_identity_checked_before_lock(fixture, monkeypatch):
    options, _ = fixture
    value = backend.OpenShellBackend(**options)
    with value._lock:
        monkeypatch.setattr(backend.os, "getpid", lambda: value._owner + 1)
        with pytest.raises(backend.RuntimeGuardError):
            check(value)


@pytest.mark.parametrize("raw", [b"x", b"null\n" * 9, b"x" * 8193])
def test_malformed_or_oversized_cli_output_refused(monkeypatch, raw):
    def run(_argv, **kwargs):
        kwargs["stdout"].write(raw)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(backend.subprocess, "run", run)
    with pytest.raises((backend.RuntimeGuardError, ValueError)):
        backend._inspect("a" * 64)


def test_command_fixed_local_read_only_and_environment_clean(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://untrusted.invalid")
    monkeypatch.setenv("LD_PRELOAD", "/untrusted")

    def run(argv, **kwargs):
        assert argv[:6] == ["/usr/bin/docker", "--host", "unix:///run/docker.sock", "inspect", "--type", "container"]
        assert argv[-1] == "a" * 64
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin", "LANG": "C"}
        assert kwargs["cwd"] == "/" and kwargs["timeout"] == 2
        assert kwargs["stderr"] is subprocess.DEVNULL and kwargs["stdin"] is subprocess.DEVNULL
        kwargs["stdout"].write(("\n".join(json.dumps(i) for i in range(10)) + "\n").encode())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(backend.subprocess, "run", run)
    assert backend._inspect("a" * 64) == list(range(10))


@pytest.mark.parametrize("mode,uid,is_socket", [
    (stat.S_IFREG | 0o777, 0, False), (stat.S_IFREG | 0o755, 1000, False),
    (stat.S_IFLNK | 0o777, 0, False), (stat.S_IFSOCK | 0o666, 0, True),
])
def test_untrusted_executable_or_socket_rejected(monkeypatch, mode, uid, is_socket):
    monkeypatch.setattr(backend.Path, "lstat", lambda _: SimpleNamespace(st_mode=mode, st_uid=uid))
    with pytest.raises(backend.RuntimeGuardError):
        backend._trusted(Path("/fixture"), socket=is_socket)


@pytest.mark.skipif(os.getuid() == 0, reason="root-owned paths are a non-root host boundary")
def test_actual_user_owned_executable_path_refused(tmp_path):
    path = tmp_path / "docker"
    path.write_text("not executable authority")
    path.chmod(0o755)
    with pytest.raises(backend.RuntimeGuardError):
        backend._trusted(path)
