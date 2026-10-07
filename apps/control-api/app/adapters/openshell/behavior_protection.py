"""Read-only, independently observed image/file protection for local Docker.

Operator-approved IDs are required. No arbitrary daemon URL, container command,
image build, upload or filesystem extraction is available through this helper.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import re
import socket
import stat
import struct
import tarfile
import time
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from app.adapters.openshell.bounded_command import run_bounded
from app.adapters.openshell.contracts import AdapterError

_DOCKER = Path("/usr/bin/docker")
_SOCKET = Path("/run/docker.sock")
_FIELDS = (".Id", ".Image", ".State.Running", ".State.Pid", ".HostConfig.Privileged",
           ".HostConfig.PidMode", ".HostConfig.NetworkMode", ".HostConfig.UsernsMode",
           ".HostConfig.CapAdd", ".Mounts",
           'index .Config.Labels "openshell.ai/sandbox-namespace"',
           'index .Config.Labels "openshell.ai/sandbox-name"',
           'index .Config.Labels "openshell.ai/sandbox-id"', ".Config.User")
_FORMAT = "\n".join("{{json (" + field + ")}}" for field in _FIELDS)
_MAX_PROGRAM = 64 << 20


def _fail():
    return AdapterError("behavior_program_protection_unverified")


def _trusted(path, *, is_socket=False):
    target = None
    for current in (path, *path.parents):
        info = current.lstat()
        if info.st_uid != 0 or stat.S_ISLNK(info.st_mode):
            raise _fail()
        if current == path:
            if is_socket:
                if not stat.S_ISSOCK(info.st_mode) or info.st_mode & 0o002:
                    raise _fail()
            elif not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or not info.st_mode & 0o111:
                raise _fail()
            target = (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)
        elif not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
            raise _fail()
    return target


class _UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(2)
        self.sock.connect(str(_SOCKET))
        pid, uid, _ = struct.unpack("3i", self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if pid <= 0 or uid != 0:
            raise _fail()


class _LimitedReader:
    def __init__(self, source, limit):
        self.source, self.limit, self.used = source, limit, 0
        self.deadline = time.monotonic() + 5

    def read(self, size):
        if time.monotonic() >= self.deadline or size < 0 or self.used + size > self.limit:
            raise _fail()
        chunk = self.source.read(size)
        self.used += len(chunk)
        return chunk


def _archive(container_id, path, *, program):
    """Inspect only the first tar member; no extraction or container execution."""
    with closing(_UnixConnection("localhost", timeout=2)) as connection:
        connection.request("GET", f"/v1.45/containers/{container_id}/archive?path={quote(path, safe='')}")
        response = connection.getresponse()
        header = response.getheader("X-Docker-Container-Path-Stat", "")
        if response.status != 200 or len(header) > 4096:
            raise _fail()
        metadata = json.loads(base64.b64decode(header, validate=True))
        if not isinstance(metadata, dict) or metadata.get("linkTarget") != "":
            raise _fail()
        reader = _LimitedReader(response, _MAX_PROGRAM + 65536 if program else 65536)
        with tarfile.open(fileobj=reader, mode="r|", bufsize=512) as archive:
            member = archive.next()
            expected_name = PurePosixPath(path).name
            if (member is None or member.name != expected_name or member.uid != 0 or member.mode & 0o6022
                or any("acl" in key.lower() or "capability" in key.lower() for key in member.pax_headers)
                or (not member.isreg() if program else not member.isdir())):
                raise _fail()
            if type(metadata.get("mode")) is not int or metadata["mode"] & 0o7777 != member.mode:
                raise _fail()
            value = {"path": path, "uid": member.uid, "gid": member.gid, "mode": member.mode,
                     "kind": "file" if program else "directory"}
            if program:
                if not member.mode & 0o111 or not 4 <= member.size <= _MAX_PROGRAM:
                    raise _fail()
                stream = archive.extractfile(member)  # A bounded stream; does not write to the filesystem.
                digest = hashlib.sha256()
                header = stream.read(4)
                if header != b"\x7fELF":
                    raise _fail()
                digest.update(header)
                count = 4
                while chunk := stream.read(65536):
                    count += len(chunk)
                    if count > _MAX_PROGRAM:
                        raise _fail()
                    digest.update(chunk)
                if count != member.size:
                    raise _fail()
                value.update(size=count, sha256=digest.hexdigest())
            return value


@dataclass(frozen=True)
class ProtectedProbeTarget:
    container_id: str
    image_digest: str
    namespace: str
    sandbox_name: str
    sandbox_id: str
    uid: int
    allow_path: str
    deny_path: str
    probe_sha256: str
    supervisor_profile: str = "unprivileged-container"

    def __post_init__(self):
        if (any(not isinstance(value, str) for key, value in asdict(self).items() if key != "uid")
            or not re.fullmatch(r"[a-f0-9]{64}", self.container_id)
            or not re.fullmatch(r"sha256:[a-f0-9]{64}", self.image_digest)
            or not re.fullmatch(r"[a-f0-9]{64}", self.probe_sha256)
            or type(self.uid) is not int or not 1 <= self.uid <= 4294967294
            or any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", v)
                   for v in (self.namespace, self.sandbox_name, self.sandbox_id))
            or self.allow_path == self.deny_path
            or self.supervisor_profile not in ("unprivileged-container", "openshell-rootful-v0")):
            raise _fail()
        for path in (self.allow_path, self.deny_path):
            if (len(path) > 512 or not re.fullmatch(r"/[A-Za-z0-9_./-]+", path)
                or str(PurePosixPath(path)) != path or ".." in PurePosixPath(path).parts or path == "/"
                or len(PurePosixPath(path).parts) > 16):
                raise _fail()


class RootfulDockerProbeGuard:
    def __init__(self, expected: ProtectedProbeTarget):
        if not isinstance(expected, ProtectedProbeTarget):
            raise _fail()
        self.expected = expected

    def _inspect(self):
        code, stdout, _ = run_bounded(
            [str(_DOCKER), "--host", "unix:///run/docker.sock", "inspect", "--type", "container", "--format",
             _FORMAT, self.expected.container_id], timeout=3, limit=65536,
            environment={"PATH": "/usr/bin:/bin", "LANG": "C"},
        )
        if code:
            raise _fail()
        values = [json.loads(line) for line in stdout.splitlines()]
        if (len(values) != len(_FIELDS) or values[:2] != [self.expected.container_id, self.expected.image_digest]
            or values[2] is not True
            or type(values[3]) is not int or not 0 < values[3] <= 2147483647 or values[4] is not False
            or values[5] != "" or not isinstance(values[6], str) or values[6] in ("", "host")
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", values[6])
            or values[6].startswith("container:") or values[7] != ""
            or values[10:13] != [self.expected.namespace, self.expected.sandbox_name, self.expected.sandbox_id]
            or not isinstance(values[9], list) or len(values[9]) > 256):
            raise _fail()
        if self.expected.supervisor_profile == "unprivileged-container":
            users = (str(self.expected.uid), f"{self.expected.uid}:{self.expected.uid}")
            if values[8] not in (None, []) or values[13] not in users:
                raise _fail()
        elif (not isinstance(values[8], list) or len(values[8]) != 4
              or any(not isinstance(cap, str) for cap in values[8])
              or set(values[8]) != {"SYS_ADMIN", "NET_ADMIN", "SYS_PTRACE", "SYSLOG"} or values[13] != "0"):
            raise _fail()
        destinations = []
        for mount in values[9]:
            if not isinstance(mount, dict) or not isinstance(mount.get("Destination"), str):
                raise _fail()
            destination = PurePosixPath(mount["Destination"])
            if (not destination.is_absolute() or str(destination) != mount["Destination"]
                or ".." in destination.parts):
                raise _fail()
            if any(PurePosixPath(path).is_relative_to(destination)
                   for path in (self.expected.allow_path, self.expected.deny_path)):
                raise _fail()
            if str(destination) in destinations or len(str(destination)) > 512:
                raise _fail()
            destinations.append(str(destination))
        return {"container_id": values[0], "image_digest": values[1], "init_pid": values[3],
                "network": values[6], "mount_destinations": sorted(destinations),
                "namespace": values[10], "sandbox_name": values[11], "sandbox_id": values[12],
                "supervisor_profile": self.expected.supervisor_profile}

    def verify(self) -> dict:
        try:
            deadline = time.monotonic() + 10
            authority = (_trusted(_DOCKER), _trusted(_SOCKET, is_socket=True))
            before = self._inspect()
            paths = (self.expected.allow_path, self.expected.deny_path)
            parents = sorted({str(parent) for path in paths for parent in PurePosixPath(path).parents},
                             key=lambda p: (len(PurePosixPath(p).parts), p))
            observed = []
            for path in parents:
                if time.monotonic() >= deadline:
                    raise _fail()
                observed.append(_archive(self.expected.container_id, path, program=False))
            for path in paths:
                if time.monotonic() >= deadline:
                    raise _fail()
                value = _archive(self.expected.container_id, path, program=True)
                if value["sha256"] != self.expected.probe_sha256:
                    raise _fail()
                observed.append(value)
            if (before != self._inspect() or time.monotonic() >= deadline
                or authority != (_trusted(_DOCKER), _trusted(_SOCKET, is_socket=True))):
                raise _fail()
            facts = {"schema_version": "openshell-behavior-protection/v1", "approved": asdict(self.expected),
                     "container": before, "objects": observed}
            digest = hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            return {"protected_execution_sha256": digest, "facts": facts}
        except Exception:  # noqa: BLE001 - daemon errors and paths never cross the control API boundary.
            raise _fail() from None
