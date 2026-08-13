"""后台循环（Phase 2 单进程版）：outbox 发布 + 风险接受到期重开 + 规则引擎。

运行：uv run python -m app.worker [--once]
- outbox 发布：Phase 2 为日志/HTTP Webhook（SIQ_AS_WEBHOOK_URL）；事件 payload 已脱敏；
- reaper：risk_accepted 且 expires_at 过期 → status=expired（设计文档 §13.1 末条）；
- 规则循环：每租户 evaluate_all + 幂等 upsert。
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime

from sqlalchemy import select

from app.config import load_settings
from app.db import init_db, session_scope
from app.models import Finding, OutboxEvent, Tenant, utcnow
from app.outbox import audit, emit_event
from app.rules import evaluate_all, upsert_findings

logger = logging.getLogger("siq-agent-security.worker")


def publish_outbox(session) -> int:
    """发布未投递事件；Phase 2 为可选 Webhook + 日志兜底，保证幂等标记。"""
    import httpx

    webhook = os.getenv("SIQ_AS_WEBHOOK_URL")
    rows = list(
        session.scalars(
            select(OutboxEvent).where(OutboxEvent.published_at.is_(None)).order_by(OutboxEvent.id).limit(50)
        )
    )
    published = 0
    for event in rows:
        try:
            if webhook:
                resp = httpx.post(webhook, json=event.payload, timeout=5)
                resp.raise_for_status()
        except httpx.HTTPError as exc:  # 失败保留未发布，下轮重试
            logger.warning("outbox publish failed for %s: %s", event.id, exc)
            continue
        event.published_at = utcnow()
        published += 1
    session.commit()
    return published


def reap_expired_risk_acceptance(session) -> int:
    """风险接受到期自动重开（§13.1：必填 Owner/原因/到期时间；到期自动重开并通知）。"""
    now = utcnow()
    rows = list(
        session.scalars(
            select(Finding).where(
                Finding.status == "risk_accepted",
                Finding.risk_acceptance.is_not(None),
            )
        )
    )
    reopened = 0
    for finding in rows:
        expires_raw = (finding.risk_acceptance or {}).get("expires_at")
        if not expires_raw:
            continue
        try:
            expires_at = datetime.fromisoformat(str(expires_raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if expires_at.tzinfo is not None:
            expires_at = expires_at.replace(tzinfo=None)
        if expires_at < now:
            finding.status = "expired"
            audit(
                session,
                finding.tenant_id,
                "system",
                "worker",
                "finding.risk_acceptance.expired",
                "finding",
                resource_id=finding.id,
                summary={"rule_id": finding.rule_id},
            )
            emit_event(
                session,
                finding.tenant_id,
                "agent.finding.resolved.v1",
                {"finding_id": finding.id, "resolution": "risk_acceptance_expired"},
                resource_ref=finding.id,
            )
            reopened += 1
    session.commit()
    return reopened


def run_rules(session) -> dict:
    tenants = list(session.scalars(select(Tenant).where(Tenant.status == "active")))
    total = {"created": 0, "updated": 0}
    for tenant in tenants:
        results = evaluate_all(session, tenant.id)
        counts = upsert_findings(session, tenant.id, results)
        total["created"] += counts["created"]
        total["updated"] += counts["updated"]
        if counts["created"]:
            logger.info("tenant %s: rules created=%s updated=%s", tenant.id, counts["created"], counts["updated"])
    session.commit()
    return total


def once() -> dict:
    with session_scope() as session:
        published = publish_outbox(session)
        reaped = reap_expired_risk_acceptance(session)
        rules = run_rules(session)
    return {"published": published, "reaped": reaped, "rules": rules}


def loop(interval_seconds: int) -> None:
    logger.info("worker loop started, interval=%ss", interval_seconds)
    while True:
        try:
            summary = once()
            logger.info("cycle: %s", summary)
        except Exception:  # noqa: BLE001 —— 后台循环不得退出，记录后继续
            logger.exception("worker cycle failed")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    init_db(settings)
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=int, default=int(os.getenv("SIQ_AS_WORKER_INTERVAL_SECONDS", "60")))
    args = parser.parse_args()
    if args.once:
        print(once())
    else:
        loop(args.interval)
