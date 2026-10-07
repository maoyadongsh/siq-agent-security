"""Synthetic Docker transport cases; real daemon acceptance is a separate tool."""

import base64
import hashlib
import io
import json
import os
import socket
import sys
import tarfile
from contextlib import closing
from dataclasses import replace

import pytest

from app.adapters.openshell import behavior_protection as module
from app.adapters.openshell.contracts import AdapterError


@pytest.fixture
def target():
    return module.ProtectedProbeTarget(container_id="a" * 64, image_digest="sha256:" + "b" * 64,
        namespace="synthetic", sandbox_name="sandbox", sandbox_id="sandbox-id", uid=1000,
        allow_path="/opt/probe/allow", deny_path="/opt/probe/deny", probe_sha256="c" * 64)


def values(target):
    return [target.container_id, target.image_digest, True, 12345, False, "", "synthetic-network", "", None, [],
            target.namespace, target.sandbox_name, target.sandbox_id, "1000:1000"]


def inspected(monkeypatch, target, rows=None):
    rows = rows or values(target)
    monkeypatch.setattr(module, "run_bounded", lambda *args, **kwargs: (0, "\n".join(map(json.dumps, rows)), ""))
    return module.RootfulDockerProbeGuard(target)


def test_fixed_daemon_projection_omits_credentials_and_host_mount_sources(monkeypatch, target):
    calls = []
    rows = values(target)
    rows[9] = [{"Destination": "/sandbox", "Source": "/private/synthetic-path", "RW": True}]

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return 0, "\n".join(map(json.dumps, rows)), ""

    monkeypatch.setattr(module, "run_bounded", runner)
    observed = module.RootfulDockerProbeGuard(target)._inspect()
    assert "private" not in json.dumps(observed)
    assert calls[0][0][:6] == ["/usr/bin/docker", "--host", "unix:///run/docker.sock", "inspect", "--type", "container"]
    assert calls[0][1]["environment"] == {"PATH": "/usr/bin:/bin", "LANG": "C"}
    assert calls[0][1]["limit"] == 65536


@pytest.mark.parametrize("index,value", [(0, "d" * 64), (1, "sha256:" + "d" * 64), (2, False), (2, 1),
    (3, True), (3, 0), (4, True), (5, "host"), (6, "host"), (6, "container:another"), (7, "host"),
    (8, ["SYS_ADMIN"]), (10, "other"), (11, "other"), (12, "other"),
    (9, [{"Destination": "/opt", "RW": False}]), (9, [{"Destination": "/opt/probe/allow", "RW": True}]),
    (9, [{"Destination": "/opt/../opt"}])])
def test_wrong_or_dangerous_container_never_becomes_protected(monkeypatch, target, index, value):
    rows = values(target)
    rows[index] = value
    with pytest.raises(AdapterError, match="behavior_program_protection_unverified"):
        inspected(monkeypatch, target, rows)._inspect()


@pytest.mark.parametrize("field,value", [("container_id", "../other"), ("image_digest", None), ("uid", True),
    ("uid", 0), ("allow_path", "/"), ("allow_path", "/opt/../probe"), ("allow_path", "/opt/probe/deny"),
    ("allow_path", "/a" * 17), ("namespace", "*")])
def test_unbounded_or_noncanonical_operator_target_rejected(target, field, value):
    with pytest.raises(AdapterError, match="behavior_program_protection_unverified"):
        replace(target, **{field: value})


def archive_transport(monkeypatch, *, uid=0, mode=0o555, kind=tarfile.REGTYPE, link="", pax=None,
                      payload=b"\x7fELFsynthetic", name="allow", header_override=None):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as archive:
        member = tarfile.TarInfo(name)
        member.type, member.uid, member.gid, member.mode, member.linkname = kind, uid, 0, mode, link
        member.pax_headers = pax or {}
        member.size = len(payload) if kind == tarfile.REGTYPE else 0
        archive.addfile(member, io.BytesIO(payload))
    header = {"name": name, "size": len(payload), "mode": mode, "linkTarget": link}
    header.update(header_override or {})

    class Response(io.BytesIO):
        status = 200

        def getheader(self, *_):
            return base64.b64encode(json.dumps(header).encode()).decode()

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, method, path):
            assert method == "GET" and path.endswith("path=%2Fopt%2Fprobe%2Fallow")

        def getresponse(self):
            return Response(raw.getvalue())

        def close(self):
            pass

    monkeypatch.setattr(module, "_UnixConnection", Connection)


