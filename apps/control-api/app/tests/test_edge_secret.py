"""Edge secret 合同（DEV08-B）：高熵 mint、长度下界、哈希比较；不做口令 KDF。"""

from __future__ import annotations

import hmac

from app.security import (
    EDGE_SECRET_MIN_LEN,
    EDGE_SECRET_PREFIX,
    edge_secret_acceptable,
    hash_secret,
    mint_edge_device_secret,
)


def test_mint_edge_device_secret_meets_length_and_prefix():
    secret = mint_edge_device_secret()
    assert secret.startswith(EDGE_SECRET_PREFIX)
    assert len(secret) >= EDGE_SECRET_MIN_LEN
    assert edge_secret_acceptable(secret)
    # 两次 mint 不得碰撞（高熵抽样）
    assert mint_edge_device_secret() != secret


def test_edge_secret_acceptable_rejects_short_and_empty():
    assert not edge_secret_acceptable("")
    assert not edge_secret_acceptable("edge-short")
    assert not edge_secret_acceptable("x" * (EDGE_SECRET_MIN_LEN - 1))
    assert edge_secret_acceptable("x" * EDGE_SECRET_MIN_LEN)


def test_hash_secret_compare_digest_rejects_mismatch():
    a = hash_secret(mint_edge_device_secret())
    b = hash_secret(mint_edge_device_secret())
    assert a != b
    assert hmac.compare_digest(a, a)
    assert not hmac.compare_digest(a, b)
