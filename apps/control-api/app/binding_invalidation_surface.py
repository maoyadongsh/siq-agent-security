"""内部只读失效联动投影：一个已登记绑定失效时，哪些**已登记对象**随之不可用、哪些无法由记录判定。

本模块只回答"现有持久记录里，这个绑定被谁引用、失效后哪条既有路径会被拒绝"，并为不能判定
的部分给出固定原因码。它**不是** HTTP 接口、**不是** 吊销执行器、**不**级联修改任何行：
本层不做吊销、不重放、不重试、不标记失败、不新增锁或独占协议，`execution_confirmation_supported`
恒为 `False`。任何"记录里有引用"都不得解释为运行占用、生效权限或独占归属。

只读边界：只做租户限定的 `SELECT`；不写库、不产生审计/outbox/任务、不发起外部探测、不扫描宿主。
不复制第二套绑定判定：吊销即拒绝的结论直接取自 `app.binding_identity.require_binding_identity_unchanged`
的固定拒绝码语义；草稿解析复用 `app.routers.deployment_preview.BatchDeploymentPreview`。
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Deployment,
    DeploymentBatchDraft,
    RuntimeBinding,
)
from app.routers.deployment_preview import BatchDeploymentPreview
from app.security import Identity

SCHEMA_VERSION = "enterprise-binding-invalidation-surface/v1"

# 绑定状态（三值）。跨租户与不存在**不可区分**：都是 not_registered_in_tenant。
ACTIVE = "active"
REVOKED = "revoked"
NOT_REGISTERED = "not_registered_in_tenant"
BINDING_STATES = (ACTIVE, REVOKED, NOT_REGISTERED)

# 联动状态词表（固定五值；不设"部分覆盖"，也不给总体安全/不安全结论）。
DEPENDENCY_ABSENT = "dependency_absent"
DEPENDENCY_RECORDED = "dependency_recorded"
BLOCKED_IF_REVOKED = "blocked_if_revoked"
BLOCKED_NOW = "blocked_now"
NOT_DETERMINABLE = "not_determinable"
STATES = (DEPENDENCY_ABSENT, DEPENDENCY_RECORDED, BLOCKED_IF_REVOKED, BLOCKED_NOW,
          NOT_DETERMINABLE)

# 固定原因码。
REASON_CODES = frozenset({
    "binding_not_registered_in_tenant",
    "binding_revoked_records_retained",
    "no_recorded_deployment_for_binding",
    "deployment_records_are_history_not_current_state",
    "no_own_live_draft_references_binding",
    "no_own_live_draft_recorded_for_scope",
    "own_live_draft_references_binding",
    "draft_preview_unreadable",
    "draft_scan_truncated",
    "draft_ownership_is_actor_scoped",
    "other_actor_live_drafts_not_enumerable",
    "expired_drafts_outside_scan_scope",
    "runtime_occupancy_source_absent",
})

# 默认草稿扫描上界：只扫**本身份仍然存活**的草稿（TTL 5 分钟），超界如实标记截断。
DEFAULT_DRAFT_SCAN_LIMIT = 200

MUST_NOT_INFER = (
    "recorded_dependency_is_not_runtime_occupancy",
    "revocation_does_not_rollback_or_replay_history",
    "no_recorded_dependency_is_not_no_runtime_occupancy",
    "shared_runtime_occupants_remains_unknown",
    "other_actor_draft_coverage_is_not_established",
    "scan_scope_is_persistent_records_only",
)

DEPLOYMENT_MUST_NOT_INFER = (
    "deployment_record_is_not_current_runtime_state",
    "revocation_is_not_a_deployment_rollback",
)
DRAFT_MUST_NOT_INFER = (
    "draft_reference_is_not_a_reservation",
    "own_live_draft_scan_is_not_full_tenant_coverage",
    "expired_draft_is_not_scanned",
)


def project_binding_invalidation_surface(
    session: Session,
    identity: Identity,
    binding_id: str,
    draft_scan_limit: int = DEFAULT_DRAFT_SCAN_LIMIT,
) -> dict:
    """只读投影一个绑定的失效联动面。

    `tenant_id` 只取自服务端验证身份；所有查询显式限定该租户。绑定缺失或属于其它租户时返回与
    "不存在"完全相同的结构（不构成跨租户存在性判别）。`draft_scan_limit` 必须是正整数。
    """
    tenant_id = getattr(identity, "tenant_id", None)
    if not isinstance(tenant_id, str) or not tenant_id:
        raise ValueError("verified_tenant_identity_required")
    if not isinstance(binding_id, str) or not binding_id:
        raise ValueError("binding_id_required")
    if isinstance(draft_scan_limit, bool) or not isinstance(draft_scan_limit, int) or draft_scan_limit < 1:
        raise ValueError("draft_scan_limit_invalid")
    # 全部查询在 no_autoflush 内：不隐式刷新调用方会话中的待提交状态，本模块不产生任何写入。
    with session.no_autoflush:
        return _project(session, identity, binding_id, draft_scan_limit)


def _now_naive() -> datetime:
    """仓储内草稿时间列为 naive UTC，比较一律用同一时基。"""
    return datetime.now(UTC).replace(tzinfo=None)


def _project(session, identity, binding_id, draft_scan_limit) -> dict:
    tenant_id = identity.tenant_id
    binding = session.scalar(select(RuntimeBinding).where(
        RuntimeBinding.id == binding_id, RuntimeBinding.tenant_id == tenant_id))
    if binding is None:
        return _result(binding_id, NOT_REGISTERED, _undetermined_dependents(
            "binding_not_registered_in_tenant"), None)

    state = ACTIVE if binding.status == "active" else REVOKED
    dependents = {
        "executed_deployment_records": _deployments(session, tenant_id, binding_id, state),
        "own_live_batch_drafts": _own_live_drafts(
            session, identity, binding_id, state, draft_scan_limit),
        "other_actor_live_batch_drafts": _group(
            NOT_DETERMINABLE,
            ("draft_ownership_is_actor_scoped", "other_actor_live_drafts_not_enumerable"),
            None, DRAFT_MUST_NOT_INFER),
        "runtime_occupancy": _group(
            NOT_DETERMINABLE, ("runtime_occupancy_source_absent",), None, MUST_NOT_INFER),
    }
    return _result(binding_id, state, dependents, binding)


def _group(state, reasons=(), references=None, must_not_infer=()):
    return {
        "state": state,
        "reasons": sorted(set(reasons)),
        "references": dict(references or {}),
        "must_not_infer": list(must_not_infer),
    }


def _result(binding_id, binding_state, dependents, binding):
    return {
        "schema_version": SCHEMA_VERSION,
        "binding_id": binding_id,
        "binding_state": binding_state,
        "dependents": dependents,
        "effect_if_revoked": _effect_if_revoked(binding_state),
        "coverage": "recorded_dependencies_only",
        "shared_runtime_occupants": "unknown",
        "execution_confirmation_supported": False,
        "must_not_infer": list(MUST_NOT_INFER),
    }


def _effect_if_revoked(binding_state):
    """固定结论集：只列既有代码路径**可判定**的拒绝语义，不预测任何效果。

    `binding_revoked` 取自 `require_binding_identity_unchanged` 的固定拒绝码：吊销后预览/执行
    侧的绑定复验一律拒绝。这里只声明"会被拒绝"，不声明拒绝之外发生什么（尤其不声明回滚）。
    """
    return {
        "new_preview_or_execute_on_this_binding_rejected": "binding_revoked",
        "unreserved_draft_reserve_rejected": "binding_revoked",
        "existing_deployment_records_are_not_modified": True,
        "existing_effects_are_not_reverted": True,
        "already_expired_drafts_cannot_start_new_items": True,
        "binding_state_currently": binding_state,
    }


def _undetermined_dependents(reason):
    """跨租户/不存在：不展开任何子事实，也不回显对方标识。"""
    return {
        "executed_deployment_records": _group(
            NOT_DETERMINABLE, (reason,), None, DEPLOYMENT_MUST_NOT_INFER),
        "own_live_batch_drafts": _group(NOT_DETERMINABLE, (reason,), None, DRAFT_MUST_NOT_INFER),
        "other_actor_live_batch_drafts": _group(NOT_DETERMINABLE, (reason,), None,
                                               DRAFT_MUST_NOT_INFER),
        "runtime_occupancy": _group(NOT_DETERMINABLE, (reason,), None, MUST_NOT_INFER),
    }


def _deployments(session, tenant_id, binding_id, binding_state):
    """硬引用：`Deployment.runtime_binding_id` 外键。历史记录，不是当前运行状态。"""
    rows = session.execute(
        select(Deployment.status, func.count())
        .where(Deployment.tenant_id == tenant_id, Deployment.runtime_binding_id == binding_id)
        .group_by(Deployment.status)
    ).all()
    by_status = {status: count for status, count in rows}
    total = sum(by_status.values())
    if total == 0:
        return _group(DEPENDENCY_ABSENT, ("no_recorded_deployment_for_binding",), {
            "total": 0, "by_status": {},
        }, DEPLOYMENT_MUST_NOT_INFER)
    return _group(DEPENDENCY_RECORDED, ("deployment_records_are_history_not_current_state",), {
        "total": total,
        "by_status": {status: by_status[status] for status in sorted(by_status)},
        "binding_state_at_read": binding_state,
    }, DEPLOYMENT_MUST_NOT_INFER)


def _own_live_drafts(session, identity, binding_id, binding_state, scan_limit):
    """软引用：草稿 `preview.items[].binding_id`。只扫本身份**未过期**的草稿。

    所有权按 `_owned_draft` 的同一规则（`actor_id` + `actor_type`）；其它身份的草稿不读取、
    也不计入覆盖率。扫描上界之外的存活草稿无法判定，故如实标记截断而**不**声明"无引用"。
    已过期草稿不在扫描范围内：`batch_execution` 在起始前检查截止时间，过期草稿不可能再启动新项。
    """
    scoped = (
        DeploymentBatchDraft.tenant_id == identity.tenant_id,
        DeploymentBatchDraft.actor_id == identity.actor_id,
        DeploymentBatchDraft.actor_type == identity.identity_type,
        DeploymentBatchDraft.expires_at > _now_naive(),
    )
    rows = list(session.execute(
        select(DeploymentBatchDraft.id, DeploymentBatchDraft.preview, DeploymentBatchDraft.expires_at)
        .where(*scoped)
        .order_by(DeploymentBatchDraft.expires_at, DeploymentBatchDraft.id)
        .limit(scan_limit + 1)
    ).all())
    truncated = len(rows) > scan_limit
    scanned = rows[:scan_limit]

    matched, unreadable = [], []
    for draft_id, preview, expires_at in scanned:
        try:
            parsed = BatchDeploymentPreview.model_validate(preview)
        except (ValueError, TypeError, RecursionError):
            unreadable.append(draft_id)
            continue
        if any(item.binding_id == binding_id for item in parsed.items):
            matched.append({"draft_id": draft_id, "expires_at": _iso(expires_at)})

    scan = {"scanned": len(scanned), "limit": scan_limit, "truncated": truncated}
    reasons = {"expired_drafts_outside_scan_scope"}
    if not scanned:
        reasons.add("no_own_live_draft_recorded_for_scope")
    if unreadable:
        reasons.add("draft_preview_unreadable")
    if truncated:
        reasons.add("draft_scan_truncated")

    if matched:
        reasons.add("own_live_draft_references_binding")
        state = BLOCKED_NOW if binding_state == REVOKED else BLOCKED_IF_REVOKED
    elif unreadable or truncated:
        # 既没匹配上、也没扫完/没读全：**不得**声明无引用。
        state = NOT_DETERMINABLE
    else:
        reasons.add("no_own_live_draft_references_binding")
        state = DEPENDENCY_ABSENT

    references = {
        "matched": matched,
        "matched_count": len(matched),
        "unreadable_draft_ids": unreadable,
        "scan": scan,
    }
    return _group(state, reasons, references, DRAFT_MUST_NOT_INFER)


def _iso(value):
    """与既有只读投影一致的输出格式（仓储内 naive UTC 约定）。"""
    return None if value is None else value.isoformat() + "Z"
