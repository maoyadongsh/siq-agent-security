"""Lifecycle regression tests use a fake executable only as a process fixture."""

import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("personal_start_local", Path(__file__).with_name("start-local.py"))
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_repeated_start_reuses_verified_service_without_spawning(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "healthy", lambda *args: True)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: pytest.fail("reused service spawned a child"))
    result = launcher.ensure_started(tmp_path / "binary", tmp_path / "state", 47611)
    assert result["reused"] is True
    assert not (tmp_path / "state").exists()


def test_unknown_port_owner_is_not_started_or_killed(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, "healthy", lambda *args: False)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: pytest.fail("occupied port spawned a child"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(RuntimeError, match="占用"):
            launcher.ensure_started(tmp_path / "binary", tmp_path / "state", port)
        assert listener.fileno() >= 0
        assert not (tmp_path / "state").exists()


@pytest.mark.skipif(
    os.name == "nt", reason="fixture uses Unix executable shebang; Windows runtime evidence tracked separately"
)
def test_spawn_failure_preserves_writer_lock(tmp_path):
    binary = tmp_path / "failed-binary"
    binary.write_text(f"#!{sys.executable}\nraise SystemExit(1)\n")
    binary.chmod(0o700)
    state = tmp_path / "state"
    state.mkdir()
    lock = state / "writer.lock"
    lock.write_text("owned-lock-fixture")
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    with pytest.raises(RuntimeError, match="启动失败"):
        launcher.ensure_started(binary, state, port)
    assert lock.read_text() == "owned-lock-fixture"


def test_health_requires_protocol_not_exit_code(monkeypatch, tmp_path):
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess([], 0, "<html>other app</html>")
    )
    assert not launcher.healthy(tmp_path / "binary", 47611, {})
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [],
            0,
            json.dumps(
                {
                    "schema_version": "local-service-health/v1",
                    "product": "siq-agent-security",
                    "local_mode": True,
                    "status": "ready",
                }
            ),
        ),
    )
    assert launcher.healthy(tmp_path / "binary", 47611, {})
