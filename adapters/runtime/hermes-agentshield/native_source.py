"""Bounded native Skill bytes and metadata (ADR-056 D2c1), not authority.

Not installed by the legacy plugin. A protected launcher/loader must create one
reader per trusted task, map observations to approved installations and enforce
the final tool decision. This component never executes or preprocesses content.
"""

from __future__ import annotations

import copy
import hashlib
import os
import stat
import sys
import threading
from contextlib import ExitStack
from pathlib import Path

MAX_BYTES = 1048576
MAX_SOURCES = 256
MAX_PATH_BYTES = 4096
MAX_COMPONENTS = 128


class SourceError(RuntimeError):
    """Value-free error: file contents and private paths are not diagnostics."""


def _failure():
    return SourceError("native_skill_source_unavailable")


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _path(value):
    if not isinstance(value, (str, Path)):
        raise _failure()
    raw = str(value)
    encoded = raw.encode("utf-8", errors="strict")
    parts = raw.split("/")[1:]
    if (not raw.startswith("/") or len(encoded) > MAX_PATH_BYTES or "\0" in raw
            or not 1 <= len(parts) <= MAX_COMPONENTS or any(p in ("", ".", "..") for p in parts)):
        raise _failure()
    return raw


def _identity(info):
    return (info.st_dev, info.st_ino)


def _stamp(info):
    return (_identity(info), info.st_mode, info.st_nlink, info.st_uid, info.st_gid,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class _Opened:
    """Hold the entire resolved descriptor chain until observation completes."""

    def __init__(self, path, managed_link_pair=False):
        self.path, self._fds, self._edges = path, [], []
        try:
            directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            root = os.open("/", directory_flags)
            self._fds.append(root)
            parent = root
            parts = path.split("/")[1:]
            for index, part in enumerate(parts):
                flags = (directory_flags if index < len(parts) - 1 else
                         os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
                fd = os.open(part, flags, dir_fd=parent)
                self._fds.append(fd)
                info = os.fstat(fd)
                self._edges.append((parent, part, fd, _identity(info)))
                parent = fd
            self.fd = parent
            info = os.fstat(self.fd)
            allowed_links = (1, 2) if managed_link_pair else (1,)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink not in allowed_links
                    or not 0 <= info.st_size <= MAX_BYTES):
                raise _failure()
            self._stamp = _stamp(info)
            chunks, total = [], 0
            while True:
                chunk = os.read(self.fd, min(65536, MAX_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > MAX_BYTES:
                    raise _failure()
            self.raw = b"".join(chunks)
            if len(self.raw) != info.st_size:
                raise _failure()
            self.verify()
        except BaseException:
            self.close()
            raise

    def verify(self):
        for parent, part, fd, expected in self._edges:
            current = os.stat(part, dir_fd=parent, follow_symlinks=False)
            if _identity(current) != expected or _identity(os.fstat(fd)) != expected:
                raise _failure()
            if stat.S_ISLNK(current.st_mode) or os.get_inheritable(fd):
                raise _failure()
        if _stamp(os.fstat(self.fd)) != self._stamp:
            raise _failure()

    def metadata(self):
        return {"path_sha256": _digest(self.path.encode("utf-8")),
                "sha256": _digest(self.raw), "bytes": len(self.raw)}

    def close(self):
        for fd in reversed(self._fds):
            os.close(fd)
        self._fds.clear()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class SkillSourceReader:
    """One trusted task's observed sources; no text caching or permission rules.

    The observer is mandatory and must bound its own work. Its *only* valid
    return is None, meaning metadata handling finished, not that an action was
    allowed. Every failure permanently closes this reader. A new reader must
    never be used to erase the still-live task's source lineage.
    """

    def __init__(self, observe, *, managed_link_pair=False):
        if (sys.platform != "linux" or not callable(observe) or type(managed_link_pair) is not bool
                or any(not hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_DIRECTORY", "O_CLOEXEC", "O_NONBLOCK"))):
            raise _failure()
        self._observe = observe
        # Only protected bootstrap may enable this. The required observer must
        # verify the signed install's private owner link and read-only mapping.
        self._managed_link_pair = managed_link_pair
        self._pid = os.getpid()
        self._lock = threading.RLock()
        self._closed, self._busy = False, False
        self._sources = {}
        self._pairs = set()

    def close(self):
        # Check before acquiring a lock possibly held by another thread at fork.
        if os.getpid() != self._pid:
            raise _failure()
        with self._lock:
            self._closed = True
            self._sources.clear()
            self._pairs.clear()

    def read(self, skill_file, content_file=None, *, cache_hit=False):
        if os.getpid() != self._pid:
            raise _failure()
        with self._lock:
            if self._closed or self._busy:
                self.close()
                raise _failure()
            self._busy = True
            try:
                return self._read(skill_file, content_file, cache_hit)
            except Exception:  # noqa: BLE001 - observer and I/O errors never expose content or paths
                self.close()
                raise _failure() from None
            except BaseException:
                self.close()
                raise
            finally:
                self._busy = False

    def _read(self, skill_file, content_file, cache_hit):
        main = _path(skill_file)
        source = main if content_file is None else _path(content_file)
        if (Path(main).name != "SKILL.md" or type(cache_hit) is not bool
                or not Path(source).is_relative_to(Path(main).parent)):
            raise _failure()
        pair = (main, source)
        if cache_hit and pair not in self._pairs:
            raise _failure()
        if len(set(self._sources) | {main, source}) > MAX_SOURCES:
            raise _failure()
        with ExitStack() as stack:
            main_file = stack.enter_context(_Opened(main, self._managed_link_pair))
            content = main_file if source == main else stack.enter_context(_Opened(source, self._managed_link_pair))
            pending = {main: main_file.metadata(), source: content.metadata()}
            for path, metadata in pending.items():
                if path in self._sources and self._sources[path] != metadata:
                    raise _failure()
            text = content.raw.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
            value = {"schema_version": "native-skill-source/v1", "skill_file": pending[main],
                     "content_file": pending[source], "text_sha256": _digest(text.encode("utf-8")),
                     "decoding": "utf-8-sig-replace-universal-newlines/v1", "cache_hit": cache_hit}
            # Confirm neither file changed while the second was read, before
            # notifying; recheck again after the callback. Still requires RO mounts.
            main_file.verify()
            content.verify()
            if self._observe(copy.deepcopy(value)) is not None or self._closed:
                raise _failure()
            main_file.verify()
            content.verify()
            self._sources.update(copy.deepcopy(pending))
            self._pairs.add(pair)
            return text
