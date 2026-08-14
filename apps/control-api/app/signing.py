"""任务签名（Ed25519）：控制面签名、Edge 验签（对应威胁 T5 任务重放/篡改）。

- 生产：SIQ_AS_TASK_SIGNING_KEY_SEED（base64，32 字节）来自 Secret Manager；
- dev：自动生成到仓库外的用户状态目录，仅当前用户可读；
- 规范签名：dict 按键排序 + JSON 紧凑序列化后 Ed25519 签名；
- 公钥随 register 响应下发给 Edge 钉住（ADR-002）。
"""

from __future__ import annotations

import base64
import fcntl
import json
import os
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.config import load_settings


def _canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


@lru_cache(maxsize=1)
def get_signing_key() -> Ed25519PrivateKey:
    settings = load_settings()
    seed_b64 = settings.task_signing_key_seed
    if seed_b64:
        seed = base64.b64decode(seed_b64, validate=True)
        return Ed25519PrivateKey.from_private_bytes(seed)
    if not settings.dev_mode or not settings.task_signing_key_file:
        raise RuntimeError("task signing key is unavailable (fail closed)")

    path = Path(settings.task_signing_key_file)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    lock_fd = os.open(f"{path}.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if path.exists():
            os.chmod(path, 0o600)
            existing = path.read_text(encoding="ascii").strip()
            try:
                seed = base64.b64decode(existing, validate=True)
            except ValueError as exc:
                raise RuntimeError(f"开发签名密钥文件无效: {path}") from exc
            if len(seed) != 32:
                raise RuntimeError(f"开发签名密钥文件长度无效: {path}")
            return Ed25519PrivateKey.from_private_bytes(seed)

        key = Ed25519PrivateKey.generate()
        raw = key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(base64.b64encode(raw).decode("ascii"))
            fh.flush()
            os.fsync(fh.fileno())
        return key
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


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
