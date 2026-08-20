"""威胁检测流水线路由（P0-3）：静态扫描 → Finding 落库 → 隔离处置闭环。

安全边界：
- 分析纯静态（app.threat_analysis），绝不执行/导入被分析内容，无模型参与处置；
- 先租户定位（404）后权限（403）；审计与状态变化同事务；
- 命中只存行号/规则 id/片段哈希/截断摘要，原始内容不入库、不进审计/outbox。
"""

from __future__ import annotations

import base64
import binascii
import hashlib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AgentAsset, Evidence, Finding, QuarantineCase, RuntimeBinding, utcnow
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

# 同一 open Finding 重复扫描命中同一规则时，matches 保留的历史命中条数上限
# （B-1）：旧实现 `existing.matches = [record]` 直接整列覆盖，每次重扫都会
# 丢弃此前的命中记录——取证与"这条规则到底稳定命中过几次/最早何时开始"的
# 时间线全部丢失。改为追加并保留最近 N 条，兼顾取证连续性与行大小上界。
MAX_MATCH_HISTORY = 20

_SEVERE = ("critical", "high")

# 自动隔离置信度门槛（R-8）：critical/high 命中还不足以直接触发自动隔离，
# 必须同时达到该置信度才会联动隔离 + 吊销 RuntimeBinding + 阻断后续部署
# （见 routers/policies.py 的 QuarantineCase 部署门禁）。
#
# 背景：隔离是一次性的强干预动作，一旦触发就会拦掉该 asset 之后的所有部署，
# 必须人工 release 才能恢复；而当前规则包中恰好存在置信度明显偏低（0.8）
# 且规则本身泛匹配面很宽的高危规则，例如 threat-net-hardcoded-c2 的
# `("IP", port)` 元组正则——这也是任何普通 socket 绑定代码
# （如 `sock.bind(("0.0.0.0", 8080))`）的合法写法，并非硬编码 C2 特有语法。
# 单条这类误报就会真的拦掉生产部署，风险与收益不成比例。
#
# 0.85 门槛精确排除了这一类低置信度规则，同时不影响任何其他 critical/high
# 规则（credential 窃取、持久化、反弹 shell、混淆执行、prompt injection 等
# 均 ≥ 0.85）——命中依然会记为 Finding 供人工复核，只是不再自动触发隔离。
AUTO_QUARANTINE_MIN_CONFIDENCE = 0.85


