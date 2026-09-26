"""内部只读证据就绪度：一个已登记绑定在当前持久记录下能核对什么、不能核对什么。

本模块只回答“现有已验证记录对每个证据维度成立到什么程度”，并为不能成立的情况给出固定原因码。
它**不是** HTTP 接口、**不是** 执行授权令牌、**不**开放执行：`execution_confirmation_supported`
恒为 `False`，任何维度为 `verified_from_records` 都不得解释为运行占用、角色归属、生效权限或审批通过。

只读边界：只做租户限定的 `SELECT`；不写库、不产生审计/outbox/任务、不发起外部网络探测、不扫描。
不复制第二套签名验证、绑定判定或名称匹配：绑定一致性复用 `app.binding_identity`，来源/设备复用
`app.framework_source_view` 与 `app.discovery_identity`，目录候选复用 `app.role_skill_roots`。
"""

import json

from fastapi import HTTPException
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.binding_identity import require_binding_identity_unchanged, snapshot_binding_identity
from app.discovery_identity import asset_evidence_device_filter
from app.framework_source_view import project_framework_sources
from app.models import (
    AgentAsset,
    Deployment,
    Evidence,
    RoleSkillSelectionObservation,
    RuntimeBinding,
    SkillInstallation,
    SkillManifestObservation,
)
from app.role_skill_roots import parse_role_skill_roots, validate_role_skill_roots
from app.role_skill_selection import RoleSkillSelection
from app.security import Identity

SCHEMA_VERSION = "enterprise-binding-evidence-readiness/v2"

# 维度状态词表（固定五值；不设“部分通过”，也不给总体通过/不通过结论）。
VERIFIED = "verified_from_records"
INCONSISTENT = "records_inconsistent"
MISSING = "evidence_missing"
UNAVAILABLE = "source_unavailable"
NOT_ESTABLISHED = "capability_not_established"
STATES = (VERIFIED, INCONSISTENT, MISSING, UNAVAILABLE, NOT_ESTABLISHED)

DIMENSIONS = (
    "registered_identity",
    "device_origin",
    "role_skill_version",
    "execution_identity",
    "shared_impact",
)

# 固定原因码：v1 §4 加 v2 增量。
REASON_CODES = frozenset({
    "binding_not_registered_in_tenant",
    "binding_status_not_active",
    "registered_identity_changed",
    "registered_subject_unavailable",
    "no_recorded_framework_source",
    "framework_source_unverifiable",
    "device_revoked",
    "device_environment_outside_binding_environment",
    "asset_device_scope_absent",
    "no_layout_candidate_recorded",
    "layout_candidate_invalid",
    "no_recorded_declaration",
    "declaration_device_mismatch",
    "declaration_record_invalid",
    "no_installation_observation",
    "runtime_load_source_absent",
    "no_deployment_history_recorded",
    "current_readback_requires_live_probe",
    "target_authority_requires_live_connection_identity",
    "no_attestation_recorded",
    "attestation_not_independently_verified",
    "runtime_occupancy_source_absent",
    "target_registration_is_unique_per_tenant_backend_target",
    "subject_may_hold_multiple_target_registrations",
})

# 每个维度的固定“不得由此维度推导”结论码。
REGISTERED_IDENTITY_MUST_NOT_INFER = (
    "active_registration_is_not_runtime_attestation",
    "attestation_is_not_independent_verification",
)
DEVICE_ORIGIN_MUST_NOT_INFER = (
    "asset_device_link_is_not_binding_device_origin",
    "same_name_on_two_devices_must_not_merge",
    "device_link_does_not_prove_runtime_occupancy",
    "no_device_evidence_must_not_select_any_device",
)
ROLE_SKILL_MUST_NOT_INFER = (
    "layout_candidate_is_not_installation_or_load",
    "declared_names_are_not_installation_identity",
    "same_name_is_not_same_installation",
    "unconfigured_or_unsupported_is_not_zero_skills",
    "empty_declared_scope_is_not_no_installation",
    "no_installation_observation_is_not_no_installation",
    "manifest_sha256_is_not_package_version",
    "installation_observation_is_not_runtime_load",
    "no_load_record_is_not_no_skill",
)
EXECUTION_IDENTITY_MUST_NOT_INFER = (
    "historical_deployment_record_is_not_current_runtime_state",
    "historical_revision_is_not_current_revision",
    "current_revision_requires_live_readback",
    "authority_assignment_is_not_role_attribution",
    "attestation_is_not_independent_verification",
    "sandbox_permission_fact_is_not_binding_identity",
)
SHARED_IMPACT_MUST_NOT_INFER = (
    "single_registration_is_not_exclusive_occupancy",
    "registered_binding_only_is_not_full_coverage",
    "shared_runtime_occupants_remains_unknown",
    "skill_isolation_remains_not_established",
    "user_confirmation_is_not_evidence",
)


