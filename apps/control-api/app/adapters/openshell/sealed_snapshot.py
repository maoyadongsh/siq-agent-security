"""Private authenticated recovery material; never a public receipt or authority."""

from __future__ import annotations

import base64
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.adapters.openshell.policy_safety import canonical_json, policy_digest

_VERSION = "openshell-sealed-snapshot/v1"
_DOMAIN = b"siq-as/openshell-recovery\x00"
_MAX_PLAINTEXT = 1024 * 1024
_KEY_ID = re.compile(r"[A-Za-z0-9_.-]{1,64}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")


class SnapshotError(Exception):
    """Only fixed failure categories may leave this module."""


@dataclass(frozen=True)
class SnapshotOrigin:
    operation_id: str
    tenant_id: str
    environment_id: str
    binding_id: str
    deployment_id: str
    backend: str
    target: str
    gateway_fingerprint: str
    gateway_name_sha256: str
    base_revision: str
    base_digest: str
    expected_digest: str

    def validate(self) -> None:
        for value in asdict(self).values():
            if not isinstance(value, str) or not value or len(value) > 512 or any(ord(c) < 32 for c in value):
                raise SnapshotError("snapshot_origin_invalid")
        if self.backend != "openshell-cli":
            raise SnapshotError("snapshot_origin_invalid")
        for value in (self.gateway_name_sha256, self.base_digest, self.expected_digest):
            if not _DIGEST.fullmatch(value):
                raise SnapshotError("snapshot_origin_invalid")
        if not re.fullmatch(r"[1-9][0-9]{0,31}", self.base_revision):
            raise SnapshotError("snapshot_origin_invalid")


def _policy_bytes(policy: dict[str, Any]) -> bytes:
    # Preserve the parser's JSON value domain and reject lossy dict keys/floats.
    def walk(value: Any, depth: int) -> None:
        if depth > 64:
            raise SnapshotError("snapshot_policy_invalid")
        if value is None or isinstance(value, (str, bool)):
            return
        if type(value) is int and -(2**63) <= value <= 2**63 - 1:
            return
        if isinstance(value, list):
            for item in value:
                walk(item, depth + 1)
            return
        if isinstance(value, dict) and all(isinstance(k, str) for k in value):
            for item in value.values():
                walk(item, depth + 1)
            return
        raise SnapshotError("snapshot_policy_invalid")

    if not isinstance(policy, dict):
        raise SnapshotError("snapshot_policy_invalid")
    walk(policy, 0)
    try:
        raw = canonical_json(policy)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise SnapshotError("snapshot_policy_invalid") from None
    if len(raw) > _MAX_PLAINTEXT:
        raise SnapshotError("snapshot_too_large")
    return raw


class SnapshotCipher:
    """Keys supplied by the service's secret boundary, never persisted here."""

    def __init__(self, keys: Mapping[str, bytes], active_key_id: str):
        if not keys or len(keys) > 32:
            raise SnapshotError("snapshot_keyring_invalid")
        for key_id, key in keys.items():
            if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id) or type(key) is not bytes or len(key) != 32:
                raise SnapshotError("snapshot_keyring_invalid")
        if active_key_id not in keys:
            raise SnapshotError("snapshot_key_unavailable")
        self._keys = dict(keys)
        self._active = active_key_id

    def _aad(self, origin: SnapshotOrigin, key_id: str) -> bytes:
        origin.validate()
        return _DOMAIN + canonical_json({"version": _VERSION, "key_id": key_id, "origin": asdict(origin)})

    def seal(self, origin: SnapshotOrigin, policy: dict[str, Any]) -> dict[str, str]:
        aad = self._aad(origin, self._active)
        raw = _policy_bytes(policy)
        if policy_digest(policy) != origin.base_digest:
            raise SnapshotError("snapshot_digest_mismatch")
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(self._keys[self._active]).encrypt(nonce, raw, aad)
        return {
            "version": _VERSION,
            "key_id": self._active,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }

    def open(self, origin: SnapshotOrigin, envelope: dict[str, str]) -> dict[str, Any]:
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"version", "key_id", "nonce", "ciphertext"}
            or any(not isinstance(v, str) for v in envelope.values())
            or envelope["version"] != _VERSION
            or not _KEY_ID.fullmatch(envelope["key_id"])
            or len(envelope["nonce"]) != 16
            or len(envelope["ciphertext"]) > 4 * ((_MAX_PLAINTEXT + 18) // 3)
        ):
            raise SnapshotError("snapshot_envelope_invalid")
        key_id = envelope["key_id"]
        key = self._keys.get(key_id)
        if key is None:
            raise SnapshotError("snapshot_key_unavailable")
        aad = self._aad(origin, key_id)
        try:
            nonce = base64.b64decode(envelope["nonce"], validate=True)
            ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
            if len(nonce) != 12 or not 16 <= len(ciphertext) <= _MAX_PLAINTEXT + 16:
                raise ValueError
        except (ValueError, UnicodeError):
            raise SnapshotError("snapshot_envelope_invalid") from None
        try:
            raw = AESGCM(key).decrypt(nonce, ciphertext, aad)
        except InvalidTag:
            raise SnapshotError("snapshot_authentication_failed") from None
        try:
            policy = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            raise SnapshotError("snapshot_policy_invalid") from None
        if _policy_bytes(policy) != raw or policy_digest(policy) != origin.base_digest:
            raise SnapshotError("snapshot_digest_mismatch")
        return policy
