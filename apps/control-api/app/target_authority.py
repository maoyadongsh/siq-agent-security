"""Operator target assignments, independent of tenant-supplied attestations."""

import hashlib
import json
import os
import stat
import sys
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import RuntimeBinding

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Target = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
MAX_BYTES = 256 * 1024


class TargetAuthorityError(ValueError):
    """Fixed public-safe codes only, never parser details or filesystem paths."""


class TargetAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: Identifier
    tenant_id: Identifier
    environment_id: Identifier
    asset_id: Identifier
    agent_instance_id: Identifier
    endpoint_fingerprint: Digest
    gateway_name_sha256: Digest
    backend_target_id: Target


class TargetAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["enterprise-runtime-target-authority/v1"]
    issued_at: datetime
    expires_at: datetime
    assignments: tuple[TargetAssignment, ...] = Field(max_length=1024)

    @field_validator("issued_at", "expires_at", mode="before")
    @classmethod
    def wire_timestamp(cls, value):
        if not isinstance(value, str):
            raise ValueError("timestamp_string_required")
        return value

    @model_validator(mode="after")
    def consistent(self):
        if (self.issued_at.utcoffset() is None or self.expires_at.utcoffset() is None
            or self.issued_at.utcoffset().total_seconds() != 0 or self.expires_at.utcoffset().total_seconds() != 0
            or self.expires_at <= self.issued_at):
            raise ValueError("invalid_validity")
        ids = [item.id for item in self.assignments]
        targets = [(item.endpoint_fingerprint, item.backend_target_id) for item in self.assignments]
        if len(set(ids)) != len(ids) or len(set(targets)) != len(targets):
            raise ValueError("ambiguous_assignment")
        return self


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode, info.st_uid)


def _read_authority_bytes(path: str) -> bytes:
    if sys.platform != "linux":
        raise TargetAuthorityError("target_authority_platform_unsupported")
    parts = path.split("/")
    if not path.startswith("/") or any(part in ("", ".", "..") for part in parts[1:]):
        raise TargetAuthorityError("target_authority_unconfigured")
    directory = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid not in {0, os.geteuid()}
                or before.st_mode & 0o022 or before.st_nlink != 1 or before.st_size > MAX_BYTES):
                raise TargetAuthorityError("target_authority_unsafe")
            raw = stream.read(MAX_BYTES + 1)
            after = os.fstat(stream.fileno())
            if len(raw) > MAX_BYTES or _identity(before) != _identity(after):
                raise TargetAuthorityError("target_authority_unsafe")
            return raw
    finally:
        os.close(directory)


def authorize_runtime_target(
    binding: RuntimeBinding, tenant_id: str, endpoint_fingerprint: str, gateway_name_sha256: str,
    *, now: datetime | None = None,
) -> dict:
    """Pure file read + exact match; caller must still verify runtime and approval."""
    if binding.tenant_id != tenant_id or binding.backend != "openshell-cli":
        raise TargetAuthorityError("target_authority_unassigned")
    path = os.environ.get("SIQ_AS_OPENSHELL_TARGET_AUTHORITY_FILE", "")
    try:
        raw = _read_authority_bytes(path)
        catalog = TargetAuthority.model_validate(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object))
    except TargetAuthorityError:
        raise
    except OSError:
        raise TargetAuthorityError("target_authority_unavailable") from None
    except (ValueError, RecursionError):
        raise TargetAuthorityError("target_authority_invalid") from None
    checked_at = now or datetime.now(UTC)
    if checked_at.utcoffset() is None or not catalog.issued_at <= checked_at < catalog.expires_at:
        raise TargetAuthorityError("target_authority_expired")
    expected = (tenant_id, binding.environment_id, binding.asset_id, binding.agent_instance_id,
                endpoint_fingerprint, gateway_name_sha256, binding.backend_target_id)
    for item in catalog.assignments:
        actual = (item.tenant_id, item.environment_id, item.asset_id, item.agent_instance_id,
                  item.endpoint_fingerprint, item.gateway_name_sha256, item.backend_target_id)
        if actual == expected:
            return {"assignment_id": item.id, "authority_sha256": hashlib.sha256(raw).hexdigest(),
                    "expires_at": catalog.expires_at.isoformat().replace("+00:00", "Z")}
    raise TargetAuthorityError("target_authority_unassigned")


def require_target_authority(binding: RuntimeBinding, tenant_id: str, capabilities) -> dict:
    """Deployment gate: no client attestation, dev fallback or historical authorization."""
    if (not capabilities.handshake_verified or not capabilities.handshake_gateway
        or len(capabilities.endpoint_fingerprint) != 64):
        raise HTTPException(409, "deployment_target_identity_unconfirmed")
    try:
        return authorize_runtime_target(
            binding, tenant_id, capabilities.endpoint_fingerprint,
            hashlib.sha256(capabilities.handshake_gateway.encode("utf-8")).hexdigest(),
        )
    except TargetAuthorityError:
        raise HTTPException(409, "deployment_target_authority_unverified") from None