def _dimension(state, reasons=(), references=None, must_not_infer=()):
    return {
        "state": state,
        "reasons": sorted(reasons),
        "references": dict(references or {}),
        "must_not_infer": list(must_not_infer),
    }


def _iso(value):
    """与既有只读投影一致的输出格式（仓储内 naive UTC 约定）。"""
    return None if value is None else value.isoformat() + "Z"


def _tenant_of(identity: Identity) -> str:
    tenant_id = getattr(identity, "tenant_id", None)
    if not isinstance(tenant_id, str) or not tenant_id:
        raise ValueError("verified_tenant_identity_required")
    return tenant_id


def assess_binding_evidence(session: Session, identity: Identity, binding_id: str) -> dict:
    """只读评估一个已登记绑定的证据就绪度。

    `tenant_id` 只取自服务端验证身份；所有查询显式限定该租户。绑定缺失或属于其它租户时
    返回与“不存在”完全相同的 `evidence_missing`（不构成跨租户存在性判别）。
    """
    tenant_id = _tenant_of(identity)
    if not isinstance(binding_id, str) or not binding_id:
        raise ValueError("binding_id_required")
    # 全部查询在 no_autoflush 内：不隐式刷新调用方会话中的待提交状态，本模块不产生任何写入。
    with session.no_autoflush:
        return _assess(session, tenant_id, binding_id)


def _assess(session: Session, tenant_id: str, binding_id: str) -> dict:
    binding = session.scalar(select(RuntimeBinding).where(
        RuntimeBinding.id == binding_id, RuntimeBinding.tenant_id == tenant_id))
    registered = _assess_registered_identity(session, tenant_id, binding)

    asset = None
    source = None
    if registered["state"] == VERIFIED:
        asset = session.scalar(select(AgentAsset).where(
            AgentAsset.id == binding.asset_id, AgentAsset.tenant_id == tenant_id))
        if asset is not None:
            source = project_framework_sources(session, tenant_id, [asset])[asset.id]

    if asset is None or source is None:
        dimensions = {"registered_identity": registered}
        dimensions.update(_unavailable_dimensions())
        return _result(binding_id, dimensions)

    device_id = source["source"]["device_id"] if source["status"] == "historical_reported_source" else None
    return _result(binding_id, {
        "registered_identity": registered,
        "device_origin": _assess_device_origin(session, tenant_id, binding, asset, source),
        "role_skill_version": _assess_role_skill_version(session, tenant_id, asset, device_id),
        "execution_identity": _assess_execution_identity(session, tenant_id, binding),
        "shared_impact": _assess_shared_impact(session, tenant_id, binding),
    })


def _result(binding_id, dimensions):
    return {
        "schema_version": SCHEMA_VERSION,
        "binding_id": binding_id,
        "dimensions": dimensions,
        "coverage": "registered_binding_only",
        "shared_runtime_occupants": "unknown",
        "skill_isolation": "not_established",
        "execution_confirmation_supported": False,
    }


def _unavailable_dimensions():
    """登记来源不可用时，其余维度不展开子事实：原因是登记不可用，不是“这些维度无记录”。"""
    reason = ("registered_subject_unavailable",)
    return {
        "device_origin": _dimension(MISSING, reason, None, DEVICE_ORIGIN_MUST_NOT_INFER),
        "role_skill_version": _dimension(MISSING, reason, None, ROLE_SKILL_MUST_NOT_INFER),
        "execution_identity": _dimension(MISSING, reason, None, EXECUTION_IDENTITY_MUST_NOT_INFER),
        "shared_impact": _dimension(MISSING, reason, None, SHARED_IMPACT_MUST_NOT_INFER),
    }


