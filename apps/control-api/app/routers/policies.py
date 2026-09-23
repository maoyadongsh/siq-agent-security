"""策略、变更与部署路由（设计文档 §14）。

职责分离（§19.3）：批准者不得是提出者本人。
enforcement_mode 只允许升级路径：audit_only → warn → block，降级必须走新变更并审批。
Phase 3 之前：策略发布只生成 EdgeTask 占位，真实编译由 OpenShell Adapter 交付。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.db import get_session
from app.list_meta import apply_list_meta, clamp_limit, take_page
from app.models import (
    AgentAsset,
    AgentInstance,
    ChangeRequest,
    Deployment,
    DeploymentSubmission,
    DesiredPolicy,
    EdgeTask,
    Environment,
    QuarantineCase,
    RuntimeBinding,
    new_id,
    utcnow,
)
from app.outbox import audit, emit_event
from app.safe_errors import error_reference
from app.schemas import (
    ChangeRequestCreate,
    ChangeRequestOut,
    DeploymentCreate,
    DeploymentOut,
    PolicyCreate,
    PolicyOut,
)
from app.security import Identity, ensure_permission, get_identity, require_permission

router = APIRouter(tags=["policies"])

_MODE_RANK = {"audit_only": 0, "warn": 1, "block": 2}


def _policy_or_404(session: Session, tenant_id: str, policy_id: str) -> DesiredPolicy:
    policy = session.scalar(
        select(DesiredPolicy).where(DesiredPolicy.id == policy_id, DesiredPolicy.tenant_id == tenant_id)
    )
    if policy is None:
        raise HTTPException(status_code=404, detail="not_found")
    return policy


def _validate_policy_static(policy: DesiredPolicy) -> list[str]:
    """静态校验（Phase 0 版）：selector 必填、enforcement_mode 合法、secret 不落明文。"""
    errors: list[str] = []
    if not policy.selector or not policy.selector.get("agent_ids"):
        errors.append("selector.agent_ids 不能为空")
    if policy.enforcement_mode not in _MODE_RANK:
        errors.append("enforcement_mode 非法")
    for secret in policy.secrets or []:
        if "ref" not in secret or "purpose" not in secret:
            errors.append("secrets[] 必须含 ref 与 purpose，禁止明文")
    return errors


def _ensure_binding_in_selector(
    session: Session, tenant_id: str, policy: DesiredPolicy, binding: RuntimeBinding
) -> None:
    """selector 与绑定的运行时强绑定校验（P0-1，fail-closed）。

    selector.agent_ids 允许填资产 id 或该资产下实例 id；任一 id 在本租户内
    无法解析为已知资产/实例即拒绝（防止 selector 拼写漂移导致策略落空），
    且绑定的 asset/instance 必须命中 selector。
    """
    agent_ids = [str(aid) for aid in (policy.selector or {}).get("agent_ids") or []]
    if agent_ids:
        known: set[str] = set(
            session.scalars(
                select(AgentAsset.id).where(AgentAsset.tenant_id == tenant_id, AgentAsset.id.in_(agent_ids))
            )
        )
        known |= set(
            session.scalars(
                select(AgentInstance.id).where(AgentInstance.tenant_id == tenant_id, AgentInstance.id.in_(agent_ids))
            )
        )
        if any(aid not in known for aid in agent_ids):
            raise HTTPException(status_code=409, detail="selector_unknown_agent_id")
    if binding.asset_id not in agent_ids and binding.agent_instance_id not in agent_ids:
        raise HTTPException(status_code=409, detail="binding_not_in_policy_selector")


@router.get("/api/v1/policies", response_model=list[PolicyOut])
def list_policies(
    cursor: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """策略中心列表（§20.1）：租户隔离 + 游标分页。"""
    ensure_permission(identity, "policy:read")
    query = (
        select(DesiredPolicy)
        .where(DesiredPolicy.tenant_id == identity.tenant_id)
        .order_by(DesiredPolicy.updated_at.desc(), DesiredPolicy.id)
    )
    if cursor:
        from datetime import datetime as _dt

        try:
            ts, rid = cursor.split("|", 1)
            ctime = _dt.fromisoformat(ts)
            query = query.where(
                (DesiredPolicy.updated_at < ctime) | ((DesiredPolicy.updated_at == ctime) & (DesiredPolicy.id > rid))
            )
        except ValueError:
            query = query.where(DesiredPolicy.id > cursor)
    return list(session.scalars(query.limit(min(limit, 200))))


@router.get("/api/v1/change-requests", response_model=list[ChangeRequestOut])
def list_change_requests(
    response: Response,
    status_filter: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """变更中心列表（§20.1）。DEV13-D：截断元数据走响应头。"""
    ensure_permission(identity, "policy:read")
    query = select(ChangeRequest).where(ChangeRequest.tenant_id == identity.tenant_id)
    if status_filter:
        query = query.where(ChangeRequest.status == status_filter)
    query = query.order_by(ChangeRequest.created_at.desc(), ChangeRequest.id)
    if cursor:
        from datetime import datetime as _dt

        try:
            ts, rid = cursor.split("|", 1)
            ctime = _dt.fromisoformat(ts)
            query = query.where(
                (ChangeRequest.created_at < ctime) | ((ChangeRequest.created_at == ctime) & (ChangeRequest.id > rid))
            )
        except ValueError:
            query = query.where(ChangeRequest.id > cursor)
    page_limit = clamp_limit(limit)
    rows = list(session.scalars(query.limit(page_limit + 1)))
    page, truncated = take_page(rows, limit=page_limit)
    next_cursor = None
    if truncated and page:
        last = page[-1]
        next_cursor = f"{last.created_at.isoformat()}|{last.id}"
    apply_list_meta(
        response,
        limit=page_limit,
        returned=len(page),
        truncated=truncated,
        next_cursor=next_cursor,
    )
    return page


@router.get("/api/v1/deployments", response_model=list[DeploymentOut])
def list_deployments(
    cursor: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """部署列表（§20.1）。"""
    ensure_permission(identity, "policy:read")
    query = (
        select(Deployment)
        .where(Deployment.tenant_id == identity.tenant_id)
        .order_by(Deployment.created_at.desc(), Deployment.id)
    )
    if cursor:
        from datetime import datetime as _dt

        try:
            ts, rid = cursor.split("|", 1)
            ctime = _dt.fromisoformat(ts)
            query = query.where(
                (Deployment.created_at < ctime) | ((Deployment.created_at == ctime) & (Deployment.id > rid))
            )
        except ValueError:
            query = query.where(Deployment.id > cursor)
    return list(session.scalars(query.limit(min(limit, 200))))


@router.post("/api/v1/policies", response_model=PolicyOut, status_code=201)
def create_policy(
    body: PolicyCreate,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("policy:manage")),
):
    policy = DesiredPolicy(id=new_id("pol"), tenant_id=identity.tenant_id, **body.model_dump())
    errors = _validate_policy_static(policy)
    policy.status = "validated" if not errors else "draft"
    if errors:
        policy.unsupported_by_backend = errors  # 校验错误显式展示，不静默
    session.add(policy)
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "policy.create",
        "desired_policy",
        resource_id=policy.id,
    )
    session.commit()
    session.refresh(policy)
    return policy


@router.post("/api/v1/policies/{policy_id}/validate", response_model=PolicyOut)
def validate_policy(
    policy_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    # 先租户定位（404）再权限（403）：跨租户 ID 猜测与不存在不可区分
    policy = _policy_or_404(session, identity.tenant_id, policy_id)
    ensure_permission(identity, "policy:manage")
    errors = _validate_policy_static(policy)
    policy.status = "validated" if not errors else "draft"
    policy.unsupported_by_backend = errors
    session.commit()
    session.refresh(policy)
    return policy


@router.post("/api/v1/change-requests", response_model=ChangeRequestOut, status_code=201)
def create_change_request(
    body: ChangeRequestCreate,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("change:propose")),
):
    policy = _policy_or_404(session, identity.tenant_id, body.policy_id)
    # Break-glass 需独立权限点（§19.2）：普通 proposer 自选 break_glass 直接 403，不豁免职责分离
    if body.approval_policy == "break_glass":
        ensure_permission(identity, "change:break_glass")
    existing = session.scalar(select(ChangeRequest).where(ChangeRequest.idempotency_key == body.idempotency_key))
    if existing is not None:
        if existing.tenant_id != identity.tenant_id:
            raise HTTPException(status_code=404, detail="not_found")
        return existing  # 幂等：重复提交返回既有变更单
    cr = ChangeRequest(
        id=new_id("cr"),
        tenant_id=identity.tenant_id,
        policy_id=policy.id,
        diff={"policy_version": policy.version, "enforcement_mode": policy.enforcement_mode},
        impact=body.impact,
        proposer_user_id=identity.actor_id,
        approval_policy=body.approval_policy,
        idempotency_key=body.idempotency_key,
    )
    session.add(cr)
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "change.request.create",
        "change_request",
        resource_id=cr.id,
    )
    emit_event(
        session,
        identity.tenant_id,
        "policy.change.requested.v1",
        {"change_request_id": cr.id, "policy_id": policy.id},
        resource_ref=cr.id,
    )
    session.commit()
    session.refresh(cr)
    return cr


@router.post("/api/v1/change-requests/{cr_id}/approve", response_model=ChangeRequestOut)
def approve_change_request(
    cr_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    cr = session.scalar(
        select(ChangeRequest).where(ChangeRequest.id == cr_id, ChangeRequest.tenant_id == identity.tenant_id)
    )
    if cr is None:
        raise HTTPException(status_code=404, detail="not_found")
    ensure_permission(identity, "change:approve")
    return _approve_change_request(cr, session, identity)


def _approve_change_request(
    cr: ChangeRequest, session: Session, identity: Identity, *, review_digest: str | None = None
):
    # 职责分离：提出者不能是唯一批准者（设计文档 §19.3）；break_glass 不豁免，仅允许跨人紧急批准
    if cr.proposer_user_id == identity.actor_id:
        raise HTTPException(status_code=409, detail="segregation_of_duties")
    if cr.status != "proposed":
        raise HTTPException(status_code=409, detail="invalid_state")

    # 降级审批（§14.2 修订语义）：enforcement_mode 只允许升级；降级必须 high_risk 变更单
    policy = session.get(DesiredPolicy, cr.policy_id)
    if policy is not None:
        previous = session.scalar(
            select(DesiredPolicy)
            .where(
                DesiredPolicy.tenant_id == identity.tenant_id,
                DesiredPolicy.name == policy.name,
                DesiredPolicy.version < policy.version,
            )
            .order_by(DesiredPolicy.version.desc())
        )
        if previous is not None and previous.status not in ("rejected", "failed"):
            if _MODE_RANK.get(policy.enforcement_mode, -1) < _MODE_RANK.get(previous.enforcement_mode, -1):
                if cr.approval_policy != "high_risk":
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "enforcement_downgrade_requires_high_risk: "
                            f"{previous.enforcement_mode} -> {policy.enforcement_mode}"
                        ),
                    )

    if cr.approval_policy == "break_glass":
        # 紧急变更：业务态 emergency_applied；复核正交挂起（DEV12-A / M-P4）
        import os
        from datetime import timedelta

        now = utcnow()
        ttl = int(os.getenv("SIQ_AS_BREAKGLASS_REVIEW_SECONDS", "86400"))
        cr.status = "emergency_applied"
        cr.approved_at = now
        cr.review_status = "pending"
        cr.review_due_at = now + timedelta(seconds=ttl)
        cr.reviewed_by = None
    else:
        cr.status = "approved"
        cr.approved_at = utcnow()
        cr.review_status = "none"
        cr.review_due_at = None
    cr.approver_user_id = identity.actor_id
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "change.approve",
        "change_request",
        resource_id=cr.id,
        summary={"approval_policy": cr.approval_policy, **({"review_digest": review_digest} if review_digest else {})},
    )
    emit_event(
        session,
        identity.tenant_id,
        "policy.change.approved.v1",
        {"change_request_id": cr.id, "approver": identity.actor_id, "approval_policy": cr.approval_policy},
        resource_ref=cr.id,
    )
    session.commit()
    session.refresh(cr)
    return cr


@router.post("/api/v1/change-requests/{cr_id}/reject", response_model=ChangeRequestOut)
def reject_change_request(
    cr_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    cr = session.scalar(
        select(ChangeRequest).where(ChangeRequest.id == cr_id, ChangeRequest.tenant_id == identity.tenant_id)
    )
    if cr is None:
        raise HTTPException(status_code=404, detail="not_found")
    ensure_permission(identity, "change:approve")
    return _reject_change_request(cr, session, identity)


def _reject_change_request(
    cr: ChangeRequest, session: Session, identity: Identity, *, review_digest: str | None = None
):
    if cr.status != "proposed":
        raise HTTPException(status_code=409, detail="invalid_state")
    cr.status = "rejected"
    cr.approver_user_id = identity.actor_id
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "change.reject",
        "change_request",
        resource_id=cr.id,
        summary={"review_digest": review_digest} if review_digest else None,
    )
    session.commit()
    session.refresh(cr)
    return cr


@dataclass
class PreparedDeployment:
    change: ChangeRequest
    environment: Environment
    policy: DesiredPolicy
    binding: RuntimeBinding
    backend: str
    task_payload: dict
    openshell_preflight: tuple | None
    backend_scope: dict


@router.post("/api/v1/deployments", response_model=DeploymentOut, status_code=201)
def create_deployment(
    body: DeploymentCreate,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    return execute_deployment(prepare_deployment(body, session, identity), session, identity)


def prepare_deployment(
    body: DeploymentCreate, session: Session, identity: Identity, *, extra_permissions: tuple[str, ...] = (),
    allowed_submission_id: str | None = None,
) -> PreparedDeployment:
    cr = session.scalar(
        select(ChangeRequest).where(
            ChangeRequest.id == body.change_request_id, ChangeRequest.tenant_id == identity.tenant_id
        ).with_for_update().execution_options(populate_existing=True)
    )
    if cr is None:
        raise HTTPException(status_code=404, detail="not_found")
    env = session.scalar(
        select(Environment).where(Environment.id == body.environment_id, Environment.tenant_id == identity.tenant_id)
    )
    if env is None:
        raise HTTPException(status_code=404, detail="not_found")
    policy = _policy_or_404(session, identity.tenant_id, cr.policy_id)

    # P0-1：部署目标只允许来自登记的 active RuntimeBinding（selector 与运行时强绑定），
    # 客户端不可指定 target；跨租户/不存在统一 404 隐藏存在性
    binding = session.scalar(
        select(RuntimeBinding).where(
            RuntimeBinding.id == body.binding_id, RuntimeBinding.tenant_id == identity.tenant_id
        )
    )
    if binding is None:
        raise HTTPException(status_code=404, detail="not_found")
    ensure_permission(identity, "policy:manage")
    for permission in extra_permissions:
        ensure_permission(identity, permission)
    existing_submission = session.scalar(select(DeploymentSubmission.id).where(
        DeploymentSubmission.tenant_id == identity.tenant_id,
        DeploymentSubmission.change_request_id == cr.id,
    ))
    if existing_submission is not None and existing_submission != allowed_submission_id:
        raise HTTPException(409, "deployment_submission_exists")
    if cr.status not in ("approved", "emergency_applied"):
        raise HTTPException(status_code=409, detail="change_not_approved")
    if env.mode != "enforce":
        raise HTTPException(status_code=409, detail="environment_not_in_enforce_mode")
    if binding.status != "active":
        raise HTTPException(status_code=409, detail="binding_revoked")
    if binding.environment_id != body.environment_id:
        raise HTTPException(status_code=409, detail="binding_environment_mismatch")
    # 隔离门禁：若目标资产当前处于隔离状态，禁止部署
    quarantine = session.scalar(
        select(QuarantineCase).where(
            QuarantineCase.tenant_id == identity.tenant_id,
            QuarantineCase.asset_id == binding.asset_id,
            QuarantineCase.status == "quarantined",
        )
    )
    if quarantine is not None:
        raise HTTPException(status_code=409, detail="asset_under_quarantine")

    _ensure_binding_in_selector(session, identity.tenant_id, policy, binding)
    target = binding.backend_target_id  # 服务端解析， Deployment.target 与适配器调用统一使用

    import os

    backend = os.getenv("SIQ_AS_ENFORCEMENT_BACKEND", "none")
    if backend == "none":
        raise HTTPException(status_code=409, detail="enforcement_backend_disabled")
    if backend == "fake":
        from app.config import load_settings

        if not load_settings().dev_mode:
            raise HTTPException(status_code=400, detail="fake_enforcement_backend_is_dev_only")
    if backend in ("fake", "openshell-cli") and binding.backend != backend:
        raise HTTPException(status_code=409, detail="binding_backend_mismatch")
    if backend == "openshell-cli" and policy.enforcement_mode != "block":
        # P1-11：openshell-cli 能力文档中仅 enforcement_mode.block=supported/enforce，
        # warn/audit_only 为 unsupported（无实测执行语义）；拒绝码引用能力文档结论
        raise HTTPException(
            status_code=422,
            detail=(
                f"capability_unsupported: enforcement_mode.{policy.enforcement_mode} "
                "(openshell-cli 能力文档仅支持 enforcement_mode.block)"
            ),
        )

    task_payload: dict = {
        "policy_id": policy.id,
        "enforcement_mode": policy.enforcement_mode,
    }
    openshell_preflight = None
    backend_scope = {}
    if backend == "openshell-cli":
        # plan_change 必须对照 live policy；compiler 的 needs_generation 只表示
        # 制品携带静态意图，不能以字段存在替代真实差异。
        from app.adapters.openshell.contracts import AdapterError, RevisionConflict, UnsupportedCapability

        try:
            adapter = OpenShellCliBackend()
            caps = adapter.probe()
            backend_scope = {
                "endpoint_fingerprint": caps.endpoint_fingerprint,
                "gateway": caps.handshake_gateway,
                "gateway_version": caps.gateway_version,
                "schema_version": caps.schema_version,
                "handshake_verified": caps.handshake_verified,
            }
            compiled = adapter.compile(_desired_from_policy(policy), caps)
            validation = adapter.validate(compiled)
            if not validation.valid:
                raise HTTPException(status_code=422, detail=f"compile_invalid: {validation.errors}")
            plan = adapter.plan_change(target, compiled)
        except UnsupportedCapability as exc:
            raise HTTPException(status_code=422, detail=f"compile_rejected: {exc}") from None
        except (AdapterError, RevisionConflict) as exc:
            error = error_reference(exc)
            raise HTTPException(
                status_code=502, detail=f"openshell_preflight_failed: {error['error_digest']}"
            ) from None
        task_payload["compiled"] = {
            "artifact_hash": compiled.artifact_hash,
            "backend": compiled.backend,
            "schema_version": compiled.schema_version,
            "needs_generation": plan.kind == "generation",
            "unsupported_by_backend": compiled.unsupported_by_backend,
        }
        if plan.kind == "generation":
            raise HTTPException(status_code=422, detail="static_generation_unavailable")
        openshell_preflight = (adapter, compiled, plan)
    else:
        # 非 CLI 后端保持原编译接线。CLI 已在上面用真实快照完成编译和计划。
        _compile_for_enforcement(policy, task_payload)

    return PreparedDeployment(cr, env, policy, binding, backend, task_payload, openshell_preflight, backend_scope)


def execute_deployment(
    prepared: PreparedDeployment, session: Session, identity: Identity, *, preview_digest: str | None = None,
    reserved_deployment: Deployment | None = None,
):
    from app.adapters.openshell.contracts import AdapterError, RevisionConflict

    cr, env, policy, binding = prepared.change, prepared.environment, prepared.policy, prepared.binding
    backend, task_payload, openshell_preflight = prepared.backend, prepared.task_payload, prepared.openshell_preflight
    target = binding.backend_target_id
    preview_audit = {"preview_digest": preview_digest} if preview_digest else {}
    deployment = reserved_deployment or Deployment(
        tenant_id=identity.tenant_id,
        environment_id=env.id,
        change_request_id=cr.id,
        target=target,
        runtime_binding_id=binding.id,
        to_revision=f"policy-{policy.version}",
        status="pending",
    )
    session.add(deployment)
    session.flush()  # deployment.id 为 insert 期默认，payload 需要真实 ID
    task_payload["deployment_id"] = deployment.id
    expires_at = utcnow() + timedelta(seconds=_task_ttl())

    if backend == "openshell-cli":
        # 真实闭环（2026-08-13 活网关验证）：审批后直接 policy set + 读回验证
        # 静态段一致（只改网络段）→ 动态热更新；验证通过才 effective（§21.1 不变量 #5）
        receipt = None
        try:
            assert openshell_preflight is not None
            adapter, compiled, plan = openshell_preflight
            receipt = adapter.apply_dynamic(target, plan, expected_revision=plan.expected_revision)
            # 完整 digest 是权威校验；host/port 只补充核对真实声明，不发明
            # 可能与策略冲突的固定 deny probe。
            allow = [r.get("endpoint") for r in (compiled.artifact.get("network_policies") or [])]
            checks = {"expect_allow": allow, "expect_deny": []}
            deployment.receipt = {
                "operation_id": receipt.operation_id,
                "target": receipt.target,
                "base_revision": receipt.base_revision,
                "base_policy_digest": receipt.base_policy_digest,
                "backend_revision": receipt.backend_revision,
                "applied_policy_digest": receipt.applied_policy_digest,
                "result": receipt.result,
                "gateway_policy_hash": receipt.evidence.get("gateway_policy_hash", ""),
            }
            deployment.from_revision = receipt.base_revision
            report = adapter.verify(target, checks, receipt)
            if not report.passed:
                raise AdapterError("openshell_post_apply_verification_failed")
            # P1-2：verification JSON 如实分级。当前 openShell 路径的 effective
            # 基于 readback（配置读回）验证——证明"后端配置与期望一致"，不证明
            # 行为执行；待行为 fixture 通道落地后才允许标 enforcement_verified。
            # deployment.status 语义不变（effective），验证强度以 level 字段区分。
            deployment.verification = {
                "level": report.level,
                "method": "config_readback",
                "allow_checks": report.allow_checks,
                "deny_checks": report.deny_checks,
            }
            deployment.status = "effective"
            cr.status = "effective"
            audit(
                session,
                identity.tenant_id,
                identity.identity_type,
                identity.actor_id,
                "deployment.verify",
                "deployment",
                resource_id=deployment.id,
                summary={
                    "backend_revision": receipt.backend_revision,
                    "method": "policy_readback",
                    "verification_level": report.level,
                    **preview_audit,
                },
            )
            emit_event(
                session,
                identity.tenant_id,
                "policy.deployment.verified.v1",
                {"deployment_id": deployment.id, "backend_revision": receipt.backend_revision},
                resource_ref=deployment.id,
            )
            session.commit()
            session.refresh(deployment)
            return deployment
        except (AdapterError, RevisionConflict) as exc:
            error = error_reference(exc)
            deployment.status = "failed"
            if receipt is None:
                deployment.receipt = error
            else:
                # policy set 已返回可信 operation binding 时不可用错误覆盖它；
                # failed deployment 仍可通过该绑定安全回滚。
                deployment.verification = {
                    **(deployment.verification or {}),
                    "apply_failed": error,
                    "backend_mutated": receipt.result == "applied",
                }
            audit(
                session,
                identity.tenant_id,
                identity.identity_type,
                identity.actor_id,
                "deployment.fail",
                "deployment",
                resource_id=deployment.id,
                summary={**error, **preview_audit},
            )
            emit_event(
                session,
                identity.tenant_id,
                "policy.deployment.failed.v1",
                {"deployment_id": deployment.id, **error},
                resource_ref=deployment.id,
            )
            session.commit()
            raise HTTPException(status_code=502, detail=f"openshell_apply_failed: {error['error_digest']}") from None

    # ── EdgeTask 占位通道（Phase 4 回执验证器落地前不可达 effective，保留为占位）──
    # 生产路径不可达：backend=none 在上方 409 拒绝；openshell-cli 走真实闭环并已返回。
    # 仅 dev/fake 后端可到达此处，且回执端（routers/environments.edge_post_receipt）对
    # publish_policy 一律置 failed（edge_publish_unsupported 常量语义），该通道永不能转 effective。
    # TODO(Phase 4)：回执验证器（制品哈希绑定 + 签名回执 + 活体探针）落地后，
    # 此处才可能成为真实 Edge 执行路径（docs/adr/0002-edge-trust-model.md、
    # docs/threat-model.md「部署回执独立验证」）。
    task = EdgeTask(
        environment_id=env.id,
        task_type="publish_policy",
        payload=task_payload,
        expires_at=expires_at,
    )
    session.add(task)
    session.flush()  # 获取 task.id 用于签名信封
    from app.signing import sign_task_payload

    task.signature = sign_task_payload(task.id, task.task_type, env.id, task.payload, expires_at.isoformat())
    deployment.edge_task_id = task.id
    cr.status = "deploying"
    deployment.status = "sent"
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "deployment.create",
        "deployment",
        resource_id=deployment.id,
        summary={"policy_id": policy.id, "environment_id": env.id, **preview_audit},
    )
    emit_event(
        session,
        identity.tenant_id,
        "policy.deployment.started.v1",
        {"deployment_id": deployment.id, "policy_id": policy.id, "environment_id": env.id},
        resource_ref=deployment.id,
    )
    session.commit()
    session.refresh(deployment)
    return deployment


@router.post("/api/v1/deployments/{deployment_id}/receipt-verify")
def verify_deployment_receipt_endpoint(
    deployment_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """P2 部署回执独立验证：控制面独立读回后端 revision 与 receipt 比对（只读执行面）。

    返回 attestation dict（同时写入 deployment.verification["independent_attestation"]）。
    """
    import os

    from app.deployment_verify import verify_deployment_receipt

    # 先租户定位（404）再权限（403）：跨租户 ID 猜测与不存在不可区分
    deployment = session.scalar(
        select(Deployment).where(Deployment.id == deployment_id, Deployment.tenant_id == identity.tenant_id)
    )
    if deployment is None:
        raise HTTPException(status_code=404, detail="not_found")
    ensure_permission(identity, "policy:read")  # 只读验证，不要求 policy:manage
    if os.getenv("SIQ_AS_ENFORCEMENT_BACKEND", "none") != "openshell-cli":
        raise HTTPException(status_code=409, detail="receipt_verify_backend_unsupported")
    attestation = verify_deployment_receipt(session, identity.tenant_id, deployment)
    session.commit()
    return attestation


def _task_ttl() -> int:
    from app.config import load_settings

    return load_settings().edge_task_ttl_seconds


def _desired_from_policy(policy: DesiredPolicy) -> dict:
    """DesiredPolicy 行 → 编译输入（§14.1 字段全集）。"""
    return {
        "policy_id": policy.id,
        "version": policy.version,
        "selector": policy.selector or {},
        "filesystem": policy.filesystem,
        "network": policy.network,
        "process": policy.process,
        "model_routing": policy.model_routing,
        "tools": policy.tools,
        "tool_policies": policy.tool_policies,
        "data_scope_refs": policy.data_scope_refs,
        "secrets": policy.secrets,
        "resources": policy.resources,
        "audit": policy.audit,
        "exceptions": policy.exceptions,
        "enforcement_mode": policy.enforcement_mode,
        "status": policy.status,
    }


def _compile_for_enforcement(policy: DesiredPolicy, task_payload: dict) -> None:
    """执行后端编译（env 开关）。未知语义拒绝（422），unsupported 显式入 payload。"""
    import os

    backend = os.getenv("SIQ_AS_ENFORCEMENT_BACKEND", "none")
    if backend == "none":
        return
    if backend == "fake":
        from app.adapters.openshell import FakeOpenShellBackend

        adapter = FakeOpenShellBackend()
    elif backend == "openshell-cli":
        # 真实网关（v0.0.83 实测：动态网络更新可用）；不可达 fail-closed
        # 使用模块级 OpenShellCliBackend（可 monkeypatch，测试不依赖真实网关）
        from app.adapters.openshell.contracts import AdapterError

        try:
            adapter = OpenShellCliBackend()
        except AdapterError as exc:
            raise HTTPException(status_code=502, detail=f"openshell_unreachable: {exc}") from None
    else:
        raise HTTPException(status_code=400, detail=f"unknown_enforcement_backend: {backend}")

    from app.adapters.openshell.contracts import UnsupportedCapability

    try:
        compiled = adapter.compile(_desired_from_policy(policy))
    except UnsupportedCapability as exc:
        raise HTTPException(status_code=422, detail=f"compile_rejected: {exc}") from None
    report = adapter.validate(compiled)
    if not report.valid:
        raise HTTPException(status_code=422, detail=f"compile_invalid: {report.errors}")
    task_payload["compiled"] = {
        "artifact_hash": compiled.artifact_hash,
        "backend": compiled.backend,
        "schema_version": compiled.schema_version,
        "needs_generation": compiled.needs_generation,
        "unsupported_by_backend": compiled.unsupported_by_backend,
    }


@router.post("/api/v1/deployments/{deployment_id}/rollback", response_model=DeploymentOut)
def rollback_deployment(
    deployment_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("policy:manage")),
):
    deployment = session.scalar(
        select(Deployment).where(Deployment.id == deployment_id, Deployment.tenant_id == identity.tenant_id)
    )
    if deployment is None:
        raise HTTPException(status_code=404, detail="not_found")
    if deployment.status not in ("effective", "sent", "failed"):
        raise HTTPException(status_code=409, detail="invalid_state")

    # 真实后端回滚（§14.4）：只恢复本进程本次 apply 绑定的精确前置快照。
    import os

    backend = os.getenv("SIQ_AS_ENFORCEMENT_BACKEND", "none")
    if backend == "openshell-cli":
        receipt = deployment.receipt or {}
        if deployment.status != "effective" and not (deployment.status == "failed" and receipt.get("operation_id")):
            raise HTTPException(status_code=409, detail="openshell_rollback_requires_effective_deployment")

        from app.adapters.openshell.contracts import (
            AdapterError,
            DeploymentReceipt,
            RollbackAuthorization,
            VerificationFailed,
        )

        def authorize_rollback(_authorization: RollbackAuthorization) -> bool:
            """写前重新查询当前授权链；不使用申请中的 evidence 决定可否回滚。"""
            ensure_permission(identity, "policy:manage")
            session.expire_all()
            live_binding = session.scalar(
                select(RuntimeBinding).where(
                    RuntimeBinding.id == deployment.runtime_binding_id,
                    RuntimeBinding.tenant_id == identity.tenant_id,
                )
            )
            if (
                live_binding is None
                or live_binding.status != "active"
                or live_binding.backend != "openshell-cli"
                or live_binding.backend_target_id != deployment.target
            ):
                return False
            live_cr = session.scalar(
                select(ChangeRequest).where(
                    ChangeRequest.id == deployment.change_request_id,
                    ChangeRequest.tenant_id == identity.tenant_id,
                )
            )
            if live_cr is None or live_cr.status not in {"approved", "effective"}:
                return False
            live_policy = session.scalar(
                select(DesiredPolicy).where(
                    DesiredPolicy.id == live_cr.policy_id,
                    DesiredPolicy.tenant_id == identity.tenant_id,
                )
            )
            if live_policy is None or live_policy.status in {"rejected", "failed", "superseded", "rolled_back"}:
                return False
            try:
                _ensure_binding_in_selector(session, identity.tenant_id, live_policy, live_binding)
            except HTTPException:
                return False
            return True

        try:
            rollback_receipt = OpenShellCliBackend().rollback(
                deployment.target,
                DeploymentReceipt(
                    backend_revision=str(receipt.get("backend_revision", "")),
                    operation_id=str(receipt.get("operation_id", "")),
                    target=str(receipt.get("target", "")),
                    base_revision=str(receipt.get("base_revision", "")),
                    base_policy_digest=str(receipt.get("base_policy_digest", "")),
                    applied_policy_digest=str(receipt.get("applied_policy_digest", "")),
                    result=str(receipt.get("result", "")),
                    evidence=receipt,
                ),
                authorizer=authorize_rollback,
            )
            deployment.verification = {
                **(deployment.verification or {}),
                "rollback": {
                    "restored_revision": rollback_receipt.restored_revision,
                    "restored_digest": rollback_receipt.restored_digest,
                    "result": rollback_receipt.result,
                },
            }
        except (AdapterError, VerificationFailed) as exc:
            error = error_reference(exc)
            deployment.verification = {
                **(deployment.verification or {}),
                "rollback_failed": error,
            }
            audit(
                session,
                identity.tenant_id,
                identity.identity_type,
                identity.actor_id,
                "deployment.rollback_fail",
                "deployment",
                resource_id=deployment.id,
                summary=error,
            )
            session.commit()
            raise HTTPException(
                status_code=502,
                detail=f"openshell_rollback_failed: {error['error_digest']}",
            ) from None

    cr = session.get(ChangeRequest, deployment.change_request_id)
    if cr is not None:
        cr.status = "rolled_back"
    deployment.status = "rolled_back"
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "deployment.rollback",
        "deployment",
        resource_id=deployment.id,
    )
    session.commit()
    session.refresh(deployment)
    return deployment
