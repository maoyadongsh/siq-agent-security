"""身份与授权。

对齐工作区不变量与设计文档 §19/§21.1：
- tenant_id 从验证身份派生，不信任客户端覆盖；
- 知道对象 ID 不构成访问权（服务层 404 隐藏存在性）；
- dev 模式身份头仅 SIQ_AS_DEV=1 时生效，生产必须 OIDC/JWKS；
- Edge 凭据只存哈希，吊销即时生效（每次请求在线校验）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from dataclasses import dataclass, field
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, load_settings
from app.jwks import JWKSCache, find_jwk
from app.models import EdgeAgent

settings: Settings = load_settings()

_jwks_cache: JWKSCache | None = None
_jwks_lock = threading.Lock()


def _jwks() -> JWKSCache:
    """懒构建进程内 JWKS 缓存（测试可重置）。"""
    global _jwks_cache
    if _jwks_cache is not None and _jwks_cache.url == settings.oidc_jwks_url:
        return _jwks_cache
    with _jwks_lock:
        if _jwks_cache is None or _jwks_cache.url != settings.oidc_jwks_url:
            if not settings.oidc_jwks_url:
                raise HTTPException(status_code=401, detail="oidc_not_configured")
            _jwks_cache = JWKSCache(url=settings.oidc_jwks_url, ttl_seconds=settings.jwks_ttl_seconds)
        return _jwks_cache


def reset_jwks_cache_for_tests() -> None:
    global _jwks_cache
    _jwks_cache = None

# 产品内置角色 → 权限点（设计文档 §19.2；SIQ 部署时向 SIQ IAM 注册对应权限点）
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "tenant_admin": {"env:manage", "env:read", "user:assign", "role:manage", "quarantine:release"},
    "security_admin": {
        "policy:manage",
        "policy:read",
        "finding:manage",
        "finding:scan",
        "quarantine:release",
        "change:approve",
        "change:break_glass",
        "env:read",
        "agent:read",
    },
    "platform_operator": {"env:manage", "env:read", "edge:manage", "connector:manage"},
    "agent_owner": {"agent:confirm", "change:propose", "agent:read"},
    "reviewer": {"change:approve"},
    "auditor": {"audit:read", "agent:read", "policy:read"},
    "viewer": {"agent:read", "policy:read"},
}


@dataclass(frozen=True)
class Identity:
    identity_type: str  # user|service|edge|system
    actor_id: str
    tenant_id: str
    roles: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[str] = field(default_factory=frozenset)

    def has_permission(self, required: str) -> bool:
        # IAM 管理员 permissions 含 "*"，与工作台/Gateway 通配语义对齐。
        return "*" in self.permissions or required in self.permissions

    @property
    def is_authenticated(self) -> bool:
        return self.identity_type != "anon"


ANONYMOUS = Identity("anon", "anon", "")

# 资源 API（get_identity）可接受的 JWT claim.type。refresh / id_token / 未知类型一律拒绝（DEV08-B）。
RESOURCE_TOKEN_TYPES = frozenset({"access", "user", "service"})

# Edge device secret：注册侧 mint 为 edge- + token_urlsafe(32)（≥43 字符）。验签侧只做长度下界，不泄露原因。
EDGE_SECRET_PREFIX = "edge-"
EDGE_SECRET_MIN_LEN = 40

_ALL_ROLE_PERMISSIONS: frozenset[str] = frozenset(
    perm for perms in ROLE_PERMISSIONS.values() for perm in perms
)


def _identity_from_claims(claims: dict) -> Identity:
    """把 IAM JWT claims 映射为控制面 Identity。

    IAM 把角色主键放在 `roles` / `role_ids`，产品角色码在 `role_codes`。
    管理员是 `permissions: ["*"]` + `role_codes: ["admin"]`，没有 `admin: true`。

    资源身份合同（DEV08-B）：
    - type=refresh / id_token / 未知 → 401 token_type_rejected
    - type=access|user → identity_type=user
    - type=service → identity_type=service（权限仍只从 claims 派生，不因 type 放宽）
    """
    tenant_id = str(claims.get("tenant_id") or "")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="missing_tenant")
    raw_type = str(claims.get("type") or "user")
    if raw_type not in RESOURCE_TOKEN_TYPES:
        raise HTTPException(status_code=401, detail="token_type_rejected")
    id_type = "service" if raw_type == "service" else "user"
    role_codes = frozenset(str(item) for item in (claims.get("role_codes") or []) if item)
    perms: set[str] = {str(item) for item in (claims.get("permissions") or []) if item}
    for code in role_codes:
        perms |= ROLE_PERMISSIONS.get(code, set())
    if claims.get("admin") is True or "*" in perms or "admin" in role_codes:
        perms |= set(_ALL_ROLE_PERMISSIONS)
        perms.add("*")
    return Identity(id_type, str(claims.get("sub")), tenant_id, role_codes, frozenset(perms))


@lru_cache(maxsize=1)
def _dev_secret() -> str:
    import os

    return os.getenv("SIQ_AS_DEV_JWT_SECRET", "dev-only-secret-change-me")


def _verify_jwt(token: str) -> dict:
    if settings.oidc_jwks_url:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.exceptions.DecodeError as exc:
            raise HTTPException(status_code=401, detail="invalid_token") from exc
        kid = header.get("kid")
        alg = header.get("alg")
        if alg != "RS256":
            raise HTTPException(status_code=401, detail="alg_rejected")
        try:
            jwks = _jwks().get_for_kid(kid if isinstance(kid, str) else None)
        except Exception as exc:  # noqa: BLE001 — 上游不可用一律 fail-closed
            raise HTTPException(status_code=401, detail="jwks_unavailable") from exc
        key = find_jwk(jwks, kid if isinstance(kid, str) else None)
        if key is None:
            raise HTTPException(status_code=401, detail="unknown_kid")
        if not settings.oidc_issuer:
            raise HTTPException(status_code=401, detail="oidc_issuer_missing")
        try:
            claims = jwt.decode(
                token,
                jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key)),
                algorithms=["RS256"],
                issuer=settings.oidc_issuer,
                audience=settings.jwt_audience,
                options={"require": ["sub", "exp", "iat", "iss", "aud"]},
            )
        except jwt.exceptions.InvalidTokenError as exc:
            raise HTTPException(status_code=401, detail="invalid_token") from exc
    else:
        # dev 回退：共享密钥 HS256，仅无 JWKS 时
        secret = _dev_secret()
        try:
            claims = jwt.decode(token, secret, algorithms=["HS256"], audience=settings.jwt_audience)
        except jwt.exceptions.InvalidTokenError as exc:
            raise HTTPException(status_code=401, detail="invalid_token") from exc
    return claims


def get_identity(request: Request) -> Identity:
    """人员/服务身份：OIDC JWT（生产）或 X-Dev-* 头（仅 dev_mode）。

    tenant_id 永远来自验证身份，客户端不可覆盖。
    """
    if settings.dev_mode:
        tenant_id = request.headers.get("X-Dev-Tenant-Id")
        user_id = request.headers.get("X-Dev-User-Id", "dev-user")
        if tenant_id:
            roles = set(request.headers.get("X-Dev-Roles", "tenant_admin").split(","))
            perms: set[str] = set()
            for role in roles:
                perms |= ROLE_PERMISSIONS.get(role, set())
            return Identity("user", user_id, tenant_id, frozenset(roles), frozenset(perms))

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        claims = _verify_jwt(auth.removeprefix("Bearer ").strip())
        return _identity_from_claims(claims)

    raise HTTPException(status_code=401, detail="missing_credentials")


def require_permission(permission: str):
    def dependency(identity: Identity = Depends(get_identity)) -> Identity:
        if not identity.has_permission(permission):
            raise HTTPException(status_code=403, detail="forbidden")
        return identity

    return dependency


def ensure_permission(identity: Identity, permission: str) -> None:
    """对象级端点在租户定位（404）之后调用：跨租户/不存在 → 404，同租户无权限 → 403。"""
    if not identity.has_permission(permission):
        raise HTTPException(status_code=403, detail="forbidden")


def verify_edge_secret(request: Request, device_identity: str, session: Session) -> EdgeAgent:
    """Edge 设备认证：secret 哈希比对，吊销即时生效（设计文档 §31.4 验收）。"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_edge_credentials")
    supplied = auth.removeprefix("Bearer ").strip()
    if not edge_secret_acceptable(supplied):
        raise HTTPException(status_code=401, detail="edge_untrusted")
    edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == device_identity))
    if edge is None or edge.revoked_at is not None:
        raise HTTPException(status_code=401, detail="edge_untrusted")
    if not hmac.compare_digest(edge.secret_hash, hash_secret(supplied)):
        raise HTTPException(status_code=401, detail="edge_untrusted")
    return edge


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_secret(value: str) -> str:
    return _sha256(value)


def mint_edge_device_secret() -> str:
    """高熵 Edge secret（DEV08-B）：edge- + urlsafe 32 字节；不做人类口令 KDF。"""
    import secrets

    return f"{EDGE_SECRET_PREFIX}{secrets.token_urlsafe(32)}"


def edge_secret_acceptable(value: str) -> bool:
    """验签侧长度下界；不区分「太短」与「哈希不匹配」，避免侧信道提示。"""
    return isinstance(value, str) and len(value) >= EDGE_SECRET_MIN_LEN


def forbid_anonymous(identity: Identity) -> Identity:
    if not identity.is_authenticated:
        raise HTTPException(status_code=401, detail="missing_credentials")
    return identity