def _assess_registered_identity(session, tenant_id, binding):
    if binding is None:
        return _dimension(MISSING, ("binding_not_registered_in_tenant",), None,
                          REGISTERED_IDENTITY_MUST_NOT_INFER)
    snapshot = snapshot_binding_identity(binding)
    try:
        require_binding_identity_unchanged(session, snapshot, tenant_id)
    except HTTPException as exc:
        # 复用既有执行前复验的固定拒绝码，只映射为本层的就绪度状态；不采用新值、不重试。
        if exc.detail == "binding_revoked":
            reasons = ("binding_status_not_active",)
        else:
            reasons = ("registered_identity_changed",)
        return _dimension(INCONSISTENT, reasons, {"binding_id": binding.id},
                          REGISTERED_IDENTITY_MUST_NOT_INFER)
    return _dimension(VERIFIED, (), {
        "binding_id": binding.id,
        "environment_id": snapshot["environment_id"],
        "asset_id": snapshot["asset_id"],
        "agent_instance_id": snapshot["agent_instance_id"],
        "backend_target_id": snapshot["backend_target_id"],
    }, REGISTERED_IDENTITY_MUST_NOT_INFER)


def _assess_device_origin(session, tenant_id, binding, asset, source):
    mn = DEVICE_ORIGIN_MUST_NOT_INFER
    status = source["status"]
    if status == "no_recorded_source":
        return _dimension(MISSING, ("no_recorded_framework_source",),
                          {"framework_source_status": status}, mn)
    if status != "historical_reported_source":
        # 含悬挂引用与其它租户设备：本层不做跨租户读取，故统一为来源不可核对。
        return _dimension(UNAVAILABLE, ("framework_source_unverifiable",),
                          {"framework_source_status": status}, mn)
    data = source["source"]
    references = {
        "framework_source_status": status,
        "asset_device_id": data["device_id"],
        "device_environment_id": data["environment_id"],
        "device_revoked": data["device_revoked"],
        "device_scoped_evidence_count": _device_evidence_count(session, tenant_id, asset),
    }
    if data["device_revoked"]:
        return _dimension(UNAVAILABLE, ("device_revoked",), references, mn)
    if data["environment_id"] != binding.environment_id:
        return _dimension(UNAVAILABLE, ("device_environment_outside_binding_environment",),
                          references, mn)
    return _dimension(VERIFIED, (), references, mn)


def _device_evidence_count(session, tenant_id, asset):
    evidence_ids = list(asset.evidence_ids or [])
    if not evidence_ids:
        return 0
    return session.scalar(
        select(func.count())
        .select_from(Evidence)
        .where(
            Evidence.tenant_id == tenant_id,
            Evidence.evidence_id.in_(evidence_ids),
            asset_evidence_device_filter(asset),
        )
    ) or 0


def _assess_role_skill_version(session, tenant_id, asset, device_id):
    subfacts = {
        "directory_candidate": _directory_candidate(asset),
        "declared_selection": _declared_selection(session, tenant_id, asset, device_id),
        "installation_observation": _installation_observation(session, tenant_id, device_id),
        # 运行时实际加载没有任何采集/存储来源：这是能力未建立，不是“缺一条记录”。
        "runtime_load": {"state": NOT_ESTABLISHED, "reason": "runtime_load_source_absent"},
    }
    # 维度状态：任一记录矛盾 → 记录不一致；任一记录缺口 → 缺失证据；记录齐全但所需结论
    # （实际加载的确切 Skill/角色版本）仍不可建立 → 能力尚未建立。
    states = [sub["state"] for key, sub in subfacts.items() if key != "runtime_load"]
    if INCONSISTENT in states:
        state = INCONSISTENT
    elif MISSING in states:
        state = MISSING
    else:
        state = NOT_ESTABLISHED
    return _dimension(state, _sub_reasons(subfacts), {"subfacts": subfacts},
                      ROLE_SKILL_MUST_NOT_INFER)


