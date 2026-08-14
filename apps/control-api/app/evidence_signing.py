"""Edge Evidence/Batch 的 Ed25519 验签与规范序列化。"""

from __future__ import annotations

import json
from copy import deepcopy

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def canonical_json(value: object) -> bytes:
    """与 Edge encoding/json(SetEscapeHTML(false)) 一致的 UTF-8、排序、紧凑 JSON。"""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def load_edge_public_key(public_key_pem: str) -> Ed25519PublicKey:
    try:
        key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
    except (ValueError, TypeError, UnicodeEncodeError) as exc:
        raise ValueError("edge public key is not valid PEM") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("edge public key must be Ed25519")
    return key


def evidence_signed_bytes(evidence: dict) -> bytes:
    payload = deepcopy(evidence)
    payload["signature"] = ""
    return canonical_json(payload)


def batch_signed_bytes(batch: dict) -> bytes:
    payload = deepcopy(batch)
    payload.pop("signature", None)
    return canonical_json(payload)


def verify_hex_signature(public_key_pem: str, payload: bytes, signature_hex: str) -> bool:
    try:
        signature = bytes.fromhex(signature_hex)
        load_edge_public_key(public_key_pem).verify(signature, payload)
        return True
    except (InvalidSignature, ValueError):
        return False
