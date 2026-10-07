"""Cooperating-writer mutex; does not implement an external backend CAS."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine


class TargetLockError(Exception):
    pass


def _key(fingerprint: str, target: str) -> bytes:
    if any(not isinstance(value, str) or not value or len(value) > 512 for value in (fingerprint, target)):
        raise TargetLockError("operation_lock_identity_invalid")
    return hashlib.sha256(b"siq-as/openshell-target/v1\x00" + json.dumps(
        [fingerprint, target], ensure_ascii=True, separators=(",", ":"),
    ).encode()).digest()


@contextmanager
def target_mutex(engine: Engine, fingerprint: str, target: str, *, timeout: float = 2.0):
    if not 0 <= timeout <= 10:
        raise TargetLockError("operation_lock_timeout_invalid")
    key = _key(fingerprint, target)
    if engine.dialect.name == "postgresql":
        with _postgres_lock(engine, int.from_bytes(key[:8], "big", signed=True), timeout):
            yield
    elif engine.dialect.name == "sqlite":
        with _sqlite_lock(engine, key.hex(), timeout):
            yield
    else:
        raise TargetLockError("operation_lock_backend_unsupported")


@contextmanager
def _postgres_lock(engine: Engine, key: int, timeout: float):
    connection = engine.connect()
    try:
        deadline = time.monotonic() + timeout
        while True:
            acquired = bool(connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}))
            connection.commit()
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise TargetLockError("operation_target_busy")
            time.sleep(min(0.025, max(0, deadline - time.monotonic())))
    except BaseException:
        # A failed reply/commit can leave the session's lock outcome unknown.
        connection.invalidate()
        connection.close()
        raise
    try:
        yield
    finally:
        try:
            released = connection.scalar(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
            connection.commit()
            if released is not True:
                raise TargetLockError("operation_lock_release_failed")
        except BaseException:
            connection.invalidate()
            raise
        finally:
            connection.close()


@contextmanager
def _sqlite_lock(engine: Engine, key: str, timeout: float):
    if os.name != "posix":
        raise TargetLockError("operation_lock_backend_unsupported")
    import fcntl

    database = engine.url.database
    if (not database or database == ":memory:" or database.startswith("file:")
        or engine.url.query.get("uri") == "true"):
        raise TargetLockError("operation_lock_database_unsupported")
    database_path = Path(database).resolve()
    lock_dir = database_path.parent / ("." + database_path.name + ".siq-operation-locks")
    directory_fd = None
    fd = None
    try:
        lock_dir.mkdir(mode=0o700, exist_ok=True)
        directory_fd = os.open(lock_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(directory_fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise TargetLockError("operation_lock_storage_invalid")
        fd = os.open(key + ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=directory_fd)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
            raise TargetLockError("operation_lock_storage_invalid")
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TargetLockError("operation_target_busy") from None
                time.sleep(min(0.025, max(0, deadline - time.monotonic())))
    except OSError:
        if fd is not None:
            os.close(fd)
            fd = None
        raise TargetLockError("operation_lock_storage_invalid") from None
    except BaseException:
        if fd is not None:
            os.close(fd)
            fd = None
        raise
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)  # Closing releases flock; never unlink a shared lock inode.