def test_archive_hashes_bytes_without_extracting_or_executing(monkeypatch):
    archive_transport(monkeypatch)
    result = module._archive("a" * 64, "/opt/probe/allow", program=True)
    assert result == {"path": "/opt/probe/allow", "uid": 0, "gid": 0, "mode": 0o555, "kind": "file",
                      "size": 13, "sha256": hashlib.sha256(b"\x7fELFsynthetic").hexdigest()}


@pytest.mark.parametrize("changes", [{"uid": 1000}, {"mode": 0o777}, {"mode": 0o4755},
    {"kind": tarfile.SYMTYPE, "link": "/another"}, {"kind": tarfile.LNKTYPE, "link": "another"},
    {"kind": tarfile.FIFOTYPE}, {"name": "../allow"}, {"payload": b"#!/bin/sh\necho fake"},
    {"pax": {"SCHILY.acl.access": "user:1000:rw-"}}, {"pax": {"SCHILY.xattr.security.capability": "synthetic"}},
    {"header_override": {"mode": 0o777}}, {"header_override": {"linkTarget": "/another"}}])
def test_archive_cannot_hide_unsafe_file_or_link(monkeypatch, changes):
    archive_transport(monkeypatch, **changes)
    with pytest.raises(AdapterError, match="behavior_program_protection_unverified"):
        module._archive("a" * 64, "/opt/probe/allow", program=True)


def test_archive_stream_has_hard_read_limit():
    limited = module._LimitedReader(io.BytesIO(b"a" * 100), 10)
    assert limited.read(10) == b"a" * 10
    with pytest.raises(AdapterError):
        limited.read(1)


def test_protection_fact_stable_and_drift_invalidates(monkeypatch, target):
    guard = inspected(monkeypatch, target)
    monkeypatch.setattr(module, "_trusted", lambda *args, **kwargs: (1, 2, 3))

    def archive(container, path, *, program):
        assert container == target.container_id
        value = {"path": path, "uid": 0, "gid": 0, "mode": 0o555, "kind": "file" if program else "directory"}
        if program:
            value.update(sha256=target.probe_sha256, size=100)
        return value

    monkeypatch.setattr(module, "_archive", archive)
    initial = guard.verify()
    assert initial == guard.verify()
    assert len(initial["facts"]["objects"]) == 5
    rows = values(target)
    calls = []

    def drifting(*args, **kwargs):
        calls.append(1)
        copy = rows[:]
        if len(calls) == 2:
            copy[3] += 1
        return 0, "\n".join(map(json.dumps, copy)), ""

    monkeypatch.setattr(module, "run_bounded", drifting)
    with pytest.raises(AdapterError):
        guard.verify()


def test_backend_error_text_is_not_exposed(monkeypatch, target):
    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic-private-daemon-path")

    monkeypatch.setattr(module, "_trusted", unavailable)
    with pytest.raises(AdapterError) as error:
        module.RootfulDockerProbeGuard(target).verify()
    assert str(error.value) == "behavior_program_protection_unverified"


def test_openshell_supervisor_profile_is_exact_and_explicit(monkeypatch, target):
    rows = values(target)
    rows[8], rows[13] = ["SYS_ADMIN", "NET_ADMIN", "SYS_PTRACE", "SYSLOG"], "0"
    with pytest.raises(AdapterError):
        inspected(monkeypatch, target, rows)._inspect()
    approved = replace(target, supervisor_profile="openshell-rootful-v0")
    assert inspected(monkeypatch, approved, rows)._inspect()["supervisor_profile"] == "openshell-rootful-v0"
    rows[8].append("DAC_OVERRIDE")
    with pytest.raises(AdapterError):
        inspected(monkeypatch, approved, rows)._inspect()


@pytest.mark.skipif(sys.platform != "linux" or os.getuid() == 0,
                    reason="non-root Unix peer negative requires non-root Linux test user")
def test_actual_nonroot_unix_peer_is_not_a_rootful_daemon(monkeypatch, tmp_path):
    path = tmp_path / "daemon.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        listener.listen(1)
        monkeypatch.setattr(module, "_SOCKET", path)
        with closing(module._UnixConnection("localhost")) as connection:
            with pytest.raises(AdapterError, match="behavior_program_protection_unverified"):
                connection.connect()
