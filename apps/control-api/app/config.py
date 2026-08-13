"""运行时配置。

生产基线（对齐工作区不变量）：
- PostgreSQL + Alembic 迁移，禁止自动建表；
- dev_mode 仅显式开发开关（SIQ_AS_DEV=1）才允许 SQLite 与 X-Dev-* 身份头；
- Secret 一律经环境变量/Secret 引用，永不落库明文。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


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
    if database_url.startswith("sqlite") and not allow_sqlite:
        raise RuntimeError("SQLite 仅显式开发模式允许（SIQ_AS_ALLOW_SQLITE=1）")

    oidc_jwks_url = os.getenv("SIQ_AS_OIDC_JWKS_URL") or None
    if not dev_mode and not oidc_jwks_url:
        raise RuntimeError("生产模式必须配置 SIQ_AS_OIDC_JWKS_URL（RS256/JWKS）")

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
    )
