"""Owner-controlled installation catalog, not a publisher-signature verifier."""

import json
import os
import stat
from typing import Literal

from pydantic import Field, field_validator

from app.install_plan import ConnectorID, Digest, EnterpriseInstallPlan, InstallConnector, StrictWire, Version


class InstallRequest(StrictWire):
    schema_version: Literal["enterprise-install-request/v1"]
    target_arch: Literal["arm64", "amd64"]
    service_mode: Literal["user", "system"]
    connectors: list[ConnectorID] = Field(min_length=1, max_length=12)

    @field_validator("connectors")
    @classmethod
    def unique_connectors(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("duplicate_connector_id")
        return value


class InstallRelease(StrictWire):
    target_arch: Literal["arm64", "amd64"]
    release_version: Version
    release_manifest_sha256: Digest
    connectors: list[InstallConnector] = Field(min_length=1, max_length=12)

    @field_validator("connectors")
    @classmethod
    def unique_connectors(cls, value):
        if len({c.id for c in value}) != len(value):
            raise ValueError("duplicate_catalog_connector")
        return value


class InstallCatalog(StrictWire):
    schema_version: Literal["enterprise-install-catalog/v1"]
    control_plane_origin: str = Field(min_length=1, max_length=2048)
    allowed_service_modes: list[Literal["user", "system"]] = Field(min_length=1, max_length=2)
    releases: list[InstallRelease] = Field(min_length=1, max_length=2)

    @field_validator("control_plane_origin")
    @classmethod
    def trusted_origin(cls, value):
        return EnterpriseInstallPlan.trusted_origin_shape(value)

    @field_validator("releases")
    @classmethod
    def unique_architectures(cls, value):
        if len({r.target_arch for r in value}) != len(value):
            raise ValueError("duplicate_catalog_architecture")
        return value


class InstallOptions(InstallCatalog):
    schema_version: Literal["enterprise-install-options/v1"]
    environment_id: str
    purpose: Literal["discovery_only"] = "discovery_only"
    release_signature_verified: Literal[False] = False


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate_catalog_field")
        value[key] = item
    return value


def load_install_catalog() -> InstallCatalog:
    """Explicit, absolute, non-symlink, owner-controlled local deployment input.

    No network resolution, arbitrary config execution or fallback to browser Host.
    Neither this file nor its hashes constitute proof of publisher signatures.
    """
    path = os.environ.get("SIQ_AS_INSTALL_CATALOG_FILE", "")
    if not os.path.isabs(path):
        raise ValueError("install_catalog_unconfigured")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o022
            or info.st_uid not in {0, os.geteuid()}
            or info.st_size > 2 * 1024 * 1024
        ):
            raise ValueError("unsafe_install_catalog")
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("oversized_install_catalog")
    return InstallCatalog.model_validate(json.loads(raw, object_pairs_hook=_unique_object))
