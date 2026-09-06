"""后台循环（Phase 2 单进程版）：outbox 发布 + 风险接受到期重开 + 规则引擎。

运行：uv run python -m app.worker [--once]
- outbox 发布：Phase 2 为日志/HTTP Webhook（SIQ_AS_WEBHOOK_URL）；事件 payload 已脱敏；
- reaper：risk_accepted 且 expires_at 过期 → status=open（设计文档 §13.1 末条）；
- 规则循环：每租户 evaluate_all + 幂等 upsert。
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select

from app.config import load_settings
from app.db import init_db, session_scope
from app.models import AgentAsset, ChangeRequest, Finding, Tenant, utcnow
from app.outbox import audit, emit_event
from app.rules import evaluate_all, upsert_findings

logger = logging.getLogger("siq-agent-security.worker")


def publish_outbox(session) -> int:
    """发布未投递事件（DEV12-B：先领取提交，再网络，再 CAS 确认）。

    至少一次投递；不宣称 exactly-once。Webhook 失败则退避重试。
    """
    import httpx

    from app.db import session_scope
    from app.outbox_lease import (
        claim_outbox_batch,
        confirm_outbox_published,
        nack_outbox_publish,
        worker_instance_id,
    )

    webhook = os.getenv("SIQ_AS_WEBHOOK_URL")
    worker_id = worker_instance_id()
    claimed = claim_outbox_batch(session, worker_id=worker_id)
    published = 0
    for item in claimed:
        ok = True
        try:
            if webhook:
                resp = httpx.post(webhook, json=item.payload, timeout=5)
                resp.raise_for_status()
            else:
                logger.info("outbox deliver %s type=%s", item.id, item.payload.get("event_type"))
        except httpx.HTTPError as exc:
            logger.warning("outbox publish failed for %s: %s", item.id, exc)
            ok = False
        # 确认/释放使用独立短事务，避免慢 webhook 长期占用业务会话
        with session_scope() as confirm_session:
            if ok:
                if confirm_outbox_published(
                    confirm_session,
                    event_id=item.id,
                    worker_id=worker_id,
                    lease_revision=item.lease_revision,
                ):
                    published += 1
            else:
                nack_outbox_publish(
                    confirm_session,
                    event_id=item.id,
                    worker_id=item.worker_id,
                    lease_revision=item.lease_revision,
                    attempt=item.attempt,
                )
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
            finding.status = "open"
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
                "agent.finding.reopened.v1",
                {"finding_id": finding.id, "reason": "risk_acceptance_expired"},
                resource_ref=finding.id,
            )
            reopened += 1
    session.commit()
    return reopened


def reopen_expired_dismissals(session) -> int:
    """dismissed 资产到期自动重开为 candidate（设计文档 §10.4：有效期到期行为）。"""
    now = utcnow()
    rows = list(
        session.scalars(
            select(AgentAsset).where(
                AgentAsset.status == "dismissed",
                AgentAsset.dismissed_expires_at.is_not(None),
                AgentAsset.dismissed_expires_at < now,
            )
        )
    )
    reopened = 0
    for asset in rows:
        asset.status = "candidate"
        asset.dismissed_reason = None
        asset.dismissed_expires_at = None
        audit(
            session,
            asset.tenant_id,
            "system",
            "worker",
            "agent.dismissal.expired",
            "agent_asset",
            resource_id=asset.id,
        )
        emit_event(
            session,
            asset.tenant_id,
            "agent.candidate.discovered.v1",
            {"agent_asset_id": asset.id, "reason": "dismissal_expired"},
            resource_ref=asset.id,
        )
        reopened += 1
    session.commit()
    return reopened


def run_drift(session) -> dict:
    """漂移检测循环（§13.3）：仅当配置了执行后端时执行；未配置返回 skipped。"""
    import os

    if os.getenv("SIQ_AS_ENFORCEMENT_BACKEND", "none") == "none":
        return {"skipped": True}
    from app.drift import check_policy_drift, upsert_drift_findings

    tenants = list(session.scalars(select(Tenant).where(Tenant.status == "active")))
    total = {"created": 0, "updated": 0}
    for tenant in tenants:
        results = check_policy_drift(session, tenant.id)
        counts = upsert_drift_findings(session, tenant.id, results)
        total["created"] += counts["created"]
        total["updated"] += counts["updated"]
    session.commit()
    return total


def reap_break_glass_reviews(session) -> int:
    """Break-glass 事后复核：只推进 review_status，不改写业务终态（DEV12-A / M-P4）。

    期限以批准时写入的 review_due_at 为准（源于 approved_at + 合同 TTL），
    不以 created_at 重算。到期自动撤销权限不在本切片默认加入。
    """
    now = utcnow()
    rows = list(
        session.scalars(
            select(ChangeRequest).where(
                ChangeRequest.approval_policy == "break_glass",
                ChangeRequest.review_status == "pending",
                ChangeRequest.review_due_at.is_not(None),
                ChangeRequest.review_due_at <= now,
            )
        )
    )
    due = 0
    for cr in rows:
        business_status = cr.status  # 保留 effective/failed/rolled_back/emergency_applied/...
        cr.review_status = "due"
        audit(
            session,
            cr.tenant_id,
            "system",
            "worker",
            "change.breakglass.review_due",
            "change_request",
            resource_id=cr.id,
            summary={"business_status": business_status, "review_status": "due"},
        )
        emit_event(
            session,
            cr.tenant_id,
            "policy.change.review_due.v1",
            {
                "change_request_id": cr.id,
                "resolution": "review_due",
                "business_status": business_status,
            },
            resource_ref=cr.id,
        )
        due += 1
    session.commit()
    return due


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
        dismissals = reopen_expired_dismissals(session)
        breakglass = reap_break_glass_reviews(session)
        drift = run_drift(session)
        rules = run_rules(session)
    return {
        "published": published,
        "reaped": reaped,
        "dismissals": dismissals,
        "breakglass": breakglass,
        "drift": drift,
        "rules": rules,
    }


def loop(
    interval_seconds: int,
    *,
    max_backoff_seconds: int | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> None:
    """后台循环：周期执行全部子任务（outbox 发布/到期重开/规则/漂移），永不退出（保活）。

    失败退避只影响下一次尝试的时间：interval → 2× → 4× …（封顶 max_backoff_seconds，
    默认 SIQ_AS_WORKER_MAX_BACKOFF_SECONDS=300），成功即复位为 interval。
    退避不改变 outbox 原子语义——发布仍按事件级幂等标记，未发布事件留待后续周期。
    """
    if max_backoff_seconds is None:
        max_backoff_seconds = int(os.getenv("SIQ_AS_WORKER_MAX_BACKOFF_SECONDS", "300"))
    logger.info("worker loop started, interval=%ss, backoff cap=%ss", interval_seconds, max_backoff_seconds)
    consecutive_failures = 0
    while True:
        try:
            summary = once()
            logger.info("cycle: %s", summary)
            consecutive_failures = 0  # 成功即复位退避
            sleep_for = float(interval_seconds)
        except Exception:  # noqa: BLE001 —— 后台循环不得退出，记录后继续
            logger.exception("worker cycle failed")
            consecutive_failures += 1
            sleep_for = min(float(interval_seconds) * (2 ** (consecutive_failures - 1)), float(max_backoff_seconds))
        sleep_fn(sleep_for)


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
