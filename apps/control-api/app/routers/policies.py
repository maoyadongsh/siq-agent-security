"""策略、变更与部署路由（设计文档 §14）。

职责分离（§19.3）：批准者不得是提出者本人。
enforcement_mode 只允许升级路径：audit_only → warn → block，降级必须走新变更并审批。
Phase 3 之前：策略发布只生成 EdgeTask 占位，真实编译由 OpenShell Adapter 交付。
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.db import get_session
from app.models import ChangeRequest, Deployment, DesiredPolicy, EdgeTask, Environment, utcnow
from app.outbox import audit, emit_event
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
    status_filter: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """变更中心列表（§20.1）。"""
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
    return list(session.scalars(query.limit(min(limit, 200))))


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
    policy = DesiredPolicy(tenant_id=identity.tenant_id, **body.model_dump())
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
    existing = session.scalar(
        select(ChangeRequest).where(ChangeRequest.idempotency_key == body.idempotency_key)
    )
    if existing is not None:
        if existing.tenant_id != identity.tenant_id:
            raise HTTPException(status_code=404, detail="not_found")
        return existing  # 幂等：重复提交返回既有变更单
    cr = ChangeRequest(
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
    identity: Identity = Depends(require_permission("change:approve")),
):
    cr = session.scalar(
        select(ChangeRequest).where(ChangeRequest.id == cr_id, ChangeRequest.tenant_id == identity.tenant_id)
    )
    if cr is None:
        raise HTTPException(status_code=404, detail="not_found")
    # 职责分离：提出者不能是唯一批准者（设计文档 §19.3）；Break-glass 是显式例外（§19.3 末条）
    if cr.proposer_user_id == identity.actor_id and cr.approval_policy != "break_glass":
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
        # 紧急变更：短期授权 + 事后复核标记（§19.3）
        cr.status = "emergency_applied"
    else:
        cr.status = "approved"
    cr.approver_user_id = identity.actor_id
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "change.approve",
        "change_request",
        resource_id=cr.id,
        summary={"approval_policy": cr.approval_policy},
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
    identity: Identity = Depends(require_permission("change:approve")),
):
    cr = session.scalar(
        select(ChangeRequest).where(ChangeRequest.id == cr_id, ChangeRequest.tenant_id == identity.tenant_id)
    )
    if cr is None:
        raise HTTPException(status_code=404, detail="not_found")
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
    )
    session.commit()
    session.refresh(cr)
    return cr


@router.post("/api/v1/deployments", response_model=DeploymentOut, status_code=201)
def create_deployment(
    body: DeploymentCreate,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("policy:manage")),
):
    cr = session.scalar(
        select(ChangeRequest).where(
            ChangeRequest.id == body.change_request_id, ChangeRequest.tenant_id == identity.tenant_id
        )
    )
    if cr is None:
        raise HTTPException(status_code=404, detail="not_found")
    if cr.status not in ("approved", "emergency_applied"):
        raise HTTPException(status_code=409, detail="change_not_approved")
    env = session.scalar(
        select(Environment).where(Environment.id == body.environment_id, Environment.tenant_id == identity.tenant_id)
    )
    if env is None:
        raise HTTPException(status_code=404, detail="not_found")
    policy = _policy_or_404(session, identity.tenant_id, cr.policy_id)
    deployment = Deployment(
        tenant_id=identity.tenant_id,
        environment_id=env.id,
        change_request_id=cr.id,
        target=body.target,
        to_revision=f"policy-{policy.version}",
        status="pending",
    )
    session.add(deployment)
    session.flush()  # deployment.id 为 insert 期默认，payload 需要真实 ID
    expires_at = utcnow() + timedelta(seconds=_task_ttl())
    task_payload: dict = {
        "policy_id": policy.id,
        "deployment_id": deployment.id,
        "enforcement_mode": policy.enforcement_mode,
    }
    # 执行后端编译接线：SIQ_AS_ENFORCEMENT_BACKEND 决定编译与发布路径
    _compile_for_enforcement(policy, task_payload)

    import os

    backend = os.getenv("SIQ_AS_ENFORCEMENT_BACKEND", "none")
    if backend == "openshell-cli":
        # 真实闭环（2026-08-13 活网关验证）：审批后直接 policy set + 读回验证
        # 静态段一致（只改网络段）→ 动态热更新；验证通过才 effective（§21.1 不变量 #5）
        from app.adapters.openshell.contracts import AdapterError, RevisionConflict

        try:
            adapter = OpenShellCliBackend()
            caps = adapter.probe()
            desired = _desired_from_policy(policy)
            compiled = adapter.compile(desired, caps)
            plan = adapter.plan_change(body.target, compiled)
            receipt = adapter.apply_dynamic(body.target, plan, expected_revision=plan.expected_revision)
            # 正负向验证：允许集=策略网络端点；拒绝集=合成未授权端点（block 模式下必须不在允许集）
            allow = [r.get("endpoint") for r in (compiled.artifact.get("network_policies") or [])]
            checks = {"expect_allow": allow, "expect_deny": ["10.255.255.255:1"]}
            report = adapter.verify(body.target, checks, receipt)
            if not report.passed:
                raise AdapterError(f"验证失败: {report.failures}")
            deployment.receipt = {
                "backend_revision": receipt.backend_revision,
                "snapshot_hash": receipt.evidence.get("snapshot_hash", ""),
            }
            deployment.verification = {"allow_checks": report.allow_checks, "deny_checks": report.deny_checks}
            deployment.status = "effective"
            cr.status = "effective"
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
            deployment.status = "failed"
            deployment.receipt = {"error": str(exc)[:300]}
            audit(
                session,
                identity.tenant_id,
                identity.identity_type,
                identity.actor_id,
                "deployment.fail",
                "deployment",
                resource_id=deployment.id,
                summary={"reason": str(exc)[:200]},
            )
            emit_event(
                session,
                identity.tenant_id,
                "policy.deployment.failed.v1",
                {"deployment_id": deployment.id, "reason": str(exc)[:200]},
                resource_ref=deployment.id,
            )
            session.commit()
            raise HTTPException(status_code=502, detail=f"openshell_apply_failed: {exc}") from None

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
        summary={"policy_id": policy.id, "environment_id": env.id},
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

    # 真实后端回滚（§14.4）：openshell-cli 模式恢复上一 revision（--rev 回读 + policy set）
    import os

    backend = os.getenv("SIQ_AS_ENFORCEMENT_BACKEND", "none")
    if backend == "openshell-cli" and deployment.status == "effective":
        from app.adapters.openshell.contracts import AdapterError, DeploymentReceipt, VerificationFailed

        receipt = deployment.receipt or {}
        try:
            rollback_receipt = OpenShellCliBackend().rollback(
                deployment.target,
                DeploymentReceipt(
                    backend_revision=str(receipt.get("backend_revision", "")),
                    evidence=receipt,
                ),
            )
            deployment.verification = {
                "rollback": {
                    "restored_revision": rollback_receipt.restored_revision,
                    "evidence": rollback_receipt.evidence,
                }
            }
        except (AdapterError, VerificationFailed) as exc:
            deployment.status = "failed"
            audit(
                session,
                identity.tenant_id,
                identity.identity_type,
                identity.actor_id,
                "deployment.rollback_fail",
                "deployment",
                resource_id=deployment.id,
                summary={"reason": str(exc)[:200]},
            )
            session.commit()
            raise HTTPException(status_code=502, detail=f"openshell_rollback_failed: {exc}") from None

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
