"""ENT-003 strict install-plan wire model; never an authorization credential.

Schema defines structural validity. This module additionally checks URL/paths,
identity uniqueness and expiry. Issuers must derive tenant/environment from
verified identity; consumers still verify the trusted manifest and user consent.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Version = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9.+_-]*$")]
ConnectorID = Literal[
    "hermes", "openclaw", "directory", "docker", "process", "systemd",
    "kubernetes", "mcp", "piagent", "workbuddy", "dify", "siq",
]


class StrictWire(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class InstallScope(StrictWire):
    roots: list[Annotated[str, Field(min_length=3, max_length=4096)]] = Field(min_length=1, max_length=32)
    include: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(min_length=1, max_length=32)

    @field_validator("roots")
    @classmethod
    def bounded_roots(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("duplicate_scope_root")
        for value in values:
            # Literal absolute/user-home paths; only a terminal /* is supported.
            base = value[:-2] if value.endswith("/*") else value
            segments = base.split("/")
            if (not (base.startswith("/") or base.startswith("~/"))
                    or base in {"/", "~", "~/", "/home", "/root", "/etc", "/proc", "/sys", "/dev"}
                    or any(part in {".", ".."} for part in segments)
                    or any(char in base for char in "*?[]\\")
                    or any(ord(char) < 32 or ord(char) == 127 for char in value)
                    or "//" in base or base.endswith("/")):
                raise ValueError("unsafe_scope_root")
        return values

    @field_validator("include")
    @classmethod
    def literal_filenames(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("duplicate_scope_include")
        for value in values:
            if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value)
                    or value.lower() in {"auth-profiles.json", "credentials.json", "id_rsa", "id_ed25519"}):
                raise ValueError("unsafe_scope_include")
        return values


class InstallConnector(StrictWire):
    id: ConnectorID
    version: Version
    artifact_sha256: Digest
    protocol_version: Literal["connector-protocol.v1"]
    scope: InstallScope


class EnterpriseInstallPlan(StrictWire):
    schema_version: Literal["enterprise-install-plan/v1"]
    plan_id: Annotated[str, Field(pattern=r"^eip-[a-f0-9]{32}$")]
    tenant_id: Identifier
    environment_id: Identifier
    control_plane_origin: Annotated[str, Field(min_length=1, max_length=2048)]
    issued_at: str
    expires_at: str
    target_os: Literal["linux"]
    target_arch: Literal["arm64", "amd64"]
    service_mode: Literal["user", "system"]
    release_version: Version
    release_manifest_sha256: Digest
    connectors: list[InstallConnector] = Field(min_length=1, max_length=12)
    purpose: Literal["discovery_only"]

    @field_validator("control_plane_origin")
    @classmethod
    def trusted_origin_shape(cls, value):
        if not re.fullmatch(r"https://[^/?#@\s]+|http://(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]+)?", value):
            raise ValueError("invalid_control_plane_origin")
        if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("invalid_control_plane_origin")
        try:
            url = urlsplit(value)
            port = url.port
        except ValueError as exc:
            raise ValueError("invalid_control_plane_origin") from exc
        if (not url.hostname or url.username is not None or url.password is not None
                or url.path or url.query or url.fragment or any(char in value for char in "\\?#%")
                or (port is not None and not 1 <= port <= 65535)
                or url.netloc.endswith(":")):
            raise ValueError("invalid_control_plane_origin")
        if url.scheme == "http":
            if url.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("remote_control_plane_requires_https")
        elif url.scheme != "https":
            raise ValueError("invalid_control_plane_scheme")
        # Normalize neither credentials nor origin silently: consent binds bytes.
        if not value.startswith(url.scheme + "://"):
            raise ValueError("noncanonical_control_plane_origin")
        return value

    @field_validator("issued_at", "expires_at")
    @classmethod
    def utc_timestamp(cls, value):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value):
            raise ValueError("timestamp_requires_utc_z")
        datetime.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def consistent_plan(self):
        issued, expires = datetime.fromisoformat(self.issued_at), datetime.fromisoformat(self.expires_at)
        if not timedelta(0) < expires - issued <= timedelta(minutes=15):
            raise ValueError("invalid_plan_lifetime")
        ids = [connector.id for connector in self.connectors]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate_connector_id")
        return self

    def require_current(self, now: datetime | None = None) -> None:
        """Explicit check at issuance/consumption; historical parsing stays possible."""
        current = now if now is not None else datetime.now(UTC)
        if current.tzinfo is None:
            raise ValueError("verification_time_requires_timezone")
        if not datetime.fromisoformat(self.issued_at) <= current < datetime.fromisoformat(self.expires_at):
            raise ValueError("install_plan_not_current")
