"""Outbox 数据库领取/租约（DEV12-B）。

语义：至少一次投递；claim 事务在网络发送前结束；按 lease_owner+revision 确认。
不宣称 exactly-once；多副本真实 PG SKIP LOCKED 证明不在本模块默认路径。
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.models import OutboxEvent, utcnow

DEFAULT_LEASE_SECONDS = 30
DEFAULT_MAX_ATTEMPTS = 8
DEFAULT_BATCH = 50


def worker_instance_id() -> str:
    explicit = os.getenv("SIQ_AS_WORKER_ID", "").strip()
    if explicit:
        return explicit[:128]
    return f"worker-{socket.gethostname()}-{os.getpid()}"[:128]


def outbox_lease_seconds() -> int:
    return max(5, int(os.getenv("SIQ_AS_OUTBOX_LEASE_SECONDS", str(DEFAULT_LEASE_SECONDS))))


def outbox_max_attempts() -> int:
    return max(1, int(os.getenv("SIQ_AS_OUTBOX_MAX_ATTEMPTS", str(DEFAULT_MAX_ATTEMPTS))))


@dataclass(frozen=True)
class ClaimedOutbox:
    id: str
    payload: dict
    lease_revision: int
    attempt: int
    worker_id: str


def claim_outbox_batch(session: Session, *, worker_id: str, limit: int = DEFAULT_BATCH) -> list[ClaimedOutbox]:
    """领取一批未发布事件并提交租约（调用方随后应结束该事务再发网络请求）。"""
    now = utcnow()
    cutoff = now - timedelta(seconds=outbox_lease_seconds())
    candidates = list(
        session.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.published_at.is_(None),
                OutboxEvent.dead_lettered_at.is_(None),
                or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= now),
                or_(OutboxEvent.lease_owner.is_(None), OutboxEvent.leased_at < cutoff),
            )
            .order_by(OutboxEvent.id)
            .limit(limit)
        )
    )
    claimed: list[ClaimedOutbox] = []
    for event in candidates:
        # 乐观占用：仅当仍空闲或租约过期时更新
        rev = int(event.lease_revision or 0) + 1
        attempt = int(event.attempt or 0) + 1
        result = session.execute(
            update(OutboxEvent)
            .where(
                OutboxEvent.id == event.id,
                OutboxEvent.published_at.is_(None),
                OutboxEvent.dead_lettered_at.is_(None),
                or_(OutboxEvent.lease_owner.is_(None), OutboxEvent.leased_at < cutoff),
            )
            .values(
                lease_owner=worker_id,
                leased_at=now,
                lease_revision=rev,
                attempt=attempt,
            )
        )
        if result.rowcount == 1:
            claimed.append(
                ClaimedOutbox(
                    id=event.id,
                    payload=dict(event.payload or {}),
                    lease_revision=rev,
                    attempt=attempt,
                    worker_id=worker_id,
                )
            )
    session.commit()
    return claimed


def confirm_outbox_published(
    session: Session, *, event_id: str, worker_id: str, lease_revision: int
) -> bool:
    """按租约 CAS 确认已发布；慢 webhook 不占用 claim 事务。"""
    now = utcnow()
    result = session.execute(
        update(OutboxEvent)
        .where(
            OutboxEvent.id == event_id,
            OutboxEvent.lease_owner == worker_id,
            OutboxEvent.lease_revision == lease_revision,
            OutboxEvent.published_at.is_(None),
        )
        .values(
            published_at=now,
            lease_owner=None,
            leased_at=None,
            next_attempt_at=None,
        )
    )
    session.commit()
    return result.rowcount == 1


def nack_outbox_publish(
    session: Session, *, event_id: str, worker_id: str, lease_revision: int, attempt: int
) -> None:
    """发送失败：释放租约并指数退避；超过上限进入死信。"""
    now = utcnow()
    max_attempts = outbox_max_attempts()
    if attempt >= max_attempts:
        session.execute(
            update(OutboxEvent)
            .where(
                OutboxEvent.id == event_id,
                OutboxEvent.lease_owner == worker_id,
                OutboxEvent.lease_revision == lease_revision,
                OutboxEvent.published_at.is_(None),
            )
            .values(
                dead_lettered_at=now,
                lease_owner=None,
                leased_at=None,
                next_attempt_at=None,
            )
        )
    else:
        # 退避：2^(attempt-1) 秒，封顶 300s
        delay = min(300, 2 ** max(0, attempt - 1))
        session.execute(
            update(OutboxEvent)
            .where(
                OutboxEvent.id == event_id,
                OutboxEvent.lease_owner == worker_id,
                OutboxEvent.lease_revision == lease_revision,
                OutboxEvent.published_at.is_(None),
            )
            .values(
                lease_owner=None,
                leased_at=None,
                next_attempt_at=now + timedelta(seconds=delay),
            )
        )
    session.commit()
