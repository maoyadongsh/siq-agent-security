"""Operator-only local profiles; never read endpoints or programs from API bodies."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.adapters.openshell.behavior_protection import ProtectedProbeTarget
from app.adapters.openshell.behavior_protocol import (
    BehaviorBinding,
    ConnectTransport,
    Digest,
    ImageDigest,
    ProgramPath,
    Timestamp,
    Token,
    Wire,
    _path,
    _time,
)
from app.adapters.openshell.contracts import AdapterError

MAX_BYTES = 128 * 1024


class ProbeProtection(Wire):
    container_id: Digest
    image_digest: ImageDigest
    namespace: Token
    sandbox_name: Token
    sandbox_id: Token
    uid: Annotated[int, Field(ge=1, le=4294967294)]
    allow_path: ProgramPath
    deny_path: ProgramPath
    probe_sha256: Digest
    supervisor_profile: Literal["unprivileged-container", "openshell-rootful-v0"]

    def target(self) -> ProtectedProbeTarget:
        return ProtectedProbeTarget(**self.model_dump())


class BehaviorProfile(Wire):
    profile_id: Token
    binding: BehaviorBinding
    gateway_name_sha256: Digest
    protection: ProbeProtection
    transport: ConnectTransport
    receiver_ipv4: Annotated[str, Field(max_length=15)]
    receiver_port: Annotated[int, Field(ge=1, le=65535)]
    allow_path: ProgramPath
    deny_path: ProgramPath
    attempts: Annotated[int, Field(ge=3, le=10)]
    timeout_ms: Annotated[int, Field(ge=100, le=10000)]
    issued_at: Timestamp
    expires_at: Timestamp

    @field_validator("receiver_ipv4")
    @classmethod
    def canonical_receiver(cls, value: str) -> str:
        if str(ipaddress.IPv4Address(value)) != value:
            raise ValueError("behavior_profile_invalid")
        return value

    @field_validator("allow_path", "deny_path")
    @classmethod
    def canonical_path(cls, value: str) -> str:
        return _path(value)

    @model_validator(mode="after")
    def consistent(self):
        try:
            target = self.protection.target()
        except AdapterError:
            raise ValueError("behavior_profile_invalid") from None
        if (target.sandbox_name != self.binding.target or target.image_digest != self.binding.image_digest
            or target.probe_sha256 != self.binding.probe_sha256 or target.allow_path != self.allow_path
            or target.deny_path != self.deny_path or self.attempts * 4 * self.timeout_ms > 240000
            or not timedelta(0) < _time(self.expires_at) - _time(self.issued_at) <= timedelta(hours=24)):
            raise ValueError("behavior_profile_invalid")
        return self


class BehaviorProfiles(Wire):
    schema_version: Literal["openshell-behavior-profiles/v1"]
    profiles: Annotated[list[BehaviorProfile], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def unique(self):
        ids = [item.profile_id for item in self.profiles]
        if len(ids) != len(set(ids)):
            raise ValueError("behavior_profile_ambiguous")
        return self


@dataclass(frozen=True)
class ApprovedBehaviorProfile:
    profile: BehaviorProfile
    file_sha256: str


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate key")
        value[key] = item
    return value


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_mode, info.st_uid, info.st_gid, info.st_nlink)


def _directory(info):
    # A root-owned sticky /tmp protects each user's child entry; all other
    # ancestors must be owned by root/operator and not writable by another UID.
    sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid())
        or (info.st_mode & 0o022 and not sticky_root)):
        raise ValueError("unsafe parent")


def _read(path: str) -> bytes:
    parts = path.split("/")
    if not path.startswith("/") or any(p in ("", ".", "..") for p in parts[1:]) or len(parts) > 64:
        raise ValueError("invalid path")
    fds = [os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)]
    stamps = []
    try:
        _directory(os.fstat(fds[0]))
        for part in parts[1:-1]:
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fds[-1])
            fds.append(fd)
            _directory(os.fstat(fd))
        # Keep directory descriptors until after the read; verify names still
        # resolve to the pinned inodes. Ignore unrelated directory content mtimes.
        for fd in fds:
            info = os.fstat(fd)
            stamps.append((info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid))
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fds[-1])
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid not in (0, os.geteuid())
                or before.st_mode & 0o022 or before.st_nlink != 1 or not 0 < before.st_size <= MAX_BYTES):
                raise ValueError("unsafe file")
            raw = stream.read(MAX_BYTES + 1)
            if (len(raw) > MAX_BYTES or _stamp(before) != _stamp(os.fstat(stream.fileno()))
                or _stamp(before) != _stamp(os.stat(parts[-1], dir_fd=fds[-1], follow_symlinks=False))):
                raise ValueError("changed file")
        for index, fd in enumerate(fds):
            info = os.fstat(fd) if index == 0 else os.stat(parts[index], dir_fd=fds[index - 1], follow_symlinks=False)
            if (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid) != stamps[index]:
                raise ValueError("changed parent")
        return raw
    finally:
        for fd in reversed(fds):
            os.close(fd)


def load_behavior_profile(profile_id: str, *, now: datetime | None = None) -> ApprovedBehaviorProfile:
    try:
        raw = _read(os.environ.get("SIQ_AS_OPENSHELL_BEHAVIOR_PROFILES_FILE", ""))
        document = BehaviorProfiles.model_validate(json.loads(raw, object_pairs_hook=_unique_object))
        instant = now or datetime.now(UTC)
        if instant.utcoffset() != timedelta(0):
            raise ValueError("invalid clock")
        matches = [item for item in document.profiles if item.profile_id == profile_id]
        if len(matches) != 1 or not _time(matches[0].issued_at) <= instant < _time(matches[0].expires_at):
            raise ValueError("unavailable profile")
        return ApprovedBehaviorProfile(matches[0], hashlib.sha256(raw).hexdigest())
    except (OSError, ValueError, TypeError, RecursionError, AttributeError):
        raise AdapterError("behavior_profile_unavailable") from None
