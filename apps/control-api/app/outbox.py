"""Transactional Outbox 与审计写入（设计文档 §23.1 / §24.2）。

不变量：
- 审计与状态变化同事务（设计文档 §23.2：审计写入失败 = 高风险写操作失败关闭）；
- Outbox 事件 payload 只含脱敏摘要（标识/数量/哈希），禁止原始敏感内容；
- 事件信封对齐 packages/contracts/event-envelope.schema.json；
- DEV11 / R05：payload 中的 *_id / 常见对象引用与 resource_ref 不得为 null/空
  （调用方须在 emit 前应用层赋 ID 或 flush）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import AuditEvent, OutboxEvent, new_id

# Keys that must not be null/empty when present in an outbox payload.
# Object / resource references only (not rule_id / free-form *\_id labels).
REQUIRED_REF_KEYS = frozenset(
    {
        "environment_id",
        "change_request_id",
        "finding_id",
        "task_id",
        "deployment_id",
        "policy_id",
        "asset_id",
        "agent_asset_id",
        "binding_id",
        "quarantine_id",
        "agent_id",
        "instance_id",
        "agent_instance_id",
        "classification_run_id",
    }
)
_REQUIRED_REF_KEYS = REQUIRED_REF_KEYS


def _reject_null_refs(payload: dict, resource_ref: str | None) -> None:
    if resource_ref is not None and not str(resource_ref).strip():
        raise ValueError("emit_event: resource_ref must be non-empty when provided")
    for key, value in payload.items():
        if key not in _REQUIRED_REF_KEYS:
            continue
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(
                f"emit_event: payload[{key!r}] must be a non-empty object id "
                "(assign id or flush before emit)"
            )


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
    _reject_null_refs(payload, resource_ref)
    if environment_id is not None and not str(environment_id).strip():
        raise ValueError("emit_event: environment_id must be non-empty when provided")
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
    """追加审计行。summary 只允许标识/数量/哈希类字段。

    审计主键由服务端生成；request_id 仅 correlation（须已规范化）。
    """
    if resource_id is not None and not str(resource_id).strip():
        raise ValueError("audit: resource_id must be non-empty when provided")
    if request_id is not None and not str(request_id).strip():
        raise ValueError("audit: request_id must be non-empty when provided")
    session.add(
        AuditEvent(
            id=new_id("aud"),
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
