"""Control Plane API 入口（模块化单体，设计文档 §9.1）。

启动约束：
- 生产：PostgreSQL + Alembic 迁移（禁止 create_all）；
- dev（SIQ_AS_DEV=1）：允许 SQLite 与 create_all，仅本地开发/测试。
"""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import load_settings
from app.db import Base, init_db, session_scope
from app.models import Tenant
from app.routers import audit as audit_router
from app.routers import environments, findings, inventory, policies

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:1361", "http://localhost:5173"],
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


for router in (
    environments.router,
    inventory.router,
    findings.router,
    policies.router,
    audit_router.router,
):
    app.include_router(router)