def _ensure_scan_permission(identity: Identity, asset: AgentAsset) -> None:
    """扫描权限（R-4b）：finding:scan（security_admin）保留租户级全量扫描能力，
    这是集中式安全团队管理全租户风险面所需的既定设计，不因本次改动收窄；
    在此之上新增一条范围更小的自服务通道——持有 agent:confirm（agent_owner）
    且确为该 asset 的 owner_user_id 本人，可以自行扫描自己名下的资产，无需
    被授予租户级 finding:scan（最小权限：owner 不该拿到能扫全租户资产的权限）。
    两者均不满足则 403（对象已在调用处先做过跨租户 404 判定）。
    """
    if identity.has_permission("finding:scan"):
        return
    if identity.has_permission("agent:confirm") and asset.owner_user_id == identity.actor_id:
        return
    raise HTTPException(status_code=403, detail="forbidden")


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
    # R-4b：扫描入口独立权限点 finding:scan，与 finding:manage（Finding 生命
    # 周期管理：acknowledge/resolve/accept-risk）分离，对齐已修复的释放侧
    # SoD（quarantine:release 独立于 finding:manage）。触发扫描是会带来强
    # 副作用的高风险动作（可联动自动隔离 + 吊销 RuntimeBinding + 阻断部署），
    # 不应与"处理既有 Finding"这类日常分诊操作共用同一权限点。此外允许
    # asset owner 在不持有租户级 finding:scan 时自扫自己名下资产（见
    # _ensure_scan_permission），覆盖"个人开发者自查自己接的 Agent"场景。
    _ensure_scan_permission(identity, asset)

    if body.encoding == "base64":
        try:
            raw = base64.b64decode(body.content, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="invalid_content_encoding") from None
    else:
        raw = body.content.encode("utf-8")
    if len(raw) > MAX_CONTENT_BYTES:
        raise HTTPException(status_code=422, detail="content_too_large")

    raw_hash = hashlib.sha256(raw).hexdigest()
    if asset.artifact_digest and asset.artifact_digest != raw_hash:
        is_bound = False
        if body.evidence_ids:
            ev_match = session.scalar(
                select(Evidence.id).where(
                    Evidence.tenant_id == identity.tenant_id,
                    Evidence.evidence_id.in_(body.evidence_ids),
                    Evidence.content_hash == raw_hash,
                ).limit(1)
            )
            if ev_match:
                is_bound = True
        if not is_bound:
            raise HTTPException(
                status_code=422,
                detail="content_not_bound: content hash does not match asset artifact_digest or evidence",
            )
    elif not asset.artifact_digest:
        asset.artifact_digest = raw_hash

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
            # B-1：追加而非整列覆盖，保留最近 MAX_MATCH_HISTORY 条命中历史
            # （重新赋值新列表对象，确保 SQLAlchemy JSON 字段变更被正确跟踪）
            existing.matches = [*(existing.matches or []), record][-MAX_MATCH_HISTORY:]
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
        emit_event(
            session,
            identity.tenant_id,
            "agent.finding.opened.v1",
            {
                "finding_id": finding.id,
                "asset_id": asset.id,
                "rule_id": match.rule_id,
                "severity": match.severity,
                "domain": "threat",
            },
            resource_ref=finding.id,
        )

    rule_ids = [m.rule_id for m in result.matches]

    # 任一 critical/high 且置信度达标的命中，且该 asset 无 quarantined 隔离单
    # → 创建隔离（R-8：加置信度门槛，避免单条低置信度规则误伤生产部署）
    quarantine: QuarantineCase | None = session.scalar(
        select(QuarantineCase).where(
            QuarantineCase.tenant_id == identity.tenant_id,
            QuarantineCase.asset_id == asset.id,
            QuarantineCase.status == "quarantined",
        )
    )
    auto_quarantine_matches = [
        m
        for m in result.matches
        if m.severity in _SEVERE and m.confidence >= AUTO_QUARANTINE_MIN_CONFIDENCE
    ]
    if auto_quarantine_matches and quarantine is None:
        severe_ids = sorted({m.rule_id for m in auto_quarantine_matches})
        trigger = next(f for f in findings if f.rule_id in severe_ids)
        quarantine = QuarantineCase(
            tenant_id=identity.tenant_id,
            asset_id=asset.id,
            finding_id=trigger.id,
            evidence_ids=list(body.evidence_ids),
            reason=f"threat-scan auto-quarantine triggered by rules: {', '.join(severe_ids)}",
            status="quarantined",
            created_by=identity.actor_id,
            created_at=now,
        )
        session.add(quarantine)
        session.flush()

        # 联动：自动吊销该资产关联的所有 active RuntimeBinding（防已隔离资产继续部署）
        active_bindings = session.scalars(
            select(RuntimeBinding).where(
                RuntimeBinding.tenant_id == identity.tenant_id,
                RuntimeBinding.asset_id == asset.id,
                RuntimeBinding.status == "active",
            )
        ).all()
        for b in active_bindings:
            b.status = "revoked"
            b.revoked_at = now
            emit_event(
                session,
                identity.tenant_id,
                "runtime_binding.revoked.v1",
                {"binding_id": b.id, "asset_id": asset.id, "reason": "auto_quarantined"},
                environment_id=b.environment_id,
                resource_ref=b.id,
            )

        audit(
            session,
            identity.tenant_id,
            identity.identity_type,
            identity.actor_id,
            "quarantine.create",
            "quarantine_case",
            resource_id=quarantine.id,
            summary={"asset_id": asset.id, "rule_ids": severe_ids},
        )
        emit_event(
            session,
            identity.tenant_id,
            "threat.quarantine.created.v1",
            {
                "quarantine_case_id": quarantine.id,
                "asset_id": asset.id,
                "finding_id": trigger.id,
                "rule_ids": severe_ids,
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
    ensure_permission(identity, "quarantine:release")
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
