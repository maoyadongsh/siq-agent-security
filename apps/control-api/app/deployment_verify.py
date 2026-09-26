"""部署回执独立验证（P2：receipt verifier / attestation）。

动机：部署路径（routers/policies.create_deployment 与 Edge 回执通道）的验证证据
由部署路径自己产生并自报，信任链单一。本模块提供控制面独立读回：
不信任 receipt 内容本身，重新向执行后端读取 target 当前 revision，与
receipt 中记录的 backend_revision 比对，并把结论作为 attestation 落库。

语义（fail-closed）：
- receipt 非对象，或 backend_revision 缺失/非字符串/空串/超长 → "no_receipt"
  （无可用证据，绝不判通过，且不访问后端）；
- 后端不可达（AdapterError）或读回结构不符合 PolicySnapshot 合同
  （target/revision 非字符串）→ "unreachable"，如实记录，不改动任何状态；
- 仅当独立读回的目标与 deployment.target 一致、且 revision 与回执字符串相等时
  → "verified"；
- 读回目标/回执自述 target 与部署目标冲突，或 revision 不一致 → "mismatch"：
  落 Finding（幂等 upsert）+ outbox 事件；
  deployment.status 不自动翻转（与 drift.py 一致：Finding 驱动处置）。

比较阶段不做 str() 归一、不裁剪、不改大小写：布尔/数字/数组/对象等异常回执值
不会被"修正"为合法值后参与比较；缺证据时按 no_receipt 处理而非猜值。

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
# 回执 revision 的长度上限，对齐 EdgeReceiptVerification.backend_revision 的合同约束
# (max_length=128)。超限值不是可用证据，按 no_receipt 处理，绝不截断后与另一标识归一。
MAX_RECEIPT_REVISION_CHARS = 128
MAX_TARGET_CHARS = 128  # Deployment.target String(128)


def _usable_identifier(value: object, limit: int) -> bool:
    # Only test whitespace; never normalize the identifier used for comparison.
    return isinstance(value, str) and 0 < len(value) <= limit and bool(value.strip())


def _receipt_expected_revision(receipt: object) -> str | None:
    """仅当 receipt 是对象且 backend_revision 是合同类型(str)的非空值时返回该证据。

    不使用 str() 把布尔/数字/数组/对象等异常值"修正"为可比较的字符串：缺少可验证
    证据时返回 None，由调用方判 no_receipt 并在访问后端前止步。

    仅用 strip() 判断是否为空证据（空白串不是可用 revision）；返回的是**原样**字符串，
    绝不用去空白后的值参与比较——因此 "7" 与 " 7 " 仍是两个不同标识，不会被归一。
    """
    if not isinstance(receipt, dict):
        return None
    # Absence is valid for legacy receipts; an explicitly malformed assertion is not.
    if "target" in receipt and not _usable_identifier(receipt["target"], MAX_TARGET_CHARS):
        return None
    value = receipt.get("backend_revision")
    if not isinstance(value, str):
        return None
    if not value or len(value) > MAX_RECEIPT_REVISION_CHARS:
        return None
    if not value.strip():
        return None
    return value


def _receipt_target_conflict(receipt: object, deployment_target: str) -> bool:
    """回执自述 target 与部署目标冲突时返回 True。

    旧回执合法地不带 target，保持兼容。显式异常值在证据校验阶段拒绝，
    不将异常值当成已核实的目标冲突。
    """
    if not isinstance(receipt, dict):
        return False
    value = receipt.get("target")
    if not isinstance(value, str) or not value:
        return False
    return value != deployment_target


def _readback_conforms(snapshot: object) -> bool:
    """PolicySnapshot 合同要求 target/revision 为 str；否则该读回不可信，fail-closed。

    revision 另受 MAX_RECEIPT_REVISION_CHARS 约束，避免把超长异常串写入审计/attestation。
    """
    revision = getattr(snapshot, "revision", None)
    target = getattr(snapshot, "target", None)
    return _usable_identifier(revision, MAX_RECEIPT_REVISION_CHARS) and _usable_identifier(target, MAX_TARGET_CHARS)


def verify_deployment_receipt(
    session: Session,
    tenant_id: str,
    deployment: Deployment,
    *,
    backend=None,
) -> dict:
    """独立读回验证部署回执；返回 attestation dict 并落库（不自行提交事务）。"""
    receipt = deployment.receipt
    expected = _receipt_expected_revision(receipt)
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
        backend = backend if backend is not None else OpenShellCliBackend()
        try:
            snapshot = backend.read_effective_policy(deployment.target)
        except AdapterError as exc:
            # 后端不可达：fail-closed 如实记录，绝不把"没查到"当"已验证"；不改动状态
            attestation["result"] = "unreachable"
            audit_summary.update(error_reference(exc))
        else:
            if not _readback_conforms(snapshot):
                # 读回结构不符合合同 → 不是可信独立读回，fail-closed；不判通过、不泄漏原值
                attestation["result"] = "unreachable"
                audit_summary.update(
                    error_reference(AdapterError("openshell_readback_contract_violation"))
                )
            else:
                actual = snapshot.revision
                attestation["actual_revision"] = actual
                audit_summary["actual_revision"] = actual
                if snapshot.target != deployment.target:
                    # 读回的是别的目标：revision 相同也绝不 verified
                    attestation["result"] = "mismatch"
                    _record_mismatch(
                        session, tenant_id, deployment, expected, actual, reason="readback_target"
                    )
                elif _receipt_target_conflict(receipt, deployment.target):
                    # 回执自述目标与部署目标冲突：即使读回一致也不 verified
                    attestation["result"] = "mismatch"
                    _record_mismatch(
                        session, tenant_id, deployment, expected, actual, reason="receipt_target"
                    )
                elif actual == expected:
                    attestation["result"] = "verified"
                else:
                    attestation["result"] = "mismatch"
                    _record_mismatch(
                        session, tenant_id, deployment, expected, actual, reason="revision"
                    )

    audit_summary["result"] = attestation["result"]
    # 既有 verification 只在确为对象时保留其键；非对象（异常列）不崩溃、不泄漏原文
    verification = dict(deployment.verification) if isinstance(deployment.verification, dict) else {}
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
    *,
    reason: str = "revision",
) -> None:
    """mismatch → Finding 幂等 upsert（键 = rule_id + resource_ref + open）+ outbox 事件。"""
    if reason == "readback_target":
        impact = (
            "独立读回返回的目标与部署目标不一致，部署目标可能已被带外替换或读回后端异常；"
            f"读回 revision 为 {actual}"
        )
        remediation = "核对部署目标归属与执行端实际目标；确认带外替换原因后重新部署期望策略"
    elif reason == "receipt_target":
        impact = (
            "部署回执自述 target 与部署目标冲突，回执可能被篡改或错配；"
            f"读回 revision 为 {actual}"
        )
        remediation = "核对回执来源与部署目标绑定；确认篡改/错配原因后重新执行部署"
    else:
        impact = (
            f"独立读回验证发现执行端 revision {actual} 与部署回执 {expected} 不一致，"
            "部署可能已被带外变更"
        )
        remediation = "核对回执与实际执行状态；确认带外变更原因或重新部署期望策略"
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
                impact=impact,
                remediation=remediation,
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
