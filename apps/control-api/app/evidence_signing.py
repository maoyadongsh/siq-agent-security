"""Edge Evidence/Batch 的 Ed25519 验签与规范序列化。

规范化合同（DEV09-B/H）：
  json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)
与 Edge `canon.MarshalUTF8` / `CanonicalJSON` 对齐；不得用于任务签名
（任务为 ensure_ascii=True，见 signing.py）。

路由 id：`evidence_utf8/v1`。DEV09-H 起 Edge SealEvidence 默认嵌入该字段；
缺省时双读为同一合同。错误 schema（如 local_canonical/v1）fail-closed。

固定向量：packages/contracts/fixtures/evidence_signature_vectors_v1.json
         packages/contracts/fixtures/evidence_embedded_schema_vectors_v1.json
清单：packages/contracts/signing-inventory-v1.md
"""

from __future__ import annotations

import json
from copy import deepcopy

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

EVIDENCE_SIGNING_SCHEMA_V1 = "evidence_utf8/v1"


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


def normalize_evidence_signing_schema(evidence: dict) -> str:
    """Dual-read: missing/empty → evidence_utf8/v1; wrong type or id → ValueError."""
    raw = evidence.get("signing_schema", None)
    if raw is None or raw == "":
        return EVIDENCE_SIGNING_SCHEMA_V1
    if not isinstance(raw, str):
        raise ValueError("signing_schema must be string")
    if raw != EVIDENCE_SIGNING_SCHEMA_V1:
        raise ValueError(f"unsupported evidence signing_schema: {raw}")
    return raw


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


def verify_evidence_signature(public_key_pem: str, evidence: dict) -> bool:
    """Schema dual-read + UTF-8 canon verify. Wrong schema never accepts."""
    try:
        normalize_evidence_signing_schema(evidence)
    except ValueError:
        return False
    return verify_hex_signature(
        public_key_pem,
        evidence_signed_bytes(evidence),
        evidence.get("signature", "") or "",
    )
