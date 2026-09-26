"""Control Plane API 入口（模块化单体，设计文档 §9.1）。

启动约束：
- 生产：PostgreSQL + Alembic 迁移（禁止 create_all）；
- dev（SIQ_AS_DEV=1）：允许 SQLite 与 create_all，仅本地开发/测试。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import load_settings
from app.db import Base, get_session, init_db, session_scope
from app.list_meta import EXPOSE_HEADERS as LIST_EXPOSE_HEADERS
from app.models import Tenant
from app.routers import audit as audit_router
from app.routers import (
    bindings,
    change_execution,
    change_review,
    console,
    credential_rotation,
    deployment_batch_draft,
    deployment_batch_execute,
    deployment_batch_result,
    deployment_impact,
    deployment_preview,
    deployment_submission,
    device_lifecycle,
    discovery_origin,
    discovery_schedule_confirmation,
    discovery_schedule_pending,
    discovery_schedules,
    enterprise_connection,
    environments,
    export,
    findings,
    framework_inventory,
    initial_scan,
    install_plans,
    inventory,
    network_revoke_batches,
    network_revoke_proposals,
    policies,
    registration_recovery,
    role_configuration_history,
    role_skill_sources,
    skill_inventory,
    skill_upload,
    threat,
)
from app.security import Identity, ensure_permission, get_identity

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
    else:
        tenant_id = settings.bootstrap_tenant_id
        with session_scope() as session:
            if session.get(Tenant, tenant_id) is None:
                session.add(Tenant(id=tenant_id, name=f"Tenant {tenant_id}"))
                logger.info("已种子控制面租户 %s（对齐 IAM SIQ_DEFAULT_TENANT_ID）", tenant_id)
    yield


app = FastAPI(
    title="SIQ Agent Security Control Plane",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS：dev 模式便于本地联调；生产默认同源（空列表），仅显式安全白名单可放开。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.dev_mode else list(settings.cors_origins),
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=list(LIST_EXPOSE_HEADERS),
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    from app.request_id import normalize_client_request_id

    # 客户端 header 仅 correlation；非法则服务端生成（M-P5c）
    request_id = normalize_client_request_id(request.headers.get(settings.request_id_header))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers[settings.request_id_header] = request_id
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/health")
def api_health():
    """设置页同源探测；无鉴权。路径挂到网关 /api/agent-security/v1/health。"""
    return {"status": "ok"}


@app.get("/api/v1/overview")
def overview(
    session=Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """控制台总览统计（§20.1）。只读、租户隔离。"""
    from datetime import timedelta

    from sqlalchemy import func

    from app.models import AgentAsset, DesiredPolicy, EdgeAgent, Environment, Finding, utcnow

    for permission in ("agent:read", "env:read", "policy:read"):
        ensure_permission(identity, permission)
    now = utcnow()

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
                EdgeAgent.environment_id.in_(select(Environment.id).where(Environment.tenant_id == identity.tenant_id)),
                EdgeAgent.revoked_at.is_(None),
                EdgeAgent.last_seen_at >= now - timedelta(seconds=settings.heartbeat_stale_seconds),
                EdgeAgent.last_seen_at <= now,
            )
        )
        or 0,
        "policies": _count(DesiredPolicy),
    }


for router in (
    change_execution.router,
    deployment_preview.router,
    deployment_impact.router,
    deployment_batch_draft.router,
    deployment_batch_execute.router,
    deployment_batch_result.router,
    deployment_submission.router,
    change_review.router,
    console.router,
    credential_rotation.router,
    environments.router,
    device_lifecycle.router,
    install_plans.router,
    initial_scan.router,
    discovery_schedules.router,
    discovery_schedule_confirmation.router,
    discovery_schedule_pending.router,
    registration_recovery.router,
    inventory.router,
    discovery_origin.router,
    framework_inventory.router,
    enterprise_connection.router,
    skill_inventory.router,
    role_skill_sources.router,
    role_configuration_history.router,
    skill_upload.router,
    findings.router,
    policies.router,
    network_revoke_proposals.router,
    network_revoke_batches.router,
    bindings.router,
    threat.router,
    audit_router.router,
    export.router,
):
    app.include_router(router)
