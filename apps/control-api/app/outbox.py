"""Transactional Outbox 与审计写入（设计文档 §23.1 / §24.2）。

不变量：
- 审计与状态变化同事务（设计文档 §23.2：审计写入失败 = 高风险写操作失败关闭）；
- Outbox 事件 payload 只含脱敏摘要（标识/数量/哈希），禁止原始敏感内容；
- 事件信封对齐 packages/contracts/event-envelope.schema.json。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import AuditEvent, OutboxEvent


def emit_event(
    session: Session,
    tenant_id: str,
    event_type: str,
    payload: dict,
    *,
    environment_id: str | None = None,
    actor: dict | None = None,
    resource_ref: str | None = None,
    request_id: str | None = None,
) -> OutboxEvent:
    """在调用方事务内追加 outbox 事件（不自行提交）。"""
    envelope = {
        "event_id": f"evt_{uuid.uuid4().hex[:20]}",
        "event_type": event_type,
        "occurred_at": datetime.now(UTC).isoformat(),
        "tenant_id": tenant_id,
        "environment_id": environment_id,
        "actor": actor,
        "resource_ref": resource_ref,
        "request_id": request_id,
        "schema_version": 1,
        "payload": payload,
    }
    event = OutboxEvent(
        tenant_id=tenant_id, event_type=event_type, payload=envelope, occurred_at=datetime.now(UTC)
    )
    session.add(event)
    return event


def audit(
    session: Session,
    tenant_id: str,
    actor_type: str,
    actor_id: str,
    action: str,
    resource_type: str,
    *,
    decision: str = "allow",
    resource_id: str | None = None,
    request_id: str | None = None,
    summary: dict | None = None,
) -> None:
    """追加审计行。summary 只允许标识/数量/哈希类字段。"""
    session.add(
        AuditEvent(
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            decision=decision,
            request_id=request_id,
            summary=summary or {},
        )
    )
