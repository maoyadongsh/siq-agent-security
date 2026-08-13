"""审计查询路由（设计文档 §24）。

不变量：审计只读、租户隔离、游标分页、摘要字段已脱敏。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AuditEvent
from app.schemas import AuditEventOut
from app.security import Identity, require_permission

router = APIRouter(tags=["audit"])


@router.get("/api/v1/audit-events", response_model=list[AuditEventOut])
def list_audit_events(
    actor_id: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    cursor: str | None = None,  # 形如 "<created_at_iso>|<event_id>"
    limit: int = 50,
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
        from datetime import datetime

        try:
            created_iso, event_id = cursor.split("|", 1)
            cursor_time = datetime.fromisoformat(created_iso)
            query = query.where(
                (AuditEvent.created_at < cursor_time)
                | ((AuditEvent.created_at == cursor_time) & (AuditEvent.id > event_id))
            )
        except ValueError:
            query = query.where(AuditEvent.id > cursor)
    return list(
        session.scalars(query.order_by(AuditEvent.created_at.desc(), AuditEvent.id).limit(min(limit, 200)))
    )
