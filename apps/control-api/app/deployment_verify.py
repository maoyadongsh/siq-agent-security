"""部署回执独立验证（P2：receipt verifier / attestation）。

动机：部署路径（routers/policies.create_deployment 与 Edge 回执通道）的验证证据
由部署路径自己产生并自报，信任链单一。本模块提供控制面独立读回：
不信任 receipt 内容本身，重新向执行后端读取 target 当前 revision，与
receipt 中记录的 backend_revision 比对，并把结论作为 attestation 落库。

语义（fail-closed）：
- receipt 无 backend_revision → "no_receipt"（无证据可验，绝不判通过）；
- 后端不可达（AdapterError）→ "unreachable"，如实记录，不改动任何状态；
- snapshot.revision == receipt.backend_revision → "verified"；
- 不一致 → "mismatch"：落 Finding（幂等 upsert）+ outbox 事件；
  deployment.status 不自动翻转（与 drift.py 一致：Finding 驱动处置）。

与 drift.py 的分工：drift.py 是周期巡检（全量 effective 部署、多维比对、
规则内容级漂移）；本模块是按需单点验证（一次部署、revision 一致性、
结果写入 deployment.verification["independent_attestation"] 供审计回放）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.contracts import AdapterError
from app.models import Deployment, Finding, new_id, utcnow
from app.outbox import audit, emit_event
from app.safe_errors import error_reference

VERIFIER_ID = "control-plane.independent-readback.v1"
MISMATCH_RULE_ID = "deployment-receipt-mismatch"


def verify_deployment_receipt(
    session: Session,
    tenant_id: str,
    deployment: Deployment,
    *,
    backend=None,
) -> dict:
    """独立读回验证部署回执；返回 attestation dict 并落库（不自行提交事务）。"""
    receipt = deployment.receipt or {}
    expected = receipt.get("backend_revision")
    expected = str(expected) if expected is not None else None
    attestation: dict = {
        "verifier": VERIFIER_ID,
        "checked_at": datetime.now(UTC).isoformat(),
        "expected_revision": expected,
        "actual_revision": None,
        "result": None,
    }
    audit_summary: dict = {"expected_revision": expected, "actual_revision": None}

    if expected is None:
        attestation["result"] = "no_receipt"
    else:
        backend = backend or OpenShellCliBackend()
        try:
            snapshot = backend.read_effective_policy(deployment.target)
        except AdapterError as exc:
            # 后端不可达：fail-closed 如实记录，绝不把"没查到"当"已验证"；不改动状态
            attestation["result"] = "unreachable"
            audit_summary.update(error_reference(exc))
        else:
            actual = str(snapshot.revision)
            attestation["actual_revision"] = actual
            audit_summary["actual_revision"] = actual
            if actual == expected:
                attestation["result"] = "verified"
            else:
                attestation["result"] = "mismatch"
                _record_mismatch(session, tenant_id, deployment, expected, actual)

    audit_summary["result"] = attestation["result"]
    verification = dict(deployment.verification or {})
    verification["independent_attestation"] = attestation
    deployment.verification = verification
    audit(
        session,
        tenant_id,
        "system",
        "receipt-verify",
        "deployment.receipt_verify",
        "deployment",
        resource_id=deployment.id,
        summary=audit_summary,
    )
    return attestation


def _record_mismatch(
    session: Session,
    tenant_id: str,
    deployment: Deployment,
    expected: str,
    actual: str,
) -> None:
    """mismatch → Finding 幂等 upsert（键 = rule_id + resource_ref + open）+ outbox 事件。"""
    existing = session.scalar(
        select(Finding).where(
            Finding.tenant_id == tenant_id,
            Finding.rule_id == MISMATCH_RULE_ID,
            Finding.resource_ref == deployment.id,
            Finding.status == "open",
        )
    )
    if existing is not None:
        existing.last_seen_at = utcnow()
    else:
        session.add(
            Finding(
                id=new_id("fnd"),
                tenant_id=tenant_id,
                rule_id=MISMATCH_RULE_ID,
                rule_version=1,
                severity="high",
                domain="drift",
                resource_ref=deployment.id,
                impact=(
                    f"独立读回验证发现执行端 revision {actual} 与部署回执 {expected} 不一致，"
                    "部署可能已被带外变更"
                ),
                remediation="核对回执与实际执行状态；确认带外变更原因或重新部署期望策略",
                status="open",
            )
        )
    emit_event(
        session,
        tenant_id,
        "policy.deployment.receipt_mismatch.v1",
        {
            "deployment_id": deployment.id,
            "expected_revision": expected,
            "actual_revision": actual,
        },
        resource_ref=deployment.id,
    )
