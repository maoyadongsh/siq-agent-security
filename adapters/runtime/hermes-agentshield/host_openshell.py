"""Read-only rootful Docker ownership checks for the trusted host launcher."""

import json
import os
import re
import stat
import subprocess
import tempfile
import threading
from pathlib import Path

from .host_runtime import RuntimeGuardError, _bounded, _stamp

_DOCKER = Path("/usr/bin/docker")
_SOCKET = Path("/run/docker.sock")
_FIELDS = (".Id", ".Image", ".State.Pid", ".State.Running", ".HostConfig.Privileged",
           '.HostConfig.PidMode', '.HostConfig.NetworkMode',
           'index .Config.Labels "openshell.ai/sandbox-namespace"',
           'index .Config.Labels "openshell.ai/sandbox-name"',
           'index .Config.Labels "openshell.ai/sandbox-id"')
_FORMAT = "\n".join("{{json (" + value + ")}}" for value in _FIELDS)


def _failure():
    return RuntimeGuardError("native_openshell_backend_unverified")


def _trusted(path, *, socket=False):
    current, target = path, None
    while True:
        info = current.lstat()
        if info.st_uid != 0 or stat.S_ISLNK(info.st_mode):
            raise _failure()
        if current == path:
            if socket:
                if not stat.S_ISSOCK(info.st_mode) or info.st_mode & 0o002:
                    raise _failure()
            elif not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or not info.st_mode & 0o111:
                raise _failure()
            target = _stamp(info)
        elif not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
            raise _failure()
        if current == current.parent:
            return target
        current = current.parent


def _capture(arguments, limit):
    # A fixed projection avoids collecting container environment or contents.
    # File-backed capture bounds memory even for a malformed daemon response.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            [str(_DOCKER), "--host", "unix:///run/docker.sock", *arguments],
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
            cwd="/", env={"PATH": "/usr/bin:/bin", "LANG": "C"}, timeout=2, check=False,
        )
        output.seek(0)
        raw = output.read(limit + 1)
    if result.returncode or len(raw) > limit:
        raise _failure()
    return raw


def _inspect(container_id):
    raw = _capture(["inspect", "--type", "container", "--format", _FORMAT, container_id], 8192)
    values = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
    if len(values) != len(_FIELDS):
        raise _failure()
    return values


def _members(container_id):
    lines = _capture(["top", container_id, "-eo", "pid"], 65536).decode("ascii").splitlines()
    if not lines or lines[0].strip() != "PID" or len(lines) > 4097:
        raise _failure()
    result = set()
    for line in lines[1:]:
        if not re.fullmatch(r"[ \t]*[1-9][0-9]{0,9}[ \t]*", line):
            raise _failure()
        pid = int(line)
        if pid > 2147483647 or pid in result:
            raise _failure()
        result.add(pid)
    return result


def _pid_chain(pid):
    rows = [line.split()[1:] for line in _bounded(f"/proc/{pid}/status", 65536).decode("ascii").splitlines()
            if line.startswith("NSpid:")]
    if len(rows) != 1 or len(rows[0]) < 2 or any(not re.fullmatch(r"[1-9][0-9]{0,9}", v) for v in rows[0]):
        raise _failure()
    values = [int(v) for v in rows[0]]
    if values[0] != pid or any(v > 2147483647 for v in values):
        raise _failure()
    return values


def _namespace(pid):
    info = os.stat(f"/proc/{pid}/ns/pid")
    return info.st_dev, info.st_ino


class OpenShellBackend:
    """Fixed launch ownership; every failure permanently invalidates this handle."""

    def __init__(self, *, container_id, image_id, namespace, sandbox, pid, init_pid,
                 uid, gid, artifact_sha256, cgroup):
        self._owner = os.getpid()
        self._failed, self._lock, self._sandbox_id = False, threading.Lock(), None
        try:
            if (type(container_id) is not str or not re.fullmatch(r"[a-f0-9]{64}", container_id)
                    or type(image_id) is not str or not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id)
                    or type(artifact_sha256) is not str or not re.fullmatch(r"[a-f0-9]{64}", artifact_sha256)
                    or any(type(v) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", v)
                           for v in (namespace, sandbox))
                    or any(type(v) is not int or not 0 < v <= 2147483647 for v in (pid, init_pid, uid, gid))
                    or type(cgroup) is not str or not 0 < len(cgroup.encode()) <= 65536 or "\x00" in cgroup):
                raise _failure()
            self._container, self._image = container_id, image_id
            self._namespace, self._sandbox = namespace, sandbox
            self._pid, self._init, self._uid, self._gid = pid, init_pid, uid, gid
            self._artifact, self._cgroup = artifact_sha256, cgroup.encode()
            self._docker_stamp = _trusted(_DOCKER)
            self._socket_stamp = _trusted(_SOCKET, socket=True)
            self(pid, uid, gid, artifact_sha256)
        except Exception:  # noqa: BLE001 - no daemon or process details cross the host boundary.
            self._failed = True
            raise _failure() from None

    def __call__(self, pid, uid, gid, artifact):
        if os.getpid() != self._owner or self._failed:
            raise _failure()
        if not self._lock.acquire(timeout=2):
            self._failed = True
            raise _failure()
        try:
            if (self._failed or (pid, uid, gid, artifact) != (self._pid, self._uid, self._gid, self._artifact)
                    or any(type(v) is not int for v in (pid, uid, gid))):
                raise _failure()
            before = (_trusted(_DOCKER), _trusted(_SOCKET, socket=True))
            if before != (self._docker_stamp, self._socket_stamp):
                raise _failure()
            actual = _inspect(self._container)
            if (actual[:2] != [self._container, self._image]
                    or type(actual[2]) is not int or actual[2] != self._init
                    or actual[3] is not True or actual[4] is not False
                    or actual[5] != "" or type(actual[6]) is not str or actual[6] in ("", "host")
                    or actual[6].startswith("container:")
                    or actual[7:9] != [self._namespace, self._sandbox]
                    or type(actual[9]) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", actual[9])
                    or (self._sandbox_id is not None and actual[9] != self._sandbox_id)):
                raise _failure()
            members = _members(self._container)
            init_chain, peer_chain = _pid_chain(self._init), _pid_chain(pid)
            if (pid not in members or self._init not in members
                    or len(init_chain) != len(peer_chain) or init_chain[-1] != 1
                    or _bounded(f"/proc/{pid}/cgroup", 65536) != self._cgroup
                    or _bounded(f"/proc/{self._init}/cgroup", 65536) != self._cgroup
                    or _namespace(pid) == _namespace(os.getpid())
                    or before != (_trusted(_DOCKER), _trusted(_SOCKET, socket=True))
                    or self._failed):
                raise _failure()
            self._sandbox_id = actual[9]
        except Exception:  # noqa: BLE001 - errors invalidate this handle without exposing input.
            self._failed = True
            raise _failure() from None
        finally:
            self._lock.release()