def _sub_reasons(subfacts):
    """列出所有未达 `verified_from_records` 的子事实原因码（即就绪度不足的全部原因）。"""
    return {sub["reason"] for sub in subfacts.values()
            if sub["state"] != VERIFIED and sub.get("reason") is not None}


def _directory_candidate(asset):
    attributes = asset.attributes if isinstance(asset.attributes, dict) else {}
    raw = attributes.get("skill_source_roots")
    if raw is None:
        return {"state": MISSING, "reason": "no_layout_candidate_recorded"}
    try:
        validate_role_skill_roots([asset])
        roots = parse_role_skill_roots(
            raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        )
    except (HTTPException, ValueError, TypeError, AttributeError, RecursionError):
        return {"state": INCONSISTENT, "reason": "layout_candidate_invalid"}
    return {
        "state": VERIFIED,
        "roots_basis": roots.get("basis"),
        "roots_status": roots.get("status"),
        "root_count": len(roots.get("roots") or []),
    }


def _declared_selection(session, tenant_id, asset, device_id):
    if device_id is None:
        return {"state": MISSING, "reason": "asset_device_scope_absent"}
    scope = (
        RoleSkillSelectionObservation.tenant_id == tenant_id,
        RoleSkillSelectionObservation.asset_id == asset.id,
    )
    mismatch = session.scalar(
        select(func.count())
        .select_from(RoleSkillSelectionObservation)
        .where(*scope, RoleSkillSelectionObservation.edge_agent_id != device_id)
    ) or 0
    if mismatch:
        # 同一资产存在来自其它设备的声明记录：不得合并归属。
        return {"state": INCONSISTENT, "reason": "declaration_device_mismatch",
                "other_device_declaration_count": mismatch}
    row = session.execute(
        select(RoleSkillSelectionObservation)
        .where(*scope, RoleSkillSelectionObservation.edge_agent_id == device_id)
        .order_by(RoleSkillSelectionObservation.received_at.desc(),
                  RoleSkillSelectionObservation.id.desc())
        .limit(1)
    ).scalars().first()
    if row is None:
        return {"state": MISSING, "reason": "no_recorded_declaration"}
    if asset.framework != "openclaw" or asset.source_type != "openclaw_agent":
        return {"state": INCONSISTENT, "reason": "declaration_record_invalid"}
    count = session.scalar(
        select(func.count())
        .select_from(RoleSkillSelectionObservation)
        .where(*scope, RoleSkillSelectionObservation.edge_agent_id == device_id)
    ) or 0
    try:
        selection = RoleSkillSelection.model_validate(row.selection)
    except (ValueError, TypeError, RecursionError):
        return {"state": INCONSISTENT, "reason": "declaration_record_invalid"}
    return {
        "state": VERIFIED,
        "declaration_count": count,
        "latest_observed_at": _iso(row.observed_at),
        "task_id": row.task_id,
        "batch_digest": row.batch_digest,
        "declaration_status": selection.status,
        "declaration_source": selection.source,
        # 只给数量，不给名称列表：同名不能代替精确安装归属。
        "declaration_name_count": len(selection.names),
    }


