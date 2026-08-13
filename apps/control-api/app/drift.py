"""漂移检测（设计文档 §13.3）：期望状态 vs 执行端实际状态。

比较维度：
1. 部署回执 revision vs 后端当前 revision（带外变更）；
2. Desired Policy 网络规则 vs 后端有效策略网络规则（静默丢失/缺失）；
3. 部署目标在后端不存在（沙箱被带外删除）。

fail-closed：后端不可达时如实报错，绝不把"没查到"当"没漂移"。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.contracts import AdapterError
from app.models import ChangeRequest, Deployment, DesiredPolicy, utcnow
from app.outbox import audit, emit_event


@dataclass(frozen=True)
class DriftResult:
    deployment_id: str
    target: str
    severity: str  # high|medium|info
    summary: str
    details: dict


def check_policy_drift(session: Session, tenant_id: str) -> list[DriftResult]:
    """对租户内所有 effective 部署做后端状态比对；返回漂移结果（由调用方落 Finding）。"""
    backend = OpenShellCliBackend()
    deployments = list(
        session.scalars(
            select(Deployment).where(Deployment.tenant_id == tenant_id, Deployment.status == "effective")
        )
    )
    results: list[DriftResult] = []
    for dep in deployments:
        try:
            snapshot = backend.read_effective_policy(dep.target)
        except AdapterError as exc:
            # 后端不可达/目标缺失：如实标记（fail-closed），不静默跳过
            results.append(
                DriftResult(
                    deployment_id=dep.id,
                    target=dep.target,
                    severity="medium",
                    summary=f"无法读取后端有效策略（含目标不存在）: {str(exc)[:160]}",
                    details={"kind": "unreadable", "error": str(exc)[:200]},
                )
            )
            continue

        # 1) revision 比对（带外变更）
        receipt_revision = (dep.receipt or {}).get("backend_revision")
        if receipt_revision and snapshot.revision != str(receipt_revision):
            results.append(
                DriftResult(
                    deployment_id=dep.id,
                    target=dep.target,
                    severity="high",
                    summary=(
                        f"执行端 revision {snapshot.revision} 与部署回执 {receipt_revision} 不一致（带外变更）"
                    ),
                    details={"kind": "revision_mismatch", "backend": snapshot.revision, "receipt": receipt_revision},
                )
            )

        # 2) Desired 网络规则 vs 有效规则
        cr = session.get(ChangeRequest, dep.change_request_id)
        policy = session.get(DesiredPolicy, cr.policy_id) if cr else None
        if policy is not None:
            desired_endpoints = {
                r.get("endpoint") for r in (policy.network or []) if r.get("effect") != "deny"
            }
            effective_endpoints = {r.get("endpoint") for r in snapshot.network if r.get("effect") != "deny"}
            missing = desired_endpoints - effective_endpoints
            if missing:
                results.append(
                    DriftResult(
                        deployment_id=dep.id,
                        target=dep.target,
                        severity="high",
                        summary=f"期望网络规则在后端缺失: {sorted(missing)[:3]}",
                        details={"kind": "missing_rules", "missing": sorted(missing)},
                    )
                )
            extra = effective_endpoints - desired_endpoints
            if extra:
                results.append(
                    DriftResult(
                        deployment_id=dep.id,
                        target=dep.target,
                        severity="medium",
                        summary=f"后端存在未登记的额外网络规则: {sorted(extra)[:3]}",
                        details={"kind": "undeclared_rules", "extra": sorted(extra)},
                    )
                )

    return results


def upsert_drift_findings(session: Session, tenant_id: str, results: list[DriftResult]) -> dict:
    """漂移 → Finding（幂等 upsert，键 = rule_id + resource_ref + open）。"""
    from app.models import Finding

    created = 0
    updated = 0
    now = utcnow()
    for r in results:
        existing = session.scalar(
            select(Finding).where(
                Finding.tenant_id == tenant_id,
                Finding.rule_id == "policy-drift",
                Finding.resource_ref == f"deployment:{r.deployment_id}",
                Finding.status == "open",
            )
        )
        if existing is not None:
            existing.last_seen_at = now
            existing.severity = r.severity
            existing.risk_acceptance = r.details
            updated += 1
            continue
        finding = Finding(
            tenant_id=tenant_id,
            rule_id="policy-drift",
            rule_version=1,
            severity=r.severity,
            domain="policy",
            resource_ref=f"deployment:{r.deployment_id}",
            impact=r.summary,
            remediation="恢复期望策略（重新部署）或记录带外变更原因",
            status="open",
            risk_acceptance=r.details,
        )
        session.add(finding)
        audit(
            session,
            tenant_id,
            "system",
            "drift-check",
            "finding.open",
            "finding",
            resource_id=finding.id,
            summary={"rule_id": "policy-drift", "severity": r.severity, "kind": r.details.get("kind")},
        )
        emit_event(
            session,
            tenant_id,
            "policy.drift.detected.v1",
            {"finding_id": finding.id, "deployment_id": r.deployment_id, "kind": r.details.get("kind")},
            resource_ref=finding.id,
        )
        created += 1
    return {"created": created, "updated": updated}
