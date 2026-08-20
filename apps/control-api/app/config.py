"""运行时配置。

生产基线（对齐工作区不变量）：
- PostgreSQL + Alembic 迁移，禁止自动建表；
- dev_mode 仅显式开发开关（SIQ_AS_DEV=1）才允许 SQLite 与 X-Dev-* 身份头；
- Secret 一律经环境变量/Secret 引用，永不落库明文。
"""

from __future__ import annotations

import os
from base64 import b64decode
from binascii import Error as Base64Error
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0").lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    dev_mode: bool
    oidc_jwks_url: str | None
    oidc_issuer: str | None
    jwt_audience: str
    # 生产强制：dev 模式与 SQLite 必须显式开启，否则拒绝启动
    allow_sqlite: bool
    # Edge 注册码与任务默认 TTL
    enrollment_ttl_seconds: int
    edge_task_ttl_seconds: int
    # 心跳新鲜度阈值（秒），超过则环境标记 stale 的判定依据之一
    heartbeat_stale_seconds: int
    # 每租户 pending 扫描任务上限（威胁 T19：扫描风暴 DoS）
    scan_quota_per_tenant: int
    # 控制面任务签名：生产只能由 Secret Manager 注入；dev 文件必须位于仓库外。
    task_signing_key_seed: str | None
    task_signing_key_file: str | None
    cors_origins: tuple[str, ...]
    request_id_header: str = "X-Request-ID"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


def load_settings() -> Settings:
    dev_mode = _bool("SIQ_AS_DEV")
    database_url = os.getenv(
        "SIQ_AS_DATABASE_URL",
        "sqlite:///./dev.db" if dev_mode else "",
    )
    allow_sqlite = _bool("SIQ_AS_ALLOW_SQLITE", dev_mode)
    if dev_mode and not database_url:
        raise RuntimeError("SIQ_AS_DEV=1 但未配置 SIQ_AS_DATABASE_URL")
    if not dev_mode and not database_url:
        raise RuntimeError("生产模式必须配置 SIQ_AS_DATABASE_URL（PostgreSQL）")
    if not dev_mode and not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise RuntimeError("生产模式仅允许 PostgreSQL（SIQ_AS_DATABASE_URL）")
    if database_url.startswith("sqlite") and (not dev_mode or not allow_sqlite):
        raise RuntimeError("SQLite 仅显式开发模式允许（SIQ_AS_ALLOW_SQLITE=1）")

    oidc_jwks_url = os.getenv("SIQ_AS_OIDC_JWKS_URL") or None
    if not dev_mode and not oidc_jwks_url:
        raise RuntimeError("生产模式必须配置 SIQ_AS_OIDC_JWKS_URL（RS256/JWKS）")

    task_signing_key_seed = os.getenv("SIQ_AS_TASK_SIGNING_KEY_SEED") or None
    if task_signing_key_seed:
        try:
            seed = b64decode(task_signing_key_seed, validate=True)
        except (Base64Error, ValueError) as exc:
            raise RuntimeError("SIQ_AS_TASK_SIGNING_KEY_SEED 必须是合法 base64") from exc
        if len(seed) != 32:
            raise RuntimeError("SIQ_AS_TASK_SIGNING_KEY_SEED 必须是 32 字节 base64")
    if not dev_mode and not task_signing_key_seed:
        raise RuntimeError("生产模式必须从 Secret Manager 注入 SIQ_AS_TASK_SIGNING_KEY_SEED")

    task_signing_key_file = None
    if dev_mode and not task_signing_key_seed:
        configured_file = os.getenv("SIQ_AS_SIGNING_KEY_FILE")
        if configured_file:
            task_signing_key_file = str(Path(configured_file).expanduser().resolve())
        else:
            state_home = Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local" / "state"))
            task_signing_key_file = str((state_home / "siq-agent-security" / "signing-key.seed").resolve())

    cors_origins = tuple(
        origin.strip().rstrip("/")
        for origin in os.getenv("SIQ_AS_CORS_ORIGINS", "").split(",")
        if origin.strip()
    )
    if not dev_mode:
        for origin in cors_origins:
            parsed = urlparse(origin)
            host = parsed.hostname or ""
            try:
                _ = parsed.port  # 显式触发端口解析校验（非法端口抛 ValueError）
            except ValueError as exc:
                raise RuntimeError(f"SIQ_AS_CORS_ORIGINS 包含无效端口: {origin}") from exc
            try:
                loopback = host.lower() == "localhost" or ip_address(host).is_loopback
            except ValueError:
                loopback = host.lower() == "localhost"
            if (
                origin == "*"
                or not host
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in ("", "/")
                or parsed.params
                or parsed.query
                or parsed.fragment
                or (parsed.scheme != "https" and not (parsed.scheme == "http" and loopback))
            ):
                raise RuntimeError(f"SIQ_AS_CORS_ORIGINS 包含不安全来源: {origin}")

    return Settings(
        database_url=database_url,
        dev_mode=dev_mode,
        oidc_jwks_url=oidc_jwks_url,
        oidc_issuer=os.getenv("SIQ_AS_OIDC_ISSUER"),
        jwt_audience=os.getenv("SIQ_AS_JWT_AUDIENCE", "siq-agent-security"),
        allow_sqlite=allow_sqlite,
        enrollment_ttl_seconds=int(os.getenv("SIQ_AS_ENROLLMENT_TTL_SECONDS", "900")),
        edge_task_ttl_seconds=int(os.getenv("SIQ_AS_EDGE_TASK_TTL_SECONDS", "3600")),
        heartbeat_stale_seconds=int(os.getenv("SIQ_AS_HEARTBEAT_STALE_SECONDS", "300")),
        scan_quota_per_tenant=int(os.getenv("SIQ_AS_SCAN_QUOTA_PER_TENANT", "50")),
        task_signing_key_seed=task_signing_key_seed,
        task_signing_key_file=task_signing_key_file,
        cors_origins=cors_origins,
    )
