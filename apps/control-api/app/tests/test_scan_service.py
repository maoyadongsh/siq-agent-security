"""Real local socket/peer/EOF tests; worker doubles are explicitly component-only."""
import json
import os
import socket
import struct
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app import scan_execution, scan_service
from app.config import load_settings
from app.db import session_scope
from app.models import AgentAsset, AuditEvent, Finding, OutboxEvent
from app.scan_service import ScanService
from app.scan_service_transport import (
    HEADER,
    MAGIC,
    peer_uid,
    read_exact,
    read_frame,
    service_exchange,
    validate_endpoint,
)
from app.scan_transport import ScanFailure
from app.scan_worker import MAX_INPUT, MAX_OUTPUT
from app.tests.binding_helpers import make_instance


@pytest.fixture
def service_factory():
    services = []
    with tempfile.TemporaryDirectory(prefix="siq-scan-") as temporary:
        root = Path(temporary)
        root.chmod(0o710)

        def start(uid=None, concurrency=2):
            path = root / f"scan-{len(services)}.sock"
            service = ScanService(str(path), os.getuid() if uid is None else uid, concurrency)
            service.open()
            thread = threading.Thread(target=service.serve)
            thread.start()
            services.append((service, thread))
            return service

        yield start
        for service, thread in services:
            service.stopping.set()
            thread.join(10)
            assert not thread.is_alive()
            assert not service.threads
            assert not service.path.exists()


def test_service_frames_actual_peer_and_single_consumption(service_factory, monkeypatch):
    calls = []
    def worker(argv, payload, **kwargs):
        calls.append((argv, payload, kwargs))
        return b'{"synthetic":"component-result"}'
    monkeypatch.setattr(scan_service, "exchange", worker)
    service = service_factory()
    result = service_exchange(str(service.path), os.getuid(), b'{"synthetic":"request"}')
    assert result == b'{"synthetic":"component-result"}'
    assert len(calls) == 1 and calls[0][0][0] == "/usr/bin/bwrap"
    assert 0 < calls[0][2]["timeout"] <= 5
    with socket.socket(socket.AF_UNIX) as connection:
        connection.connect(str(service.path))
        assert peer_uid(connection) == os.getuid()
        connection.sendall(HEADER.pack(MAGIC, 0, 2) + b"{}" + HEADER.pack(MAGIC, 0, 2) + b"{}")
        connection.shutdown(socket.SHUT_WR)
        assert read_exact(connection, HEADER.size, time.monotonic() + 1) == HEADER.pack(MAGIC, 3, 0)
        # Closing an invalid request with unread trailing bytes may produce Linux RST.
        try:
            assert connection.recv(1) == b""
        except ConnectionResetError:
            pass
    assert len(calls) == 1  # A second request never reaches a worker.


def test_unauthorized_uid_rejected_before_worker(service_factory, monkeypatch):
    calls = []
    monkeypatch.setattr(scan_service, "exchange", lambda *a, **k: calls.append(a))
    service = service_factory(os.getuid() + 1)
    with pytest.raises(ScanFailure):
        service_exchange(str(service.path), os.getuid(), b"{}")
    assert calls == []


def test_client_rejects_wrong_server_uid_before_sending(service_factory, monkeypatch):
    # Keep real SO_PEERCRED and bypass only ownership check to exercise identity layer.
    from app import scan_service_transport as transport
    calls = []
    monkeypatch.setattr(scan_service, "exchange", lambda *a, **k: calls.append(a))
    service = service_factory()
    monkeypatch.setattr(transport, "validate_endpoint", lambda *a: None)
    with pytest.raises(ScanFailure, match="peer_invalid"):
        service_exchange(str(service.path), os.getuid() + 1, b"{}")
    assert calls == []


@pytest.mark.parametrize("mutation", ["socket_mode", "writable_parent", "symlink", "wrong_owner", "regular"])
def test_endpoint_protection_rejects_replacement_vectors(service_factory, mutation):
    service = service_factory()
    path, owner = service.path, os.getuid()
    alternate = path.parent / "alternate.sock"
    if mutation == "socket_mode":
        path.chmod(0o666)
    elif mutation == "writable_parent":
        path.parent.chmod(0o730)
    elif mutation == "symlink":
        alternate.symlink_to(path)
        path = alternate
    elif mutation == "wrong_owner":
        owner += 1
    else:
        alternate.write_bytes(b"not a socket")
        alternate.chmod(0o660)
        path = alternate
    with pytest.raises(ScanFailure, match="endpoint_invalid"):
        validate_endpoint(str(path), owner)


