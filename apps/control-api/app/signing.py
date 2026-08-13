"""任务签名（Ed25519）：控制面签名、Edge 验签（对应威胁 T5 任务重放/篡改）。

- 生产：SIQ_AS_TASK_SIGNING_KEY_SEED（base64，32 字节）来自 Secret Manager；
- dev：启动时自动生成并常驻内存（重启后旧任务签名失效，可接受）；
- 规范签名：dict 按键排序 + JSON 紧凑序列化后 Ed25519 签名；
- 公钥随 register 响应下发给 Edge 钉住（ADR-002）。
"""

from __future__ import annotations

import base64
import json
import os
from functools import lru_cache

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


@lru_cache(maxsize=1)
def get_signing_key() -> Ed25519PrivateKey:
    seed_b64 = os.getenv("SIQ_AS_TASK_SIGNING_KEY_SEED")
    if seed_b64:
        seed = base64.b64decode(seed_b64)
        if len(seed) != 32:
            raise RuntimeError("SIQ_AS_TASK_SIGNING_KEY_SEED 必须是 32 字节 base64")
        return Ed25519PrivateKey.from_private_bytes(seed)
    return Ed25519PrivateKey.generate()


def public_key_base64() -> str:
    raw = get_signing_key().public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    return base64.b64encode(raw).decode("ascii")


def sign_task_payload(task_id: str, task_type: str, environment_id: str, payload: dict, expires_at: str) -> str:
    """签名信封：{task_id, task_type, environment_id, payload, expires_at} 规范序列化。"""
    envelope = {
        "task_id": task_id,
        "task_type": task_type,
        "environment_id": environment_id,
        "payload": payload,
        "expires_at": expires_at,
    }
    sig = get_signing_key().sign(_canonical_bytes(envelope))
    return base64.b64encode(sig).decode("ascii")


def build_task_envelope(task_id: str, task_type: str, environment_id: str, payload: dict, expires_at: str) -> dict:
    """Edge 侧验签用的同一信封（供测试与文档对齐）。"""
    return {
        "task_id": task_id,
        "task_type": task_type,
        "environment_id": environment_id,
        "payload": payload,
        "expires_at": expires_at,
    }


def verify_task_signature(public_key_b64: str, envelope: dict, signature_b64: str) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        public_key.verify(base64.b64decode(signature_b64), _canonical_bytes(envelope))
        return True
    except (InvalidSignature, ValueError):
        return False
