"""环境、Edge 注册、心跳与任务路由。

安全要点：
- 注册码一次性 + 短 TTL + 只存哈希（设计文档 §31.4 验收）；
- Edge secret 明文仅注册响应返回一次；
- Edge 任务按 environment 隔离，吊销 Edge 立即无法领取任务（在线校验）。
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Deployment, EdgeAgent, EdgeTask, EnrollmentToken, Environment, utcnow
from app.outbox import audit, emit_event
from app.schemas import (
    EdgeHeartbeatRequest,
    EdgeReceiptRequest,
    EdgeRegisterOut,
    EdgeRegisterRequest,
    EdgeTaskOut,
    EnrollmentCreate,
    EnrollmentOut,
    EnvironmentCreate,
    EnvironmentModeUpdate,
    EnvironmentOut,
)
from app.security import (
    Identity,
    ensure_permission,
    get_identity,
    hash_secret,
    require_permission,
    verify_edge_secret,
)
from app.signing import public_key_base64

router = APIRouter(tags=["environments"])

# publish_policy 回执的部署处置是常量语义（Phase 4 回执验证器落地前恒 failed）：
# 当前 Edge 明确只实现 scan，publish_policy 成功回执不属于可信协议（设计文档 §21.1 不变量 #5）。
# TODO(Phase 4)：回执验证器（制品哈希绑定 + 签名回执 + 活体探针）落地后，
# 方可依据可机器校验证据决定 effective/failed（docs/adr/0002-edge-trust-model.md、
# docs/threat-model.md「部署回执独立验证」）；此前任何回执都不得转 effective（fail-closed）。
_EDGE_PUBLISH_RECEIPT_STATUS = "failed"


def _edge_publish_receipt_reason(status: str) -> str:
    """publish_policy 回执失败原因（常量语义，见 _EDGE_PUBLISH_RECEIPT_STATUS）。

    成功回执也标记 edge_publish_unsupported：回执验证器落地前，
    "成功"本身不构成可机器校验证据，不得与真实失败混同。
    """
    return "edge_publish_unsupported" if status == "success" else "edge_failure"


def _env_or_404(session: Session, tenant_id: str, environment_id: str) -> Environment:
    env = session.scalar(
        select(Environment).where(Environment.id == environment_id, Environment.tenant_id == tenant_id)
    )
    if env is None:
        # 跨租户与不存在统一 404，不泄露存在性（设计文档 §21.1 不变量 #1）
        raise HTTPException(status_code=404, detail="not_found")
    return env


@router.post("/api/v1/environments", response_model=EnvironmentOut, status_code=201)
def create_environment(
    body: EnvironmentCreate,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("env:manage")),
):
    env = Environment(tenant_id=identity.tenant_id, **body.model_dump())
    session.add(env)
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "environment.create",
        "environment",
    )
    emit_event(session, identity.tenant_id, "environment.created.v1", {"environment_id": env.id})
    session.commit()
    session.refresh(env)
    return env


@router.get("/api/v1/environments", response_model=list[EnvironmentOut])
def list_environments(
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("env:read")),
):
    return list(
        session.scalars(
            select(Environment).where(Environment.tenant_id == identity.tenant_id).order_by(Environment.name)
        )
    )


@router.patch("/api/v1/environments/{environment_id}/mode", response_model=EnvironmentOut)
def update_environment_mode(
    environment_id: str,
    body: EnvironmentModeUpdate,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """切换环境模式（discovery <-> enforce 等），受控治理动作。"""
    env = _env_or_404(session, identity.tenant_id, environment_id)
    ensure_permission(identity, "env:manage")
    old_mode = env.mode
    env.mode = body.mode
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "environment.mode.update",
        "environment",
        resource_id=env.id,
        summary={"old_mode": old_mode, "new_mode": env.mode, "reason": body.reason},
    )
    emit_event(
        session,
        identity.tenant_id,
        "environment.mode_updated.v1",
        {"environment_id": env.id, "old_mode": old_mode, "new_mode": env.mode},
        environment_id=env.id,
        resource_ref=env.id,
    )
    session.commit()
    session.refresh(env)
    return env


@router.post("/api/v1/environments/{environment_id}/edge-enrollment", response_model=EnrollmentOut)
def create_enrollment(
    environment_id: str,
    _body: EnrollmentCreate,
    request: Request,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    # 先租户定位（404）再权限（403）：跨租户 ID 猜测不可区分存在性
    env = _env_or_404(session, identity.tenant_id, environment_id)
    ensure_permission(identity, "edge:manage")
    code = f"enr-{secrets.token_urlsafe(24)}"
    token = EnrollmentToken(
        environment_id=env.id,
        code_hash=hash_secret(code),
        expires_at=utcnow() + timedelta(seconds=900),
        created_by=identity.actor_id,
    )
    session.add(token)
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "edge.enrollment.create",
        "environment",
        resource_id=environment_id,
        request_id=request.headers.get("X-Request-ID"),
    )
    session.commit()
    return EnrollmentOut(code=code, expires_at=token.expires_at)


@router.post("/edge/v1/register", response_model=EdgeRegisterOut)
def register_edge(body: EdgeRegisterRequest, session: Session = Depends(get_session)):
    """Edge 使用一次性注册码换取设备身份与 secret。注册码不可重放。"""
    from app.evidence_signing import load_edge_public_key

    try:
        load_edge_public_key(body.public_key_pem)
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_edge_public_key") from None
    now = utcnow()
    token = session.scalar(
        select(EnrollmentToken)
        .where(EnrollmentToken.code_hash == hash_secret(body.enrollment_code))
        .with_for_update()
    )
    if token is None or token.used_at is not None or token.expires_at < now:
        raise HTTPException(status_code=401, detail="enrollment_invalid")
    env = session.get(Environment, token.environment_id)
    if env is None:
        raise HTTPException(status_code=401, detail="enrollment_invalid")

    device_secret = f"edge-{secrets.token_urlsafe(32)}"
    edge = EdgeAgent(
        environment_id=env.id,
        device_identity=body.device_identity,
        secret_hash=hash_secret(device_secret),
        public_key_pem=body.public_key_pem,
        version=body.version,
        capabilities=body.capabilities,
    )
    token.used_at = now
    session.add(edge)
    session.add(token)
    audit(session, env.tenant_id, "edge", body.device_identity, "edge.register", "edge_agent")
    session.commit()
    return EdgeRegisterOut(
        edge_agent_id=edge.id,
        device_secret=device_secret,
        control_plane_public_key=public_key_base64(),
        environment_id=env.id,
    )


@router.post("/edge/v1/heartbeat")
def edge_heartbeat(
    body: EdgeHeartbeatRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    device_identity = request.headers.get("X-Edge-Identity")
    if not device_identity:
        raise HTTPException(status_code=401, detail="missing_edge_identity")
    edge = verify_edge_secret(request, device_identity, session)
    now = utcnow()
    edge.last_seen_at = now
    edge.version = body.version or edge.version
    env = session.get(Environment, edge.environment_id)
    if env is not None:
        env.last_heartbeat_at = now
    session.commit()
    return {"ok": True}


@router.get("/edge/v1/tasks", response_model=list[EdgeTaskOut])
def edge_fetch_tasks(request: Request, session: Session = Depends(get_session)):
    """领取任务（P1-5 原子 claim/lease）。

    候选 = 同环境、pending、未过期，且（未租出 / 租约过期 / 本设备持有）。
    对每个候选执行条件 UPDATE，rowcount==1 才真正领取成功：并发请求中只有
    一个能抢到同一任务（SQLite 单写者串行化同样保证该语义）。同一设备重复
    fetch（重试/重启）可拿回自己租约内的任务（at-least-once）。

    注意：lease 不是分布式锁的完整替代（时钟漂移/持有者进程暂停仍可能
    造成重复投递）；最终一致性由回执幂等（delivered/failed 终态去重）保障。
    """
    from app.config import load_settings

    device_identity = request.headers.get("X-Edge-Identity")
    if not device_identity:
        raise HTTPException(status_code=401, detail="missing_edge_identity")
    edge = verify_edge_secret(request, device_identity, session)
    now = utcnow()
    # 租约 TTL 复用心跳失活阈值：持有者宕机后至多一个 TTL 即可被接管
    lease_ttl_seconds = load_settings().heartbeat_stale_seconds
    lease_cutoff = now - timedelta(seconds=lease_ttl_seconds)
    # 过期任务顺带标记 expired（惰性清扫）
    session.query(EdgeTask).filter(
        EdgeTask.environment_id == edge.environment_id,
        EdgeTask.status == "pending",
        EdgeTask.expires_at < now,
    ).update({EdgeTask.status: "expired"})
    # 租约前提：未租出 / 租约缺少时间戳（防御）/ 租约过期 / 本设备持有
    claimable = or_(
        EdgeTask.lease_owner.is_(None),
        EdgeTask.leased_at.is_(None),
        EdgeTask.leased_at < lease_cutoff,
        EdgeTask.lease_owner == device_identity,
    )
    candidates = list(
        session.scalars(
            select(EdgeTask.id)
            .where(
                EdgeTask.environment_id == edge.environment_id,
                EdgeTask.status == "pending",
                claimable,
            )
            .order_by(EdgeTask.created_at)
            .limit(10)
        )
    )
    claimed: list[EdgeTask] = []
    for task_id in candidates:
        # 条件更新即领取：候选快照与更新之间被他人抢走时 rowcount==0，跳过
        result = session.execute(
            update(EdgeTask)
            .where(EdgeTask.id == task_id, EdgeTask.status == "pending", claimable)
            .values(
                leased_at=now,
                lease_owner=device_identity,
                attempt=EdgeTask.attempt + 1,
            )
        )
        if result.rowcount == 1:
            task = session.get(EdgeTask, task_id)
            if task is not None:
                claimed.append(task)
    session.commit()
    return claimed


@router.post("/edge/v1/tasks/{task_id}/receipt")
def edge_post_receipt(
    task_id: str,
    body: EdgeReceiptRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    """回执处理（设计文档 §21.1 不变量 #5）。

    部署任务（publish_policy）的成功回执必须携带可机器校验证据（verification），
    否则 Deployment 不得标记 effective（fail-closed，保留上一有效状态）。
    """
    from app.config import load_settings

    device_identity = request.headers.get("X-Edge-Identity")
    if not device_identity:
        raise HTTPException(status_code=401, detail="missing_edge_identity")
    edge = verify_edge_secret(request, device_identity, session)
    task = session.scalar(
        select(EdgeTask).where(
            EdgeTask.id == task_id,
            EdgeTask.environment_id == edge.environment_id,
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="not_found")
    if body.task_id is not None and body.task_id != task.id:
        raise HTTPException(status_code=409, detail="receipt_task_mismatch")
    if body.device_identity is not None and body.device_identity != device_identity:
        raise HTTPException(status_code=409, detail="receipt_device_mismatch")
    terminal_status = "delivered" if body.status == "success" else "failed"
    if task.status in ("delivered", "failed"):
        if task.status != terminal_status:
            raise HTTPException(status_code=409, detail="receipt_replay_conflict")
        return {"ok": True, "idempotent": True}
    if task.status == "expired" or task.expires_at < utcnow():
        raise HTTPException(status_code=409, detail="receipt_task_expired")
    # P1-5 租约一致性：任务被其他设备持有且租约未过期时，非持有者不得提交回执。
    # 放在终态幂等（delivered/failed 重放）与过期检查之后，既有重放/过期语义不变；
    # 租约过期或无租约的任务保持原有行为（任何本环境设备均可回执）。
    lease_ttl_seconds = load_settings().heartbeat_stale_seconds
    if (
        task.lease_owner is not None
        and task.lease_owner != device_identity
        and task.leased_at is not None
        and task.leased_at >= utcnow() - timedelta(seconds=lease_ttl_seconds)
    ):
        raise HTTPException(status_code=409, detail="receipt_lease_mismatch")
    if task.status not in ("pending", "uploaded"):
        raise HTTPException(status_code=409, detail="receipt_task_state_invalid")
    if task.task_type == "scan" and body.status == "success":
        if body.evidence_count != len(body.evidence_ids):
            raise HTTPException(status_code=422, detail="receipt_evidence_count_mismatch")
        if (body.candidate_count > 0 or body.evidence_count > 0) and task.status != "uploaded":
            raise HTTPException(status_code=409, detail="batch_upload_required")
    task.status = "delivered" if body.status == "success" else "failed"
    env = session.get(Environment, edge.environment_id)
    tenant_id = env.tenant_id if env else ""

    deployment = None
    if task.task_type == "publish_policy":
        deployment = session.scalar(
            select(Deployment).where(
                Deployment.edge_task_id == task.id,
                Deployment.tenant_id == tenant_id,
            )
        )
        if deployment is not None:
            verification = body.verification.model_dump(exclude_none=True) if body.verification else {}
            deployment.receipt = {
                "status": body.status,
                "error_code": body.error_code,
                **verification,
            }
            # 常量语义（Phase 4 回执验证器落地前）：publish_policy 回执一律置 failed，
            # 在 Edge 具备制品哈希绑定、签名回执和活体探针前，永不由该路径转 effective。
            deployment.status = _EDGE_PUBLISH_RECEIPT_STATUS
            reason = _edge_publish_receipt_reason(body.status)
            emit_event(
                session,
                tenant_id,
                "policy.deployment.failed.v1",
                {"deployment_id": deployment.id, "reason": reason},
                resource_ref=deployment.id,
            )

    audit(
        session,
        tenant_id,
        "edge",
        device_identity,
        "edge.task.receipt",
        "edge_task",
        resource_id=task_id,
        summary={
            "status": body.status,
            "error_code": body.error_code,
            "candidate_count": body.candidate_count,
            "evidence_count": body.evidence_count,
            "truncated": body.truncated,
            "verification_present": body.verification is not None,
            "deployment_id": deployment.id if deployment else None,
        },
    )
    session.commit()
    return {"ok": True}