@pytest.mark.parametrize("raw", [
    b"wrong", struct.pack("!8sBI", b"BADMAGIC", 0, 2) + b"{}",
    HEADER.pack(MAGIC, 4, 0), HEADER.pack(MAGIC, 2, 1) + b"x",
    HEADER.pack(MAGIC, 0, 0), HEADER.pack(MAGIC, 0, MAX_OUTPUT + 1),
    HEADER.pack(MAGIC, 0, 3) + b"{}", HEADER.pack(MAGIC, 0, 2) + b"{}x",
])
def test_client_rejects_bad_response_frames(raw):
    left, right = socket.socketpair()
    with left, right:
        right.sendall(raw)
        right.shutdown(socket.SHUT_WR)
        with pytest.raises(ScanFailure):
            read_frame(left, time.monotonic() + 1, response=True)


def test_request_limit_checked_before_body_and_worker(service_factory, monkeypatch):
    calls = []
    monkeypatch.setattr(scan_service, "exchange", lambda *a, **k: calls.append(a))
    service = service_factory()
    with socket.socket(socket.AF_UNIX) as connection:
        connection.connect(str(service.path))
        connection.sendall(HEADER.pack(MAGIC, 0, MAX_INPUT + 1))
        connection.shutdown(socket.SHUT_WR)
        assert read_frame(connection, time.monotonic() + 1, response=True) == (3, b"")
    assert calls == []


def test_partial_sender_deadline_and_service_recovers(service_factory, monkeypatch):
    monkeypatch.setattr(scan_service, "TIMEOUT", .1)
    monkeypatch.setattr(scan_service, "exchange", lambda *a, **k: b"{}")
    service = service_factory(concurrency=1)
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(1)
        connection.connect(str(service.path))
        connection.sendall(b"S")
        started = time.monotonic()
        assert connection.recv(1) == b""
        assert time.monotonic() - started < .8
    assert service_exchange(str(service.path), os.getuid(), b"{}") == b"{}"


def test_absolute_deadline_not_refreshed_by_each_chunk():
    left, right = socket.socketpair()
    def trickle():
        try:
            for byte in HEADER.pack(MAGIC, 0, 2) + b"{}":
                right.sendall(bytes([byte]))
                time.sleep(.02)
        except OSError:
            pass
    with left, right:
        thread = threading.Thread(target=trickle)
        thread.start()
        start = time.monotonic()
        with pytest.raises((TimeoutError, ScanFailure)):
            read_frame(left, start + .07)
        assert time.monotonic() - start < .3
        left.close()
        thread.join(1)


def test_busy_does_not_start_or_queue_a_worker(service_factory, monkeypatch):
    calls, entered, release = [], threading.Event(), threading.Event()
    def worker(*args, **kwargs):
        calls.append(args)
        entered.set()
        assert release.wait(3)
        return b"{}"
    monkeypatch.setattr(scan_service, "exchange", worker)
    service = service_factory(concurrency=1)
    results = []
    first = threading.Thread(target=lambda: results.append(service_exchange(str(service.path), os.getuid(), b"{}")))
    first.start()
    try:
        assert entered.wait(1)
        with socket.socket(socket.AF_UNIX) as second:
            second.connect(str(service.path))
            assert read_frame(second, time.monotonic() + 1, response=True) == (1, b"")
        assert len(calls) == 1
    finally:
        release.set()
        first.join(2)
    assert results == [b"{}"]


