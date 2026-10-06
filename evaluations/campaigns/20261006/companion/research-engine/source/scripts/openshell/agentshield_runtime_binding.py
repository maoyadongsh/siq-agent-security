#!/usr/bin/python3 -IB
"""Validate the host-owned AgentShield authority material for Hermes 0.21."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = "siq.openshell.agentshield_authority_binding.v1"
DEFAULT_RELATIVE = Path("var/openshell/secrets/agentshield-runtime-authority.json")
SCOPED_RELATIVE = Path("var/openshell/secrets/agentshield-runtime-authorities")
MAX_BINDING_BYTES = 64 * 1024
MAX_CREDENTIAL_BYTES = 256

RUNTIME_ID_RE = re.compile(r"ri-[a-f0-9]{32}\Z")
INSTANCE_ID_RE = re.compile(r"hi-[a-f0-9]{32}\Z")
AGENT_ID_RE = re.compile(r"hri-[a-f0-9]{32}\Z")
GRANT_ID_RE = re.compile(r"(?:grt-(?:d-)?[a-f0-9-]{12,96}|grt-si-[a-f0-9]{64})\Z")
SCOPE_ID_RE = re.compile(r"[a-f0-9]{24}\Z")
SHA256_RE = re.compile(r"[a-f0-9]{64}\Z")
IMAGE_ID_RE = re.compile(r"sha256:[a-f0-9]{64}\Z")


class AuthorityBindingError(RuntimeError):
    """Stable, value-free binding validation error."""


@dataclass(frozen=True)
class AuthorityBinding:
    runtime_identity_id: str
    instance_id: str
    agent_id: str
    grant_id: str
    grant_revision: int
    credential_path: Path
    scope_id: str
    relay_binary: Path
    relay_sha256: str
    helper_image_ref: str
    helper_image_id: str
    binding_sha256: str

    @property
    def session_namespace(self) -> str:
        return f"siq:openshell:pool:{self.scope_id}"


FIELDS = {
    "schema_version",
    "runtime_identity_id",
    "instance_id",
    "agent_id",
    "grant_id",
    "grant_revision",
    "credential_path",
    "scope_id",
    "relay_binary",
    "relay_sha256",
    "helper_image_ref",
    "helper_image_id",
}


def _private_regular(path: Path, *, executable: bool = False) -> os.stat_result:
    try:
        before = path.lstat()
    except OSError as exc:
        raise AuthorityBindingError("agentshield_authority_file_unavailable") from exc
    if (
        not stat.S_ISREG(before.st_mode)
        or before.st_uid != os.geteuid()
        or before.st_nlink != 1
        or before.st_mode & (stat.S_ISUID | stat.S_ISGID)
        or (executable and (before.st_mode & 0o022 or not before.st_mode & stat.S_IXUSR))
        or (not executable and stat.S_IMODE(before.st_mode) != 0o600)
    ):
        raise AuthorityBindingError("agentshield_authority_file_unsafe")
    return before


def _absolute_clean(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise AuthorityBindingError("agentshield_authority_binding_invalid")
    path = Path(value)
    if not path.is_absolute() or Path(os.path.normpath(path)) != path:
        raise AuthorityBindingError("agentshield_authority_binding_invalid")
    return path


def _authority_path(project_root: Path, expected_scope_id: str) -> Path:
    scoped_root = project_root / SCOPED_RELATIVE
    try:
        info = scoped_root.lstat()
    except FileNotFoundError:
        return project_root / DEFAULT_RELATIVE
    except OSError as exc:
        raise AuthorityBindingError("agentshield_authority_file_unavailable") from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise AuthorityBindingError("agentshield_authority_file_unsafe")
    scoped = scoped_root / f"{expected_scope_id}.json"
    try:
        scoped.lstat()
    except FileNotFoundError:
        return project_root / DEFAULT_RELATIVE
    except OSError as exc:
        raise AuthorityBindingError("agentshield_authority_file_unavailable") from exc
    return scoped


def load(project_root: Path, *, expected_scope_id: str) -> AuthorityBinding:
    """Load a strict binding without returning the credential value."""

    if SCOPE_ID_RE.fullmatch(expected_scope_id) is None:
        raise AuthorityBindingError("agentshield_scope_invalid")
    path = _authority_path(project_root, expected_scope_id)
    info = _private_regular(path)
    if info.st_size <= 0 or info.st_size > MAX_BINDING_BYTES:
        raise AuthorityBindingError("agentshield_authority_binding_invalid")
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuthorityBindingError("agentshield_authority_binding_invalid") from exc
    if not isinstance(value, dict) or set(value) != FIELDS or value.get("schema_version") != SCHEMA_VERSION:
        raise AuthorityBindingError("agentshield_authority_binding_invalid")
    runtime_identity_id = value.get("runtime_identity_id")
    instance_id = value.get("instance_id")
    agent_id = value.get("agent_id")
    grant_id = value.get("grant_id")
    grant_revision = value.get("grant_revision")
    scope_id = value.get("scope_id")
    relay_sha256 = value.get("relay_sha256")
    helper_image_ref = value.get("helper_image_ref")
    helper_image_id = value.get("helper_image_id")
    if (
        not isinstance(runtime_identity_id, str)
        or RUNTIME_ID_RE.fullmatch(runtime_identity_id) is None
        or not isinstance(instance_id, str)
        or INSTANCE_ID_RE.fullmatch(instance_id) is None
        or not isinstance(agent_id, str)
        or AGENT_ID_RE.fullmatch(agent_id) is None
        or agent_id[4:] != instance_id[3:]
        or not isinstance(grant_id, str)
        or GRANT_ID_RE.fullmatch(grant_id) is None
        or isinstance(grant_revision, bool)
        or not isinstance(grant_revision, int)
        or grant_revision < 0
        or scope_id != expected_scope_id
        or not isinstance(relay_sha256, str)
        or SHA256_RE.fullmatch(relay_sha256) is None
        or not isinstance(helper_image_ref, str)
        or not helper_image_ref
        or len(helper_image_ref) > 256
        or any(character.isspace() for character in helper_image_ref)
        or not isinstance(helper_image_id, str)
        or IMAGE_ID_RE.fullmatch(helper_image_id) is None
    ):
        raise AuthorityBindingError("agentshield_authority_binding_invalid")
    credential_path = _absolute_clean(value.get("credential_path"))
    credential_info = _private_regular(credential_path)
    if credential_info.st_size <= 0 or credential_info.st_size > MAX_CREDENTIAL_BYTES:
        raise AuthorityBindingError("agentshield_runtime_credential_invalid")
    try:
        credential = credential_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise AuthorityBindingError("agentshield_runtime_credential_invalid") from exc
    if re.fullmatch(re.escape(runtime_identity_id) + r"\.[a-f0-9]{64}", credential) is None:
        raise AuthorityBindingError("agentshield_runtime_credential_invalid")
    relay_binary = _absolute_clean(value.get("relay_binary"))
    _private_regular(relay_binary, executable=True)
    try:
        actual_relay_sha256 = hashlib.sha256(relay_binary.read_bytes()).hexdigest()
    except OSError as exc:
        raise AuthorityBindingError("agentshield_relay_binary_unavailable") from exc
    if actual_relay_sha256 != relay_sha256:
        raise AuthorityBindingError("agentshield_relay_binary_digest_mismatch")
    return AuthorityBinding(
        runtime_identity_id=runtime_identity_id,
        instance_id=instance_id,
        agent_id=agent_id,
        grant_id=grant_id,
        grant_revision=grant_revision,
        credential_path=credential_path,
        scope_id=scope_id,
        relay_binary=relay_binary,
        relay_sha256=relay_sha256,
        helper_image_ref=helper_image_ref,
        helper_image_id=helper_image_id,
        binding_sha256=hashlib.sha256(raw).hexdigest(),
    )


__all__ = [
    "AuthorityBinding",
    "AuthorityBindingError",
    "DEFAULT_RELATIVE",
    "SCOPED_RELATIVE",
    "SCHEMA_VERSION",
    "load",
]
