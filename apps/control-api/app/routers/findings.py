"""风险中心路由（设计文档 §13）。

规则引擎 Phase 2 交付；当前支持 Finding 的生命周期管理：
- 风险接受必须带 Owner、原因、到期时间（§13.1 末条：风险接受长期遗忘防护）；
- 到期自动重开由 worker 处理（services/worker，Phase 2）。
"""

from __future__ import annotations

from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AgentAsset, Finding, utcnow
from app.outbox import audit, emit_event
from app.schemas import FindingAcceptRisk, FindingOut
from app.security import Identity, ensure_permission, get_identity, require_permission

router = APIRouter(tags=["findings"])


@router.get("/api/v1/findings", response_model=list[FindingOut])
def list_findings(
    severity: str | None = None,
    status_filter: str | None = None,
    asset_id: str | None = None,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    if asset_id:
        # 越权资产 ID 直接 404，不泄露其他租户数据（先定位后权限）
        asset = session.scalar(
            select(AgentAsset).where(AgentAsset.id == asset_id, AgentAsset.tenant_id == identity.tenant_id)
        )
        if asset is None:
            raise HTTPException(status_code=404, detail="not_found")
    ensure_permission(identity, "agent:read")
    query = select(Finding).where(Finding.tenant_id == identity.tenant_id)
    if severity:
        query = query.where(Finding.severity == severity)
    if status_filter:
        query = query.where(Finding.status == status_filter)
    if asset_id:
        query = query.where(Finding.asset_id == asset_id)
    return list(session.scalars(query.order_by(Finding.severity, Finding.first_seen_at.desc()).limit(200)))


@router.post("/api/v1/findings/{finding_id}/accept-risk", response_model=FindingOut)
def accept_risk(
    finding_id: str,
    body: FindingAcceptRisk,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("finding:manage")),
):
    finding = session.scalar(
        select(Finding).where(Finding.id == finding_id, Finding.tenant_id == identity.tenant_id)
    )
    if finding is None:
        raise HTTPException(status_code=404, detail="not_found")
    if body.expires_at.astimezone(UTC).replace(tzinfo=None) < utcnow():
        raise HTTPException(status_code=422, detail="expiry_in_past")
    finding.status = "risk_accepted"
    finding.owner_user_id = body.owner_user_id
    finding.risk_acceptance = {
        "reason": body.reason,
        "accepted_by": identity.actor_id,
        "expires_at": body.expires_at.isoformat(),
    }
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "finding.accept_risk",
        "finding",
        resource_id=finding.id,
        summary={"expires_at": body.expires_at.isoformat()},
    )
    emit_event(
        session,
        identity.tenant_id,
        "agent.finding.resolved.v1",
        {"finding_id": finding.id, "resolution": "risk_accepted"},
        resource_ref=finding.id,
    )
    session.commit()
    session.refresh(finding)
    return finding