def _installation_observation(session, tenant_id, device_id):
    if device_id is None:
        return {"state": MISSING, "reason": "asset_device_scope_absent"}
    scoped = (
        SkillInstallation.tenant_id == tenant_id,
        SkillInstallation.edge_agent_id == device_id,
    )
    installation_count = session.scalar(
        select(func.count()).select_from(SkillInstallation).where(*scoped)
    ) or 0
    observed_count = session.scalar(
        select(func.count(distinct(SkillManifestObservation.installation_id)))
        .select_from(SkillManifestObservation)
        .join(SkillInstallation, SkillInstallation.id == SkillManifestObservation.installation_id)
        .where(SkillManifestObservation.tenant_id == tenant_id, *scoped)
    ) or 0
    row = session.execute(
        select(
            SkillManifestObservation.installation_id,
            SkillManifestObservation.manifest_sha256,
            SkillManifestObservation.parse_status,
            SkillManifestObservation.parser_version,
            SkillManifestObservation.observed_at,
        )
        .join(SkillInstallation, SkillInstallation.id == SkillManifestObservation.installation_id)
        .where(SkillManifestObservation.tenant_id == tenant_id, *scoped)
        .order_by(SkillManifestObservation.observed_at.desc(),
                  SkillManifestObservation.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return {"state": MISSING, "reason": "no_installation_observation",
                "installation_count": installation_count}
    return {
        "state": VERIFIED,
        "installation_count": installation_count,
        "observed_installation_count": observed_count,
        "latest_observation": {
            "installation_id": row[0],
            "manifest_sha256": row[1],
            "parse_status": row[2],
            "parser_version": row[3],
            "observed_at": _iso(row[4]),
        },
    }


def _assess_execution_identity(session, tenant_id, binding):
    scoped = (
        Deployment.tenant_id == tenant_id,
        Deployment.runtime_binding_id == binding.id,
    )
    row = session.execute(
        select(
            Deployment.status,
            Deployment.to_revision,
            Deployment.created_at,
            Deployment.receipt.is_not(None),
            Deployment.verification.is_not(None),
        )
        .where(*scoped)
        .order_by(Deployment.created_at.desc(), Deployment.id.desc())
        .limit(1)
    ).first()
    if row is None:
        revision_history = {"state": MISSING, "reason": "no_deployment_history_recorded"}
    else:
        # 只读存在性标志，不载入回执/验证正文。
        revision_history = {
            "state": VERIFIED,
            "count": session.scalar(
                select(func.count()).select_from(Deployment).where(*scoped)) or 0,
            "latest_to_revision": row[1],
            "latest_status": row[0],
            "latest_created_at": _iso(row[2]),
            "has_receipt": bool(row[3]),
            "has_verification": bool(row[4]),
        }
    attestation_present = bool(binding.attestation)
    subfacts = {
        "revision_history": revision_history,
        # 当前 revision 需经适配器实时读回；本层不发起探测，也不用历史记录替代当前状态。
        "current_revision_readback": {"state": NOT_ESTABLISHED,
                                     "reason": "current_readback_requires_live_probe"},
        "target_authority": {"state": NOT_ESTABLISHED,
                             "reason": "target_authority_requires_live_connection_identity"},
        "operator_attestation": {
            "state": UNAVAILABLE if attestation_present else MISSING,
            "reason": "attestation_not_independently_verified" if attestation_present
                      else "no_attestation_recorded",
            "present": attestation_present,
        },
    }
    # 记录类子事实（历史 revision、人工 attestation）任一无记录 → 缺失证据；其余情况为
    # 能力尚未建立（当前读回与目标授权没有来源，人工 attestation 也不能升格为独立核验）。
    record_states = (revision_history["state"], subfacts["operator_attestation"]["state"])
    state = MISSING if MISSING in record_states else NOT_ESTABLISHED
    return _dimension(state, _sub_reasons(subfacts), {"subfacts": subfacts},
                      EXECUTION_IDENTITY_MUST_NOT_INFER)


def _assess_shared_impact(session, tenant_id, binding):
    # 登记层事实：同一主体可登记到多个不同目标，且同（租户,后端,目标）结构上只有一条登记，
    # 因此“查不到第二条绑定”恒真，不构成独占证据。
    count = session.scalar(
        select(func.count())
        .select_from(RuntimeBinding)
        .where(
            RuntimeBinding.tenant_id == tenant_id,
            RuntimeBinding.agent_instance_id == binding.agent_instance_id,
            RuntimeBinding.status == "active",
        )
    ) or 0
    return _dimension(
        NOT_ESTABLISHED,
        (
            "runtime_occupancy_source_absent",
            "target_registration_is_unique_per_tenant_backend_target",
            "subject_may_hold_multiple_target_registrations",
        ),
        {"registered_active_targets_for_subject": count},
        SHARED_IMPACT_MUST_NOT_INFER,
    )
