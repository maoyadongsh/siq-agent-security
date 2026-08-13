"""Control Plane API 入口（模块化单体，设计文档 §9.1）。

启动约束：
- 生产：PostgreSQL + Alembic 迁移（禁止 create_all）；
- dev（SIQ_AS_DEV=1）：允许 SQLite 与 create_all，仅本地开发/测试。
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import load_settings
from app.db import Base, get_session, init_db, session_scope
from app.models import Tenant
from app.routers import audit as audit_router
from app.routers import environments, findings, inventory, policies
from app.security import Identity, get_identity

logger = logging.getLogger("siq-agent-security")

settings = load_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings)
    if settings.dev_mode:
        from app.db import get_engine

        Base.metadata.create_all(bind=get_engine())
        with session_scope() as session:
            if session.query(Tenant).count() == 0:
                session.add(Tenant(id="dev-tenant", name="Development Tenant"))
                session.commit()
        logger.warning("dev 模式：自动建表 + dev-tenant 种子数据（仅限本地开发）")
    yield


app = FastAPI(
    title="SIQ Agent Security Control Plane",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS：dev 模式全放开（本地控制台可能从任意本机网卡 IP 打开）；
# 生产保持显式白名单（身份仍由 OIDC 验证，dev 身份头生产不生效）。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.dev_mode else ["http://localhost:19876", "http://127.0.0.1:19876"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get(settings.request_id_header) or f"req-{uuid.uuid4().hex[:12]}"
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers[settings.request_id_header] = request_id
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/overview")
def overview(
    session=Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """控制台总览统计（§20.1）。只读、租户隔离。"""
    from sqlalchemy import func

    from app.models import AgentAsset, EdgeAgent, Environment, Finding

    def _count(model, *where):
        return session.scalar(select(func.count(model.id)).where(model.tenant_id == identity.tenant_id, *where)) or 0

    return {
        "agents": _count(AgentAsset, AgentAsset.status.in_(["confirmed", "managed"])),
        "candidates": _count(AgentAsset, AgentAsset.status.in_(["candidate", "needs_review"])),
        "open_findings": _count(Finding, Finding.status.in_(["open", "acknowledged"])),
        "critical_findings": _count(
            Finding, Finding.status.in_(["open", "acknowledged"]), Finding.severity == "critical"
        ),
        "environments": _count(Environment),
        # EdgeAgent 无 tenant_id（经 environment 归属租户），走子查询
        "edges_online": session.scalar(
            select(func.count(EdgeAgent.id)).where(
                EdgeAgent.environment_id.in_(
                    select(Environment.id).where(Environment.tenant_id == identity.tenant_id)
                ),
                EdgeAgent.revoked_at.is_(None),
            )
        )
        or 0,
        "policies": 0,  # Phase 3 Adapter 联调后接 DesiredPolicy 计数
    }


for router in (
    environments.router,
    inventory.router,
    findings.router,
    policies.router,
    audit_router.router,
):
    app.include_router(router)
