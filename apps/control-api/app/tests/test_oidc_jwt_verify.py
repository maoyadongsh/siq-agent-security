"""DEV08-C：OIDC RS256 验签矩阵（mock JWKS + 受控时钟；非真实 IdP）。"""

from __future__ import annotations

import json
import time
from dataclasses import replace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app import security
from app.config import Settings
from app.jwks import JWKSCache

ISSUER = "https://iam.test/"
AUDIENCE = "siq-agent-security"


def _rsa_pair():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(priv.public_key()))
    jwk["kid"] = "kid-a"
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    return priv, jwk


def _settings(**kwargs) -> Settings:
    base = Settings(
        database_url="sqlite:///./dev.db",
        dev_mode=False,
        oidc_jwks_url="https://iam.test/jwks",
        oidc_issuer=ISSUER,
        jwt_audience=AUDIENCE,
        jwks_ttl_seconds=60.0,
        allow_sqlite=False,
        enrollment_ttl_seconds=3600,
        edge_task_ttl_seconds=3600,
        heartbeat_stale_seconds=300,
        scan_quota_per_tenant=50,
        register_rate_limit=30,
        enrollment_create_rate_limit=30,
        register_rate_window_seconds=60,
        task_signing_key_seed=None,
        task_signing_key_file=None,
        cors_origins=(),
        bootstrap_tenant_id="default",
    )
    return replace(base, **kwargs) if kwargs else base


@pytest.fixture
def oidc_env(monkeypatch):
    priv, jwk = _rsa_pair()
    clock = {"t": 0.0}
    keys = {"current": [dict(jwk)]}

    def fetch(_url: str) -> dict:
        return {"keys": list(keys["current"])}

    cache = JWKSCache(
        url="https://iam.test/jwks",
        ttl_seconds=60.0,
        fetch=fetch,
        clock=lambda: clock["t"],
        unknown_kid_min_interval=5.0,
    )
    monkeypatch.setattr(security, "settings", _settings())
    security.reset_jwks_cache_for_tests()
    monkeypatch.setattr(security, "_jwks_cache", cache)

    def mint(*, kid: str = "kid-a", alg: str = "RS256", key=None, **claims):
        now = int(time.time())
        body = {
            "sub": "user-1",
            "tenant_id": "default",
            "type": "access",
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + 3600,
        }
        body.update(claims)
        headers = {"kid": kid} if alg == "RS256" else {}
        return jwt.encode(body, key if key is not None else priv, algorithm=alg, headers=headers)

    return {"priv": priv, "jwk": jwk, "keys": keys, "clock": clock, "mint": mint, "cache": cache}


def test_rs256_valid_token_verifies(oidc_env):
    token = oidc_env["mint"]()
    claims = security._verify_jwt(token)
    assert claims["sub"] == "user-1"
    assert claims["aud"] == AUDIENCE


def test_wrong_audience_rejected(oidc_env):
    token = oidc_env["mint"](aud="other-api")
    with pytest.raises(HTTPException) as exc:
        security._verify_jwt(token)
    assert exc.value.status_code == 401
    assert exc.value.detail == "invalid_token"


def test_wrong_issuer_rejected(oidc_env):
    token = oidc_env["mint"](iss="https://evil.test/")
    with pytest.raises(HTTPException) as exc:
        security._verify_jwt(token)
    assert exc.value.detail == "invalid_token"


def test_expired_token_rejected(oidc_env):
    now = int(time.time())
    token = oidc_env["mint"](iat=now - 7200, exp=now - 3600)
    with pytest.raises(HTTPException) as exc:
        security._verify_jwt(token)
    assert exc.value.detail == "invalid_token"


def test_non_rs256_alg_rejected(oidc_env):
    token = oidc_env["mint"](alg="HS256", key="not-a-real-hmac-secret-value-32b!")
    with pytest.raises(HTTPException) as exc:
        security._verify_jwt(token)
    assert exc.value.detail == "alg_rejected"


def test_removed_kid_rejected_after_ttl_trust_window(oidc_env):
    """新 key 刷新后生效；TTL 内仍可能验旧 kid；TTL 后旧 kid 从集中消失则拒绝。"""
    token = oidc_env["mint"]()
    assert security._verify_jwt(token)["sub"] == "user-1"

    # Still within TTL: even if upstream drops kid, cached set still trusts it
    # until expiry (documented trust window = jwks_ttl_seconds).
    oidc_env["keys"]["current"] = []
    oidc_env["clock"]["t"] += 10.0
    assert security._verify_jwt(token)["sub"] == "user-1"

    # Past TTL: refresh sees empty/no kid → unknown_kid
    oidc_env["clock"]["t"] += 60.0
    with pytest.raises(HTTPException) as exc:
        security._verify_jwt(token)
    assert exc.value.detail in {"unknown_kid", "jwks_unavailable", "invalid_token"}


def test_new_kid_accepted_after_refresh(oidc_env):
    priv_b = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk_b = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(priv_b.public_key()))
    jwk_b["kid"] = "kid-b"
    jwk_b["alg"] = "RS256"
    jwk_b["use"] = "sig"

    # Cold cache has only kid-a
    with pytest.raises(HTTPException) as exc:
        security._verify_jwt(oidc_env["mint"](kid="kid-b", key=priv_b))
    assert exc.value.detail == "unknown_kid"

    oidc_env["keys"]["current"] = [oidc_env["jwk"], jwk_b]
    oidc_env["clock"]["t"] += 5.0  # allow unknown_kid refresh
    claims = security._verify_jwt(oidc_env["mint"](kid="kid-b", key=priv_b))
    assert claims["sub"] == "user-1"
