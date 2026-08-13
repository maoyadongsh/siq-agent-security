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
from dataclasses import dataclass, field
from functools import lru_cache

import httpx
import jwt
from fastapi import Depends, HTTPException, Request

from app.config import Settings, load_settings
from app.db import session_scope
from app.models import EdgeAgent

settings: Settings = load_settings()

# 产品内置角色 → 权限点（设计文档 §19.2；SIQ 部署时向 SIQ IAM 注册对应权限点）
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "tenant_admin": {"env:manage", "env:read", "user:assign", "role:manage"},
    "security_admin": {"policy:manage", "policy:read", "finding:manage", "change:approve", "env:read", "agent:read"},
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
        return required in self.permissions

    @property
    def is_authenticated(self) -> bool:
        return self.identity_type != "anon"


ANONYMOUS = Identity("anon", "anon", "")


@lru_cache(maxsize=1)
def _fetch_jwks(url: str) -> dict:
    """JWKS 拉取带 60s 内存缓存；失败 fail-closed。"""
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _verify_jwt(token: str) -> dict:
    if settings.oidc_jwks_url:
        jwks = _fetch_jwks(settings.oidc_jwks_url)
        header = jwt.get_unverified_header(token)
        key = None
        for jwk in jwks.get("keys", []):
            if jwk.get("kid") == header.get("kid"):
                key = jwk
                break
        if key is None:
            raise HTTPException(status_code=401, detail="unknown_kid")
        claims = jwt.decode(
            token,
            jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key)),
            algorithms=["RS256"],
            issuer=settings.oidc_issuer,
            audience=settings.jwt_audience,
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
    else:
        # dev 回退：共享密钥 HS256，仅 dev_mode
        secret = _dev_secret()
        claims = jwt.decode(token, secret, algorithms=["HS256"], audience=settings.jwt_audience)
    return claims


@lru_cache(maxsize=1)
def _dev_secret() -> str:
    import os

    return os.getenv("SIQ_AS_DEV_JWT_SECRET", "dev-only-secret-change-me")


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
        # 租户归属：优先 claim 内 tenant_id；生产禁止客户端自报（dev 模式下已短路）
        tenant_id = str(claims.get("tenant_id") or "")
        if not tenant_id:
            raise HTTPException(status_code=401, detail="missing_tenant")
        id_type = str(claims.get("type", "user"))
        roles = frozenset(claims.get("roles", []) or [])
        perms: set[str] = set(claims.get("permissions", []) or [])
        for role in roles:
            perms |= ROLE_PERMISSIONS.get(role, set())
        if claims.get("admin") is True:
            perms.add("*")
        return Identity(id_type, str(claims.get("sub")), tenant_id, roles, frozenset(perms))

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


def verify_edge_secret(request: Request, device_identity: str) -> EdgeAgent:
    """Edge 设备认证：secret 哈希比对，吊销即时生效（设计文档 §31.4 验收）。"""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_edge_credentials")
    supplied = auth.removeprefix("Bearer ").strip()
    if not supplied:
        raise HTTPException(status_code=401, detail="missing_edge_credentials")
    with session_scope() as session:
        edge = session.query(EdgeAgent).filter(EdgeAgent.device_identity == device_identity).first()
        if edge is None or edge.revoked_at is not None:
            raise HTTPException(status_code=401, detail="edge_untrusted")
        if not hmac.compare_digest(edge.secret_hash, _sha256(supplied)):
            raise HTTPException(status_code=401, detail="edge_untrusted")
        return edge


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_secret(value: str) -> str:
    return _sha256(value)


def forbid_anonymous(identity: Identity) -> Identity:
    if not identity.is_authenticated:
        raise HTTPException(status_code=401, detail="missing_credentials")
    return identity
