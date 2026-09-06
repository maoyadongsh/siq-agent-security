"""审计查询路由（设计文档 §24）。

不变量：审计只读、租户隔离、游标分页、摘要字段已脱敏。
DEV13-D：limit+1 探测截断；响应头声明 returned/truncated/next_cursor，禁止用本页条数冒充全量。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.list_meta import apply_list_meta, clamp_limit, take_page
from app.models import AuditEvent
from app.schemas import AuditEventOut
from app.security import Identity, require_permission

router = APIRouter(tags=["audit"])


def _audit_cursor(row: AuditEvent) -> str:
    return f"{row.created_at.isoformat()}|{row.id}"


@router.get("/api/v1/audit-events", response_model=list[AuditEventOut])
def list_audit_events(
    response: Response,
    actor_id: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    cursor: str | None = None,  # 形如 "<created_at_iso>|<event_id>"
    limit: int = 50,
    include_total: bool = False,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("audit:read")),
):
    query = select(AuditEvent).where(AuditEvent.tenant_id == identity.tenant_id)
    if actor_id:
        query = query.where(AuditEvent.actor_id == actor_id)
    if action:
        query = query.where(AuditEvent.action == action)
    if resource_type:
        query = query.where(AuditEvent.resource_type == resource_type)
    if cursor:
        try:
            created_iso, event_id = cursor.split("|", 1)
            cursor_time = datetime.fromisoformat(created_iso)
            query = query.where(
                (AuditEvent.created_at < cursor_time)
                | ((AuditEvent.created_at == cursor_time) & (AuditEvent.id > event_id))
            )
        except ValueError:
            query = query.where(AuditEvent.id > cursor)

    page_limit = clamp_limit(limit)
    rows = list(
        session.scalars(
            query.order_by(AuditEvent.created_at.desc(), AuditEvent.id).limit(page_limit + 1)
        )
    )
    page, truncated = take_page(rows, limit=page_limit)
    next_cursor = _audit_cursor(page[-1]) if truncated and page else None

    total: int | None = None
    if include_total:
        count_q = select(func.count()).select_from(AuditEvent).where(
            AuditEvent.tenant_id == identity.tenant_id
        )
        if actor_id:
            count_q = count_q.where(AuditEvent.actor_id == actor_id)
        if action:
            count_q = count_q.where(AuditEvent.action == action)
        if resource_type:
            count_q = count_q.where(AuditEvent.resource_type == resource_type)
        total = int(session.scalar(count_q) or 0)

    apply_list_meta(
        response,
        limit=page_limit,
        returned=len(page),
        truncated=truncated,
        next_cursor=next_cursor,
        total=total,
    )
    return page
