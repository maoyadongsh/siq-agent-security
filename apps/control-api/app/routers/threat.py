"""威胁检测流水线路由（P0-3）：静态扫描 → Finding 落库 → 隔离处置闭环。

安全边界：
- 分析纯静态（app.threat_analysis），绝不执行/导入被分析内容，无模型参与处置；
- 先租户定位（404）后权限（403）；审计与状态变化同事务；
- 命中只存行号/规则 id/片段哈希/截断摘要，原始内容不入库、不进审计/outbox。
"""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AgentAsset, Finding, QuarantineCase, utcnow
from app.outbox import audit, emit_event
from app.schemas import (
    QuarantineCaseOut,
    QuarantineReleaseRequest,
    ThreatScanOut,
    ThreatScanRequest,
)
from app.security import Identity, ensure_permission, get_identity
from app.threat_analysis import ANALYZER_VERSION, analyze

router = APIRouter(tags=["threat"])

# 解码后内容上限 1 MiB：防内存放大与超大样本拖垮请求
MAX_CONTENT_BYTES = 1024 * 1024

_SEVERE = ("critical", "high")


@router.post("/api/v1/assets/{asset_id}/threat-scan", response_model=ThreatScanOut)
def threat_scan(
    asset_id: str,
    body: ThreatScanRequest,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    # 跨租户/不存在统一 404（先定位后权限，§21.1 不变量 #1）
    asset = session.scalar(
        select(AgentAsset).where(AgentAsset.id == asset_id, AgentAsset.tenant_id == identity.tenant_id)
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="not_found")
    ensure_permission(identity, "finding:manage")

    if body.encoding == "base64":
        try:
            raw = base64.b64decode(body.content, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="invalid_content_encoding") from None
    else:
        raw = body.content.encode("utf-8")
    if len(raw) > MAX_CONTENT_BYTES:
        raise HTTPException(status_code=422, detail="content_too_large")

    result = analyze(raw, filename=body.filename)

    now = utcnow()
    findings: list[Finding] = []
    for match in result.matches:
        record = match.to_record()
        # 去重：同 asset 同 rule_id 且 status=open 的既有 Finding 更新而非重复建行
        existing = session.scalar(
            select(Finding).where(
                Finding.tenant_id == identity.tenant_id,
                Finding.asset_id == asset.id,
                Finding.rule_id == match.rule_id,
                Finding.domain == "threat",
                Finding.status == "open",
            )
        )
        if existing is not None:
            existing.last_seen_at = now
            existing.matches = [record]
            existing.confidence = match.confidence
            existing.analyzer_version = ANALYZER_VERSION
            if body.evidence_ids:
                existing.evidence_ids = sorted(set(existing.evidence_ids) | set(body.evidence_ids))
            findings.append(existing)
            continue
        finding = Finding(
            tenant_id=identity.tenant_id,
            rule_id=match.rule_id,
            rule_version=1,
            severity=match.severity,
            domain="threat",
            asset_id=asset.id,
            evidence_ids=list(body.evidence_ids),
            impact=match.impact,
            remediation=match.remediation,
            status="open",
            analyzer_version=ANALYZER_VERSION,
            confidence=match.confidence,
            matches=[record],
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(finding)
        session.flush()  # finding.id 为 insert 期默认，隔离单需要真实 ID
        findings.append(finding)

    rule_ids = [m.rule_id for m in result.matches]

    # 任一 critical/high 命中且该 asset 无 quarantined 隔离单 → 创建隔离
    quarantine: QuarantineCase | None = session.scalar(
        select(QuarantineCase).where(
            QuarantineCase.tenant_id == identity.tenant_id,
            QuarantineCase.asset_id == asset.id,
            QuarantineCase.status == "quarantined",
        )
    )
    if any(m.severity in _SEVERE for m in result.matches) and quarantine is None:
        severe_ids = {m.rule_id for m in result.matches if m.severity in _SEVERE}
        trigger = next(f for f in findings if f.rule_id in severe_ids)
        quarantine = QuarantineCase(
            tenant_id=identity.tenant_id,
            asset_id=asset.id,
            finding_id=trigger.id,
            evidence_ids=list(body.evidence_ids),
            reason=f"threat-scan hit rules: {', '.join(rule_ids)}",
            status="quarantined",
            created_by=identity.actor_id,
            created_at=now,
        )
        session.add(quarantine)
        session.flush()
        audit(
            session,
            identity.tenant_id,
            identity.identity_type,
            identity.actor_id,
            "quarantine.create",
            "quarantine_case",
            resource_id=quarantine.id,
            summary={"asset_id": asset.id, "rule_ids": rule_ids},
        )
        emit_event(
            session,
            identity.tenant_id,
            "threat.quarantine.created.v1",
            {
                "quarantine_case_id": quarantine.id,
                "asset_id": asset.id,
                "finding_id": trigger.id,
                "rule_ids": rule_ids,
                "content_sha256": result.sha256,
            },
            resource_ref=quarantine.id,
        )

    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "threat.scan",
        "agent_asset",
        resource_id=asset.id,
        summary={
            "content_sha256": result.sha256,
            "detected_type": result.detected_type,
            "analyzer_version": ANALYZER_VERSION,
            "match_count": len(result.matches),
            "rule_ids": rule_ids,
        },
    )
    emit_event(
        session,
        identity.tenant_id,
        "threat.scan.completed.v1",
        {
            "asset_id": asset.id,
            "content_sha256": result.sha256,
            "detected_type": result.detected_type,
            "analyzer_version": ANALYZER_VERSION,
            "match_count": len(result.matches),
            "rule_ids": rule_ids,
            "quarantine_case_id": quarantine.id if quarantine else None,
        },
        resource_ref=asset.id,
    )
    session.commit()

    return ThreatScanOut(
        asset_id=asset.id,
        content_sha256=result.sha256,
        detected_type=result.detected_type,
        analyzer_version=ANALYZER_VERSION,
        match_count=len(result.matches),
        findings=[f for f in findings],
        quarantine_case=quarantine,
    )


@router.get("/api/v1/quarantine-cases", response_model=list[QuarantineCaseOut])
def list_quarantine_cases(
    status: str | None = None,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    ensure_permission(identity, "agent:read")
    query = (
        select(QuarantineCase)
        .where(QuarantineCase.tenant_id == identity.tenant_id)
        .order_by(QuarantineCase.created_at.desc(), QuarantineCase.id)
    )
    if status:
        query = query.where(QuarantineCase.status == status)
    return list(session.scalars(query.limit(200)))


@router.post("/api/v1/quarantine-cases/{case_id}/release", response_model=QuarantineCaseOut)
def release_quarantine_case(
    case_id: str,
    body: QuarantineReleaseRequest,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    case = session.scalar(
        select(QuarantineCase).where(
            QuarantineCase.id == case_id, QuarantineCase.tenant_id == identity.tenant_id
        )
    )
    if case is None:
        raise HTTPException(status_code=404, detail="not_found")
    ensure_permission(identity, "finding:manage")
    if case.status != "quarantined":
        raise HTTPException(status_code=409, detail="invalid_state")
    case.status = "released"
    case.released_by = identity.actor_id
    case.released_at = utcnow()
    case.release_reason = body.reason
    # 处置分离：释放隔离不自动改动关联 Finding 的状态（Finding 走 acknowledge/resolve 生命周期）
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "quarantine.release",
        "quarantine_case",
        resource_id=case.id,
        summary={"asset_id": case.asset_id, "reason": body.reason},
    )
    emit_event(
        session,
        identity.tenant_id,
        "threat.quarantine.released.v1",
        {
            "quarantine_case_id": case.id,
            "asset_id": case.asset_id,
            "finding_id": case.finding_id,
        },
        resource_ref=case.id,
    )
    session.commit()
    session.refresh(case)
    return case