@pytest.mark.parametrize("failure", ["worker", "oversize", "empty"])
def test_worker_failure_no_retry_and_next_connection_recovers(service_factory, monkeypatch, failure):
    calls = []
    def worker(*args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            if failure == "worker":
                raise ScanFailure("threat_scan_worker_failed")
            return b"x" * (MAX_OUTPUT + 1) if failure == "oversize" else b""
        return b"{}"
    monkeypatch.setattr(scan_service, "exchange", worker)
    service = service_factory()
    with pytest.raises(ScanFailure, match="worker_failed"):
        service_exchange(str(service.path), os.getuid(), b"{}")
    assert len(calls) == 1
    assert service_exchange(str(service.path), os.getuid(), b"{}") == b"{}"
    assert len(calls) == 2


def test_existing_socket_is_not_adopted_or_unlinked(service_factory):
    service = service_factory()
    info = service.path.stat()
    duplicate = ScanService(str(service.path), os.getuid())
    with pytest.raises(OSError):
        duplicate.open()
    assert service.path.stat().st_ino == info.st_ino


def test_thread_start_failure_closes_connection_and_service(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="siq-scan-start-") as directory:
        root = Path(directory)
        root.chmod(0o710)
        service = ScanService(str(root / "scan.sock"), os.getuid(), concurrency=1)
        service.open()
        def fail_start(_):
            raise RuntimeError("synthetic thread exhaustion")
        monkeypatch.setattr(threading.Thread, "start", fail_start)
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(1)
            connection.connect(str(service.path))
            with pytest.raises(RuntimeError, match="synthetic thread exhaustion"):
                service.serve()
            assert connection.recv(1) == b""
        assert not service.path.exists() and not service.threads
        assert service.slots.acquire(blocking=False)


def test_shutdown_preserves_replaced_endpoint():
    with tempfile.TemporaryDirectory(prefix="siq-scan-replace-") as directory:
        root = Path(directory)
        root.chmod(0o710)
        service = ScanService(str(root / "scan.sock"), os.getuid())
        service.open()
        service.path.unlink()
        service.path.write_text("operator replacement")
        service.stopping.set()
        service.serve()
        assert service.path.read_text() == "operator replacement"


@pytest.mark.parametrize("path,uid", [("relative.sock", "10001"), ("/run/x/../s", "10001"),
    ("/run/scan.sock", "0"), ("/run/scan.sock", "-1"), ("/run/scan.sock", "NaN"),
    ("/run/scan.sock", str(os.getuid())), ("/run/scan.sock", "4294967295")])
def test_service_configuration_is_explicit_and_fail_closed(monkeypatch, path, uid):
    monkeypatch.setenv("SIQ_AS_THREAT_SCAN_ISOLATION", "bwrap-service")
    monkeypatch.setenv("SIQ_AS_THREAT_SCAN_SOCKET", path)
    monkeypatch.setenv("SIQ_AS_THREAT_SCAN_SERVICE_UID", uid)
    with pytest.raises(RuntimeError):
        load_settings()


def test_service_settings_and_legacy_defaults(monkeypatch):
    monkeypatch.delenv("SIQ_AS_THREAT_SCAN_ISOLATION", raising=False)
    assert load_settings().threat_scan_isolation == "process"
    monkeypatch.setenv("SIQ_AS_THREAT_SCAN_ISOLATION", "bwrap")
    assert load_settings().threat_scan_isolation == "bwrap"
    monkeypatch.setenv("SIQ_AS_THREAT_SCAN_ISOLATION", "bwrap-service")
    monkeypatch.setenv("SIQ_AS_THREAT_SCAN_SOCKET", "/run/scan/socket")
    monkeypatch.setenv("SIQ_AS_THREAT_SCAN_SERVICE_UID", str(os.getuid() + 1))
    result = load_settings()
    assert result.threat_scan_socket == "/run/scan/socket"
    assert result.threat_scan_service_uid == os.getuid() + 1


def test_misbound_service_result_cannot_commit_success(client, tenant_a, env_a, service_factory, monkeypatch):
    def worker(argv, payload, **kwargs):
        response = json.loads(payload)
        for key in ("rules", "filename", "content_base64"):
            response.pop(key)
        response["scope_sha256"] = "0" * 64
        response["result"] = {"sha256": response["input_sha256"], "detected_type": "shell", "matches": []}
        return json.dumps(response).encode()
    monkeypatch.setattr(scan_service, "exchange", worker)
    service = service_factory()
    monkeypatch.setattr(scan_execution, "load_settings", lambda: SimpleNamespace(
        threat_scan_isolation="bwrap-service", threat_scan_socket=str(service.path),
        threat_scan_service_uid=os.getuid()))
    asset_id, _ = make_instance(tenant_a['X-Dev-Tenant-Id'], env_a['id'])
    def counts():
        with session_scope() as session:
            return tuple(session.scalar(select(func.count()).select_from(model))
                         for model in (Finding, AuditEvent, OutboxEvent))
    before = counts()
    response = client.post(f"/api/v1/assets/{asset_id}/threat-scan", headers=tenant_a,
                           json={"content": "echo synthetic", "filename": "x.sh"})
    assert response.status_code == 503 and response.json()["detail"] == "threat_scan_result_invalid"
    assert counts() == before
    with session_scope() as session:
        assert session.get(AgentAsset, asset_id).artifact_digest is None
    assert client.get('/health').status_code == 200
