"""确定性风险规则引擎 v1（设计文档 §13.1）。

规则只基于权威数据计算 Finding 建议，落库由调用方（worker / 手动触发）执行：
- 每条规则声明规则 ID、严重级别、作用域与证据；
- 幂等 upsert 键：(tenant_id, rule_id, asset_id, resource_ref) + status=open；
- 规则引擎不修改权限、不下发策略。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AgentAsset, Environment, Evidence, Finding, PermissionFact


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    severity: str
    domain: str
    asset_id: str | None
    resource_ref: str | None
    evidence_ids: list
    impact: str
    remediation: str


def _now(session: Session) -> datetime:
    from app.models import utcnow

    return utcnow()


# ---------------------------------------------------------------- 规则实现


def _rule_unowned_confirmed_agent(session: Session, tenant_id: str, now: datetime) -> list[RuleResult]:
    """未登记或无负责人的智能体处于已确认/已纳管状态（§13.1 首条）。"""
    rows = session.scalars(
        select(AgentAsset).where(
            AgentAsset.tenant_id == tenant_id,
            AgentAsset.status.in_(["confirmed", "managed"]),
            AgentAsset.owner_user_id.is_(None),
        )
    )
    return [
        RuleResult(
            rule_id="unowned-confirmed-agent",
            severity="high",
            domain="governance",
            asset_id=a.id,
            resource_ref=None,
            evidence_ids=[],
            impact="已确认/已纳管的智能体缺少负责人，变更与风险无法落实责任归属",
            remediation="在资产详情补充 owner 与所属 System",
        )
        for a in rows
    ]


def _rule_stale_environment(session: Session, tenant_id: str, now: datetime) -> list[RuleResult]:
    """环境心跳过期（Edge 全部失联风险）。"""
    from datetime import timedelta

    from app.config import load_settings

    threshold = now - timedelta(seconds=load_settings().heartbeat_stale_seconds)
    envs = session.scalars(
        select(Environment).where(
            Environment.tenant_id == tenant_id,
            Environment.last_heartbeat_at.is_not(None),
            Environment.last_heartbeat_at < threshold,
        )
    )
    return [
        RuleResult(
            rule_id="stale-environment-heartbeat",
            severity="medium",
            domain="availability",
            asset_id=None,
            resource_ref=f"environment:{e.id}",
            evidence_ids=[],
            impact=f"环境 {e.name} 超过新鲜度阈值无心跳，资产与权限视图可能过期",
            remediation="检查 Edge Agent 状态；确认下线则标记环境停用",
        )
        for e in envs
    ]


def _rule_expired_evidence(session: Session, tenant_id: str, now: datetime) -> list[RuleResult]:
    """证据过期（新鲜度失效）。"""
    rows = session.scalars(
        select(Evidence).where(
            Evidence.tenant_id == tenant_id,
            Evidence.expires_at.is_not(None),
            Evidence.expires_at < now,
        )
    )
    return [
        RuleResult(
            rule_id="expired-evidence",
            severity="info",
            domain="evidence",
            asset_id=None,
            resource_ref=f"evidence:{e.id}",
            evidence_ids=[e.id],
            impact=f"证据 {e.source_locator} 已超过有效期，相关结论不再新鲜",
            remediation="重新采集或延长有效期",
        )
        for e in rows
    ]


def _rule_shared_credential(session: Session, tenant_id: str, now: datetime) -> list[RuleResult]:
    """同一凭据被多个不相关 Agent 共用（§13.1）。"""
    rows = session.execute(
        select(PermissionFact.resource_value, func.count(func.distinct(PermissionFact.subject_id)).label("cnt"))
        .where(
            PermissionFact.tenant_id == tenant_id,
            PermissionFact.domain == "credential",
        )
        .group_by(PermissionFact.resource_value)
        .having(func.count(func.distinct(PermissionFact.subject_id)) > 1)
    )
    return [
        RuleResult(
            rule_id="shared-credential",
            severity="high",
            domain="credential",
            asset_id=None,
            resource_ref=f"credential:{ref}",
            evidence_ids=[],
            impact=f"凭据 {ref} 被 {cnt} 个不同主体共用，吊销与审计无法独立归属",
            remediation="为每个 Agent 签发独立凭据引用",
        )
        for ref, cnt in rows
    ]


def _rule_no_effective_permissions(session: Session, tenant_id: str, now: datetime) -> list[RuleResult]:
    """已纳管资产没有任何 effective 权限事实（unknown 覆盖，§12.2）。"""
    managed = list(
        session.scalars(
            select(AgentAsset).where(
                AgentAsset.tenant_id == tenant_id,
                AgentAsset.status.in_(["confirmed", "managed"]),
            )
        )
    )
    results: list[RuleResult] = []
    for asset in managed:
        count = session.scalar(
            select(func.count(PermissionFact.id)).where(
                PermissionFact.tenant_id == tenant_id,
                PermissionFact.subject_id == asset.id,
                PermissionFact.state == "effective",
            )
        )
        if count == 0:
            results.append(
                RuleResult(
                    rule_id="no-effective-permissions",
                    severity="info",
                    domain="permissions",
                    asset_id=asset.id,
                    resource_ref=None,
                    evidence_ids=[],
                    impact="资产没有任何经权威源解析的有效权限事实，权限视图为 unknown",
                    remediation="接入对应权限域 Resolver 或明确标记 unknown 原因",
                )
            )
    return results


RULES = [
    _rule_unowned_confirmed_agent,
    _rule_stale_environment,
    _rule_expired_evidence,
    _rule_shared_credential,
    _rule_no_effective_permissions,
]


# ---------------------------------------------------------------- 执行与落库


def evaluate_all(session: Session, tenant_id: str) -> list[RuleResult]:
    """运行全部规则（不含落库），now 单次执行内固定，保证结果一致。"""
    now = _now(session)
    results: list[RuleResult] = []
    for rule in RULES:
        results.extend(rule(session, tenant_id, now))
    return results


def upsert_findings(session: Session, tenant_id: str, results: list[RuleResult]) -> dict[str, int]:
    """幂等落库：同 (rule_id, asset_id, resource_ref) 的 open Finding 只保留一条。

    返回 {"created": n, "updated": n}。审计与事件由调用方在同一事务内追加。
    """
    from app.models import utcnow
    from app.outbox import audit, emit_event

    created = 0
    updated = 0
    now = utcnow()
    for r in results:
        existing = session.scalar(
            select(Finding).where(
                Finding.tenant_id == tenant_id,
                Finding.rule_id == r.rule_id,
                Finding.asset_id == r.asset_id,
                Finding.resource_ref == r.resource_ref,
                Finding.status == "open",
            )
        )
        if existing is not None:
            existing.last_seen_at = now
            updated += 1
            continue
        finding = Finding(
            tenant_id=tenant_id,
            rule_id=r.rule_id,
            rule_version=1,
            severity=r.severity,
            domain=r.domain,
            asset_id=r.asset_id,
            resource_ref=r.resource_ref,
            evidence_ids=r.evidence_ids,
            impact=r.impact,
            remediation=r.remediation,
            status="open",
        )
        session.add(finding)
        audit(
            session,
            tenant_id,
            "system",
            "rule-engine",
            "finding.open",
            "finding",
            resource_id=finding.id,
            summary={"rule_id": r.rule_id, "severity": r.severity},
        )
        emit_event(
            session,
            tenant_id,
            "agent.finding.opened.v1",
            {
                "finding_id": finding.id,
                "rule_id": r.rule_id,
                "severity": r.severity,
                "asset_id": r.asset_id,
            },
            resource_ref=finding.id,
        )
        created += 1
    return {"created": created, "updated": updated}
