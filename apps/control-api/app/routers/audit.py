"""审计查询路由（设计文档 §24）。

不变量：审计只读、租户隔离、游标分页、摘要字段已脱敏。
DEV13-D：limit+1 探测截断；响应头声明 returned/truncated/next_cursor，禁止用本页条数冒充全量。
ENT-019-AUDIT-QUERY：request_id/resource_id/actor_type/decision 精确过滤（enterprise-audit-query.v1）。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
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
    # 新增精确过滤：非空严格相等；空串/超长由 Query 约束直接 422（enterprise-audit-query.v1）。
    request_id: str | None = Query(default=None, min_length=1, max_length=64),
    resource_id: str | None = Query(default=None, min_length=1, max_length=64),
    actor_type: str | None = Query(default=None, min_length=1, max_length=16),
    decision: str | None = Query(default=None, min_length=1, max_length=16),
    cursor: str | None = None,  # 形如 "<created_at_iso>|<event_id>"
    limit: int = 50,
    include_total: bool = False,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("audit:read")),
):
    # 列表与总数共用同一组过滤条件；cursor 只作用于翻页，不进入总数口径。
    filters = [AuditEvent.tenant_id == identity.tenant_id]
    if actor_id:
        filters.append(AuditEvent.actor_id == actor_id)
    if action:
        filters.append(AuditEvent.action == action)
    if resource_type:
        filters.append(AuditEvent.resource_type == resource_type)
    if request_id is not None:
        filters.append(AuditEvent.request_id == request_id)
    if resource_id is not None:
        filters.append(AuditEvent.resource_id == resource_id)
    if actor_type is not None:
        filters.append(AuditEvent.actor_type == actor_type)
    if decision is not None:
        filters.append(AuditEvent.decision == decision)

    query = select(AuditEvent).where(*filters)
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
        count_q = select(func.count()).select_from(AuditEvent).where(*filters)
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
