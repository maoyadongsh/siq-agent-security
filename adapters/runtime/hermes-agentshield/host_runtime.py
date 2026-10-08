"""Trusted Linux launcher checks (ADR-056), never a model-facing authorizer.

The mandatory backend verifier owns sandbox/image attestation. This component
checks its actual process and file view; it never creates or changes a mount.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import stat
import threading
import time
from pathlib import Path

from .native_channel import ProcessPin

_MAX_FILES = 128
_MAX_CODE_BYTES = 16 << 20
_HASH = re.compile(r"[a-f0-9]{64}")


class RuntimeGuardError(RuntimeError):
    """Only a fixed failure category crosses the launcher boundary."""


def _failure():
    return RuntimeGuardError("native_runtime_unverified")


def _path(value):
    if (type(value) is not str or not value.startswith("/") or value == "/"
            or len(value.encode("utf-8")) > 4096 or "\\" in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(p in ("", ".", "..") for p in value.split("/")[1:])):
        raise _failure()
    return value


def _hash(value):
    if type(value) is not str or not _HASH.fullmatch(value):
        raise _failure()
    return value


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
            info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _host_info(value):
    path = Path(value)
    while True:
        info = path.lstat()
        sticky_root_tmp = info.st_uid == 0 and stat.S_ISDIR(info.st_mode) and info.st_mode & stat.S_ISVTX
        if (stat.S_ISLNK(info.st_mode) or info.st_uid not in (0, os.getuid())
                or (info.st_mode & 0o022 and not sticky_root_tmp)):
            raise _failure()
        if path == Path(value):
            target = info
        if path == path.parent:
            return target
        path = path.parent


def _bounded(path, limit):
    with open(path, "rb") as file:
        value = file.read(limit + 1)
    if len(value) > limit:
        raise _failure()
    return value


def _mounts(raw):
    result = {}
    for line in raw.decode("utf-8", errors="strict").splitlines():
        fields, separator, filesystem = line.partition(" - ")
        parts = fields.split()
        if not separator or len(parts) < 6 or len(filesystem.split()) < 3:
            raise _failure()
        target = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), parts[4])
        if target in result:
            raise _failure()
        result[target] = frozenset(parts[5].split(","))
    return result


class RuntimeGuard:
    """Pinned host facts; backend checks must be bounded and non-reentrant.

    `mounts` contains exact {source, target, kind} dictionaries; code_files maps
    actual runtime paths to hashes. The launcher supplies these, never a tool.
    No positive result or prior hash is cached between execution boundaries.
    """

    def __init__(self, *, pid, uid, gid, artifact_sha256, executable_sha256,
                 argv_sha256, mounts, code_files, verify_backend,
                 image_files=None, image_skill_roots=None):
        self._pin, self._closed = None, False
        self._lock = threading.RLock()
        self._failed = threading.Event()
        self._image_mode = image_files is not None
        self._image_objects, self._image_skills = {}, []
        self._channel_directory = None
        try:
            if (type(uid) is not int or uid <= 0 or type(gid) is not int or gid <= 0
                    or not callable(verify_backend) or type(mounts) is not list
                    or type(code_files) is not dict):
                raise _failure()
            if self._image_mode:
                if (mounts or code_files or type(image_files) is not dict
                        or not 1 <= len(image_files) <= _MAX_FILES
                        or type(image_skill_roots) is not list or len(image_skill_roots) > 64):
                    raise _failure()
                for mapping in image_skill_roots:
                    if type(mapping) is not dict or set(mapping) != {"source", "target"}:
                        raise _failure()
                    entry = {"source": _path(mapping["source"]), "target": _path(mapping["target"])}
                    for old in self._image_skills:
                        if (entry["source"] == old["source"] or entry["target"] == old["target"]
                                or entry["target"].startswith(old["target"] + "/")
                                or old["target"].startswith(entry["target"] + "/")):
                            raise _failure()
                    self._image_skills.append(entry)
            elif (image_skill_roots is not None or not 1 <= len(mounts) <= 64
                    or not 1 <= len(code_files) <= _MAX_FILES):
                raise _failure()
            self.pid, self.uid, self.gid = pid, uid, gid
            self.artifact = _hash(artifact_sha256)
            self._executable, self._argv = _hash(executable_sha256), _hash(argv_sha256)
            self._backend = verify_backend
            self._mounts = []
            for mount in mounts:
                if (type(mount) is not dict or set(mount) != {"source", "target", "kind"}
                        or mount["kind"] not in ("code", "skill", "channel")):
                    raise _failure()
                entry = {"source": _path(mount["source"]), "target": _path(mount["target"]), "kind": mount["kind"]}
                for old in self._mounts:
                    if (entry["target"] == old["target"] or entry["target"].startswith(old["target"] + "/")
                            or old["target"].startswith(entry["target"] + "/")):
                        raise _failure()
                self._mounts.append(entry)
            self._files = {_path(k): _hash(v) for k, v in (image_files if self._image_mode else code_files).items()}
            if not self._image_mode and any(self._owner(path)["kind"] != "code" for path in self._files):
                raise _failure()
            self._pin = ProcessPin(pid, uid)
            self._namespaces = self._namespace_ids()
            self.verify()
        except BaseException:  # noqa: BLE001 - no raw process/configuration details cross this boundary
            self.close()
            raise _failure() from None

    def _owner(self, target):
        owners = [m for m in self._mounts if target == m["target"] or target.startswith(m["target"] + "/")]
        if len(owners) != 1:
            raise _failure()
        return owners[0]

    def _namespace_ids(self):
        return tuple((info.st_dev, info.st_ino) for info in (
            os.stat(f"/proc/{self.pid}/ns/{kind}") for kind in ("mnt", "pid", "user", "net")))

    @property
    def peer(self):
        self.verify()
        return self._pin

    def _check_process(self):
        self._pin.check()
        fields = {}
        for line in _bounded(f"/proc/{self.pid}/status", 65536).decode("ascii").splitlines():
            key, _, value = line.partition(":")
            fields[key] = value.split()
        if (fields.get("Uid") != [str(self.uid)] * 4 or fields.get("Gid") != [str(self.gid)] * 4
                or fields.get("NoNewPrivs") != ["1"]
                or any(int(fields[key][0], 16) != 0 for key in ("CapEff", "CapPrm", "CapAmb"))
                or not set(fields.get("Groups", ())).issubset({str(self.gid)})
                or self._namespace_ids() != self._namespaces
                or hashlib.sha256(_bounded(f"/proc/{self.pid}/cmdline", 65536)).hexdigest() != self._argv):
            raise _failure()
        with open(f"/proc/{self.pid}/exe", "rb") as file:
            if self._digest_fd(file.fileno(), 128 << 20)[0] != self._executable:
                raise _failure()

    @staticmethod
    def _digest_fd(fd, limit):
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 <= before.st_size <= limit:
            raise _failure()
        digest, total = hashlib.sha256(), 0
        while True:
            chunk = os.read(fd, min(65536, limit + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise _failure()
            digest.update(chunk)
        if total != before.st_size or _stamp(os.fstat(fd)) != _stamp(before):
            raise _failure()
        return digest.hexdigest(), total

    @contextlib.contextmanager
    def _runtime_file(self, root, path, *, protected=False):
        descriptors, edges = [], []
        parent = root
        try:
            if protected:
                self._protected_object("/", os.fstat(root))
            parts = path.split("/")[1:]
            for index, name in enumerate(parts):
                flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
                if index < len(parts) - 1:
                    flags |= os.O_DIRECTORY
                fd = os.open(name, flags, dir_fd=parent)
                descriptors.append(fd)
                info = os.fstat(fd)
                if protected:
                    self._protected_object("/" + "/".join(parts[:index + 1]), info)
                edges.append((parent, name, fd, (info.st_dev, info.st_ino)))
                parent = fd
            yield parent
            for index, (parent, name, fd, expected) in enumerate(edges):
                current = os.stat(name, dir_fd=parent, follow_symlinks=False)
                opened = os.fstat(fd)
                if (stat.S_ISLNK(current.st_mode) or (current.st_dev, current.st_ino) != expected
                        or (opened.st_dev, opened.st_ino) != expected):
                    raise _failure()
                if protected:
                    key = "/" + "/".join(parts[:index + 1])
                    self._protected_object(key, opened)
                    self._protected_object(key, current)
        finally:
            for fd in reversed(descriptors):
                os.close(fd)

    def _protected_object(self, path, info):
        if (info.st_uid != 0 or info.st_mode & 0o022
                or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode))):
            raise _failure()
        identity = (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)
        if self._image_objects.setdefault(path, identity) != identity:
            raise _failure()

    def _check_image_skills(self, root):
        for mapping in self._image_skills:
            target = mapping["target"]
            expected = {path for path in self._files if path.startswith(target + "/")}
            if not expected:
                raise _failure()
            found, pending, entries = set(), [target], 0
            while pending:
                directory = pending.pop()
                with self._runtime_file(root, directory, protected=True) as fd:
                    if not stat.S_ISDIR(os.fstat(fd).st_mode):
                        raise _failure()
                    # scandir streams entries instead of allocating an unbounded list.
                    with os.scandir(fd) as children:
                        for child in children:
                            entries += 1
                            if entries > _MAX_FILES * 2:
                                raise _failure()
                            path = directory + "/" + child.name
                            info = child.stat(follow_symlinks=False)
                            self._protected_object(path, info)
                            if stat.S_ISDIR(info.st_mode):
                                if not any(p.startswith(path + "/") for p in expected):
                                    raise _failure()
                                pending.append(path)
                            elif path in expected:
                                found.add(path)
                            else:
                                raise _failure()
            if found != expected:
                raise _failure()

    def _check_channel_directory(self, root):
        if self._channel_directory is None:
            return
        path, identity = self._channel_directory
        with self._runtime_file(root, path) as fd:
            info = os.fstat(fd)
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != self.uid or info.st_gid != self.gid
                    or stat.S_IMODE(info.st_mode) != 0o700 or (info.st_dev, info.st_ino) != identity):
                raise _failure()

    @contextlib.contextmanager
    def namespace_channel_directory(self, runtime_path):
        """Yield a verified runtime fd; only for a host outside its PID namespace."""
        root, duplicate = None, None
        try:
            with self._lock:
                _path(runtime_path)
                host_pid_ns = os.stat("/proc/self/ns/pid")
                if (not self._image_mode or (os.geteuid(), os.getegid()) != (self.uid, self.gid)
                        or self._namespaces[1] == (host_pid_ns.st_dev, host_pid_ns.st_ino)):
                    raise _failure()
                self.verify()
                root = os.open(f"/proc/{self.pid}/root", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
                with self._runtime_file(root, runtime_path) as fd:
                    info = os.fstat(fd)
                    entry = (runtime_path, (info.st_dev, info.st_ino))
                    if self._channel_directory not in (None, entry):
                        raise _failure()
                    self._channel_directory = entry
                    self._check_channel_directory(root)
                    self.verify()
                    duplicate = os.dup(fd)
                    os.set_inheritable(duplicate, False)
            # Publisher verification may run on another thread while the
            # launcher holds this context; do not hold the guard lock here.
            yield duplicate
            self.verify()
        except BaseException:  # noqa: BLE001 - invalid bootstrap state closes the guarded process
            self.close()
            raise _failure() from None
        finally:
            if duplicate is not None:
                os.close(duplicate)
            if root is not None:
                os.close(root)

    def _check_mounts(self, root):
        actual = _mounts(_bounded(f"/proc/{self.pid}/mountinfo", 1 << 20))
        for mount in self._mounts:
            target, source = mount["target"], mount["source"]
            if "ro" not in actual.get(target, ()) or any(p.startswith(target + "/") for p in actual):
                raise _failure()
            host = _host_info(source)
            with self._runtime_file(root, target) as fd:
                current = os.fstat(fd)
            if not os.path.samestat(host, current) or not (stat.S_ISDIR(host.st_mode) or stat.S_ISREG(host.st_mode)):
                raise _failure()
            if mount["kind"] != "code":
                continue
            expected = {p for p in self._files if self._owner(p) == mount}
            found = set()
            if stat.S_ISREG(host.st_mode):
                found.add(target)
            else:
                entries = 0
                for directory, dirs, files in os.walk(source, followlinks=False):
                    entries += len(dirs) + len(files)
                    if entries > _MAX_FILES * 2:
                        raise _failure()
                    for name in dirs + files:
                        entry = Path(directory) / name
                        info = _host_info(str(entry))
                        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                            raise _failure()
                        runtime_path = target + "/" + str(entry.relative_to(source))
                        if stat.S_ISDIR(info.st_mode) and not any(p.startswith(runtime_path + "/") for p in expected):
                            raise _failure()
                    found.update(target + "/" + str((Path(directory) / name).relative_to(source)) for name in files)
                    if len(found) > _MAX_FILES:
                        raise _failure()
            if found != expected:
                raise _failure()

    def verify(self):
        if not self._lock.acquire(timeout=5):
            self._failed.set()
            raise _failure()
        try:
            if self._closed or self._failed.is_set() or self._pin is None:
                raise _failure()
            deadline = time.monotonic() + 5
            self._pin.check()
            if self._backend(self.pid, self.uid, self.gid, self.artifact) is not None:
                raise _failure()
            self._check_process()
            root = os.open(f"/proc/{self.pid}/root", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                if self._image_mode:
                    self._check_image_skills(root)
                else:
                    self._check_mounts(root)
                self._check_channel_directory(root)
                total = 0
                for path, expected in self._files.items():
                    if time.monotonic() >= deadline:
                        raise _failure()
                    with self._runtime_file(root, path, protected=self._image_mode) as fd:
                        if not self._image_mode:
                            owner = self._owner(path)
                            host = owner["source"] + path.removeprefix(owner["target"])
                            if not os.path.samestat(_host_info(host), os.fstat(fd)):
                                raise _failure()
                        digest, size = self._digest_fd(fd, 1 << 20)
                        total += size
                        if digest != expected or total > _MAX_CODE_BYTES:
                            raise _failure()
                if self._image_mode:
                    self._check_image_skills(root)
                else:
                    self._check_mounts(root)
                self._check_channel_directory(root)
            finally:
                os.close(root)
            self._check_process()
            if self._backend(self.pid, self.uid, self.gid, self.artifact) is not None or time.monotonic() >= deadline:
                raise _failure()
            self._pin.check()
            if self._failed.is_set():
                raise _failure()
        except BaseException:  # noqa: BLE001 - all verification failures invalidate this exact process
            self.close()
            raise _failure() from None
        finally:
            self._lock.release()

    def verify_mount(self, source, target):
        matched = ({"source": source, "target": target} in self._image_skills if self._image_mode
                   else {"source": source, "target": target, "kind": "skill"} in self._mounts)
        if not matched:
            self.close()
            raise _failure()
        self.verify()

    def close(self):
        self._failed.set()
        with self._lock:
            self._closed = True
            if self._pin is not None:
                self._pin.close()
                self._pin = None

    def __enter__(self):
        self.verify()
        return self

    def __exit__(self, *_):
        self.close()
