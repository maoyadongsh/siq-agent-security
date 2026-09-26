"""漂移检测（设计文档 §13.3）：期望状态 vs 执行端实际状态。

比较维度：
1. 部署回执 revision vs 后端当前 revision（带外变更）；
2. Desired Policy 网络规则 vs 后端有效策略网络规则（静默丢失/缺失）；
3. 部署目标在后端不存在（沙箱被带外删除）。

fail-closed：后端不可达时如实报错，绝不把"没查到"当"没漂移"。

异常证据与租户关联（本模块的安全边界）：
- 单条部署的证据无法核对时，产出既有 `unreadable` 结果（`error_reference` 固定脱敏
  参考），不推导 revision_mismatch/missing_rules/undeclared_rules，也不影响同批其他部署；
- 后端读回（target/revision 结构与目标）不可信时，该部署本轮不产出任何其他结论
  —— 读回同时是两个维度的依据；读回结果不能是"可信的当前有效规则"，除非
  `PolicySnapshot.target` 与本部署 target 完全一致；
- 回执证据（`Deployment.receipt.backend_revision`）与期望策略证据（关联
  ChangeRequest/DesiredPolicy）各自只影响自己的维度：一方不可核对时该维度作废，
  另一维度仍按各自可信证据比对，不把可独立验证的事实丢弃；
- 回执自述 target 若显式出现，必须与本部署 target 原值一致：别的目标的回执不是本部署
  的 revision 证据，即使 revision 恰好相同也不得判"无漂移"（不 trim、不 lowercase、
  不重定向，冲突时该维度判不可用，绝不据此推导 revision_mismatch）。
  缺 target 键的旧回执保持兼容（不要求该字段）；
- 网络规则行 `effect` 是合同字段：显式取值只接受 `allow`/`deny`（openshell-policy-safety.v2
  §Network compilation 只编译 `effect=allow`；读回生产者恒产出 `allow`），既有比较模型
  排除 `deny` 行；显式非法值（未知字符串、空串、大小写变体、非字符串）使该维度判不可用，
  既不当作允许规则，也不静默跳过。缺 `effect` 键沿用既有"非 deny 即 allow"模型，
  不新增限制（避免误拒合法历史记录）；
- 关联策略必须属于当前验证租户：跨租户或缺引用一律按不可用证据处理，绝不读取、
  比较或回显对方对象（含名称、规则、标识）；
- 比较保持原值语义：不做 `str()` 归一、不 trim、不 lowercase、不截断。数字/布尔/
  对象等异常 revision 不是可用证据；字符串 "0" 等具体取值是否可用由各适配器合同决定，
  漂移模块不新增正整数或纯数字限制（"正整数 revision" 是 CLI 路径约束，不是本模块约束）；
- 缺失、null 与合法空列表按合同区分：`DesiredPolicy.network` 为 `list | None`，
  null 表示未声明网络（沿用既有"无期望 allow 规则"语义）；后端读回网络合同是
  `list[dict]`，null 或非列表容器都是不可用读回，绝不悄悄当作空列表。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.contracts import AdapterError
from app.models import ChangeRequest, Deployment, DesiredPolicy, Finding, new_id, utcnow
from app.outbox import audit, emit_event
from app.safe_errors import error_reference

# 证据不可核对时的固定内部原因码：只以适配器错误类别 + sha256 摘要落库，原文不持久化
_READBACK_UNUSABLE = "openshell_drift_readback_unusable"  # 读回结构不符合 PolicySnapshot 合同
_READBACK_TARGET_MISMATCH = "openshell_drift_readback_target_mismatch"  # 读回目标不是本部署目标
_RECEIPT_UNUSABLE = "openshell_drift_receipt_unusable"  # 回执存在但不是可核对证据
_RECEIPT_TARGET_MISMATCH = "openshell_drift_receipt_target_mismatch"  # 回执自述目标是别的部署目标
_POLICY_EVIDENCE_UNAVAILABLE = "openshell_drift_policy_evidence_unavailable"  # 关联缺失或跨租户
_NETWORK_EVIDENCE_UNUSABLE = "openshell_drift_network_unusable"  # 网络容器/规则行不是合法证据

# 证据标识长度上限：对齐 Deployment.target(String(128)) / EdgeReceiptVerification.backend_revision
# (max_length=128)。超限值不是可用证据，也绝不截断后与另一标识归一比较。
_MAX_EVIDENCE_IDENTIFIER_CHARS = 128

# 网络规则 effect 的合法显式取值（合同白名单，非新增结果枚举）：`allow` 参与比较，
# `deny` 按既有比较模型显式排除；缺键沿用既有默认（见 _DEFAULT_RULE_EFFECT）。
_RULE_EFFECTS = ("allow", "deny")
_DEFAULT_RULE_EFFECT = "allow"

# Finding.severity 现有合法级别（models.py Finding.severity 注释）的排序权重：只用于取本轮最高
# 级别与判断是否降级，不新增枚举，也不改写未知取值（未知一律不参与级别比较）。
_SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

# 内部哨兵：区分"回执不存在（既有容忍语义）"与"回执存在但不可核对"。_TARGET_CONFLICT
# 只用于给出更精确的固定原因码，仍是既有 unreadable 结果，不新增 kind/响应字段。
_UNUSABLE = object()
_TARGET_CONFLICT = object()


@dataclass(frozen=True)
class DriftResult:
    deployment_id: str
    target: str
    severity: str  # high|medium|info
    summary: str
    details: dict


def _usable_identifier(value: object) -> bool:
    """合同类型(str)、非空、非纯空白、不超限。只做可用性判断，绝不返回归一/裁剪后的值。"""
    return (
        isinstance(value, str)
        and 0 < len(value) <= _MAX_EVIDENCE_IDENTIFIER_CHARS
        and bool(value.strip())
    )


def _receipt_revision(receipt: object, expected_target: object) -> object:
    """回执 revision 证据：None=无回执；_UNUSABLE/_TARGET_CONFLICT=回执存在但不可核对；str=原样可用值。

    `Deployment.receipt` 为 NULL 是"没有记录回执"，沿用既有语义只跳过 revision 维度；
    回执对象一旦存在，其显式字段就是一条可核对的断言：非对象、显式异常 target、
    非字符串/空/空白/超限的 backend_revision 都不是可用证据（对齐 receipt verifier
    的可用性规则），由调用方判 `unreadable`。绝不 `str()` 把数字/布尔/对象"修正"
    成可比较字符串，也不 trim 后比较。

    显式 `target` 还必须是**本部署**目标（`deployment.target`）的原值：别的目标的回执
    不能作为本部署的 revision 证据（`_TARGET_CONFLICT`，固定原因码与普通结构异常区分开，
    便于运维定位，但不回显该目标原文）。缺 `target` 键的旧回执保持兼容。
    """
    if receipt is None:
        return None
    if not isinstance(receipt, dict):
        return _UNUSABLE
    if "target" in receipt:
        target = receipt["target"]
        if not _usable_identifier(target):
            return _UNUSABLE
        if target != expected_target:
            return _TARGET_CONFLICT
    revision = receipt.get("backend_revision")
    if not _usable_identifier(revision):
        return _UNUSABLE
    return revision


def _readback_reason(snapshot: object, deployment: Deployment) -> str | None:
    """读回不可核对的固定原因码；None 表示该读回可用于比对。

    读回目标必须与本部署 target 完全一致：别的目标的有效规则不是本部署的当前规则，
    即使 revision 相同也不能当成可信事实。
    """
    target = getattr(snapshot, "target", None)
    revision = getattr(snapshot, "revision", None)
    if not _usable_identifier(target) or not _usable_identifier(revision):
        return _READBACK_UNUSABLE
    if target != deployment.target:
        return _READBACK_TARGET_MISMATCH
    return None


def _endpoint_set(container: object, *, none_is_empty: bool) -> set[str] | None:
    """网络容器 → 非 deny 的 endpoint 集合；None 表示证据不可用（调用方判 unreadable）。

    最小结构校验（不重写网络规则 schema，也不改变 allow/deny 比较模型）：容器必须是
    列表（`none_is_empty=True` 时 None 表示未声明），每行必须是对象，endpoint 必须是
    非空字符串；`effect` 显式出现时必须是合同白名单取值（`allow`/`deny`），其它任何
    值（未知字符串、空串、大小写变体、非字符串）都使该维度证据不可用——既不当作允许
    规则，也不静默跳过（跳过会伪造缺失/额外规则）。缺 `effect` 键沿用既有默认
    `_DEFAULT_RULE_EFFECT`，不误拒合法历史记录。异常容器或异常行一律判不可用，绝不
    静默过滤成空列表，也绝不把非字符串 endpoint 放进集合后参与差集/排序。
    """
    if container is None:
        return set() if none_is_empty else None
    if not isinstance(container, list):
        return None
    endpoints: set[str] = set()
    for row in container:
        if not isinstance(row, dict):
            return None
        endpoint = row.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint:
            return None
        effect = row.get("effect", _DEFAULT_RULE_EFFECT)
        if effect not in _RULE_EFFECTS:
            return None
        if effect != "deny":
            endpoints.add(endpoint)
    return endpoints


def _unreadable(deployment: Deployment, reason: str) -> DriftResult:
    """既有 unreadable 结果：固定脱敏错误参考，不回显异常原文或异常目标。"""
    error = error_reference(AdapterError(reason))
    return DriftResult(
        deployment_id=deployment.id,
        target=deployment.target,
        severity="medium",
        summary=f"无法核对后端漂移证据（错误参考 {error['error_digest']}）",
        details={"kind": "unreadable", **error},
    )


def check_policy_drift(session: Session, tenant_id: str) -> list[DriftResult]:
    """对租户内所有 effective 部署做后端状态比对；返回漂移结果（由调用方落 Finding）。

    单条部署不得影响同批其他部署：每条部署的证据独立核对，异常时只产出该部署的
    `unreadable` 结果（`AdapterError` 之外的编程/数据库错误不在此处吞掉，照常抛出）。
    """
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
            error = error_reference(exc)
            results.append(
                DriftResult(
                    deployment_id=dep.id,
                    target=dep.target,
                    severity="medium",
                    summary=f"无法读取后端有效策略（错误参考 {error['error_digest']}）",
                    details={"kind": "unreadable", **error},
                )
            )
            continue

        # 读回本身是两个维度的共同依据：不可核对的读回不产出任何其他结论
        readback_reason = _readback_reason(snapshot, dep)
        if readback_reason is not None:
            results.append(_unreadable(dep, readback_reason))
            continue

        unreadable: list[DriftResult] = []
        drifts: list[DriftResult] = []

        # 1) revision 比对（带外变更）：仅当回执 revision 是原样的可用证据
        #    回执自述目标是别的部署目标时，该回执不是本部署证据：只报不可用，不比对、
        #    不推导 revision_mismatch，也不把该目标原文写入结果。
        receipt_revision = _receipt_revision(dep.receipt, dep.target)
        if receipt_revision is _TARGET_CONFLICT:
            unreadable.append(_unreadable(dep, _RECEIPT_TARGET_MISMATCH))
        elif receipt_revision is _UNUSABLE:
            unreadable.append(_unreadable(dep, _RECEIPT_UNUSABLE))
        elif receipt_revision is not None and snapshot.revision != receipt_revision:
            drifts.append(
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

        # 2) Desired 网络规则 vs 有效规则：关联必须显式限定本租户，缺失/跨租户即无可用证据
        cr = session.scalar(
            select(ChangeRequest).where(
                ChangeRequest.id == dep.change_request_id,
                ChangeRequest.tenant_id == tenant_id,
            )
        )
        policy = None
        if cr is not None:
            policy = session.scalar(
                select(DesiredPolicy).where(
                    DesiredPolicy.id == cr.policy_id,
                    DesiredPolicy.tenant_id == tenant_id,
                )
            )
        if policy is None:
            # 找不到本租户期望策略既不是"期望没有网络规则"，也不构成无漂移结论
            unreadable.append(_unreadable(dep, _POLICY_EVIDENCE_UNAVAILABLE))
        else:
            desired_endpoints = _endpoint_set(policy.network, none_is_empty=True)
            effective_endpoints = _endpoint_set(snapshot.network, none_is_empty=False)
            if desired_endpoints is None or effective_endpoints is None:
                unreadable.append(_unreadable(dep, _NETWORK_EVIDENCE_UNUSABLE))
            else:
                missing = desired_endpoints - effective_endpoints
                if missing:
                    drifts.append(
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
                    drifts.append(
                        DriftResult(
                            deployment_id=dep.id,
                            target=dep.target,
                            severity="medium",
                            summary=f"后端存在未登记的额外网络规则: {sorted(extra)[:3]}",
                            details={"kind": "undeclared_rules", "extra": sorted(extra)},
                        )
                    )

        # 不可核对证据先于本部署的漂移结论返回；同批其他部署不受影响
        results.extend(unreadable)
        results.extend(drifts)

    return results


def _severity_rank(severity: object) -> int | None:
    """现有合法级别的排序权重；未知取值返回 None（不参与比较，也绝不据此改写级别）。"""
    return _SEVERITY_RANK.get(severity) if isinstance(severity, str) else None


def _representative_result(group: list[DriftResult]) -> DriftResult:
    """同一部署本轮多条结果 → 一条代表项（与输入顺序无关、不修改也不重排入参）。

    规则：严重级别最高者优先；同级按 `kind` 升序；仍相同则以固定细节序列（JSON 键排序）
    定序，最后以摘要原文打破平局。级别未知的结果排在已知级别之后。
    代表项整条使用：severity/summary/details 永远来自同一条结果。
    """
    return min(group, key=_representative_sort_key)


def _representative_sort_key(result: DriftResult) -> tuple:
    rank = _severity_rank(result.severity)
    return (
        0 if rank is not None else 1,
        -(rank if rank is not None else 0),
        str(result.details.get("kind") or ""),
        json.dumps(result.details, sort_keys=True, default=str),
        result.summary,
    )


def upsert_drift_findings(session: Session, tenant_id: str, results: list[DriftResult]) -> dict:
    """漂移 → Finding（幂等 upsert，键 = rule_id + resource_ref + open；每部署每轮只写一次）。

    同一部署本轮可能产出多条结果（unreadable / revision_mismatch / missing_rules /
    undeclared_rules）。因此先**按部署分组**，每部署只 upsert 一次，避免后一条结果覆盖前一条
    造成的级别与证据错配。代表项取本轮该部署严重级别最高的结果（同级按固定规则定序，与输入
    顺序无关），其 severity/summary/details **整条**写入，绝不把一种风险的摘要与另一种风险的
    详情拼在一起。代表项不声称包含本轮全部证据：端点响应仍保留全部 drift_results，若要持久化
    多条证据需要返回合同变化，不在本函数范围内。

    更新既有 open Finding 时（保守、不自动降级）：现有风险生命周期（用户显式 acknowledge/
    resolve/accept-risk、worker 的 risk_acceptance 到期重开）没有"证据变轻即自动降级"的合同，
    所以本轮最高级别低于既有级别（或任一级别不是现有合法取值）时，只刷新 last_seen_at，保留
    既有的 severity/impact/risk_acceptance 三件套（它们本身同源，不自相矛盾），本轮更低级别的
    证据可由本次端点响应查看，不声称更新审计持久化了全部证据。
    本轮级别不低于既有级别时，三件套一起换成本轮代表项。
    不自动关闭/重新打开/删除 Finding，first_seen_at、id、owner_user_id、due_at、evidence_ids、
    status 等无关字段保持原值。

    返回 {"created": n, "updated": n}：按本次**实际创建/更新的 Finding 数**计（同一部署本轮
    最多计一次），不是结果条数。不自行 commit：审计/outbox 与状态变化同事务，审计失败由调用方
    的事务回滚。新建时若无合法级别代表项，抛固定错误交调用方回滚，不静默跳过风险。
    """
    grouped: dict[str, list[DriftResult]] = {}
    for r in results:
        grouped.setdefault(r.deployment_id, []).append(r)

    created = 0
    updated = 0
    now = utcnow()
    for deployment_id, group in grouped.items():
        representative = _representative_result(group)
        existing = session.scalar(
            select(Finding).where(
                Finding.tenant_id == tenant_id,
                Finding.rule_id == "policy-drift",
                Finding.resource_ref == f"deployment:{deployment_id}",
                Finding.status == "open",
            )
        )
        incoming_rank = _severity_rank(representative.severity)
        if existing is not None:
            existing_rank = _severity_rank(existing.severity)
            existing.last_seen_at = now
            # 级别未知或本轮更低：保留既有三件套，不降级、不把未知级别写进库
            if existing_rank is None or incoming_rank is None or incoming_rank < existing_rank:
                updated += 1
                continue
            existing.severity = representative.severity
            existing.impact = representative.summary
            existing.risk_acceptance = representative.details
            updated += 1
            continue
        if incoming_rank is None:
            raise ValueError("drift_finding_severity_unavailable")
        finding = Finding(
            id=new_id("fnd"),
            tenant_id=tenant_id,
            rule_id="policy-drift",
            rule_version=1,
            severity=representative.severity,
            domain="policy",
            resource_ref=f"deployment:{deployment_id}",
            impact=representative.summary,
            remediation="恢复期望策略（重新部署）或记录带外变更原因",
            status="open",
            risk_acceptance=representative.details,
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
            summary={
                "rule_id": "policy-drift",
                "severity": representative.severity,
                "kind": representative.details.get("kind"),
            },
        )
        emit_event(
            session,
            tenant_id,
            "policy.drift.detected.v1",
            {"finding_id": finding.id, "deployment_id": deployment_id, "kind": representative.details.get("kind")},
            resource_ref=finding.id,
        )
        created += 1
    return {"created": created, "updated": updated}
