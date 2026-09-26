"""环境、Edge 注册、心跳与任务路由。

安全要点：
- 注册码一次性 + 短 TTL + 只存哈希（设计文档 §31.4 验收）；
- Edge secret 明文仅注册响应返回一次；
- Edge 任务按 environment 隔离，吊销 Edge 立即无法领取任务（在线校验）。
"""

from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import and_, func, or_, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.edge_capabilities import can_claim_skills, claimable_connectors
from app.list_meta import apply_list_meta, take_page
from app.models import (
    AuditEvent,
    Deployment,
    EdgeAgent,
    EdgeTask,
    EnrollmentToken,
    Environment,
    Evidence,
    new_id,
    utcnow,
)
from app.onboarding import OnboardingAccess, OnboardingDevice, OnboardingScan, OnboardingStatus
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
    mint_edge_device_secret,
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
    env = Environment(id=new_id("env"), tenant_id=identity.tenant_id, **body.model_dump())
    session.add(env)
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "environment.create",
        "environment",
        resource_id=env.id,
    )
    emit_event(
        session,
        identity.tenant_id,
        "environment.created.v1",
        {"environment_id": env.id},
        resource_ref=env.id,
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if session.scalar(select(Environment.id).where(
            Environment.tenant_id == identity.tenant_id, Environment.name == body.name
        )):
            raise HTTPException(status_code=409, detail="environment_name_conflict") from None
        raise
    session.refresh(env)
    return env


@router.get("/api/v1/environments", response_model=list[EnvironmentOut])
def list_environments(
    response: Response,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("env:read")),
    limit: int | None = Query(default=None, ge=1, le=200),
    cursor: str | None = Query(default=None, min_length=1, max_length=64),
    include_total: bool = False,
):
    filters = [Environment.tenant_id == identity.tenant_id]
    query = select(Environment).where(*filters).order_by(Environment.name, Environment.id)
    if cursor is not None:
        if limit is None:
            raise HTTPException(422, "environment_list_cursor_unavailable")
        anchor = session.scalar(select(Environment).where(*filters, Environment.id == cursor))
        if anchor is None:
            raise HTTPException(422, "environment_list_cursor_unavailable")
        query = query.where(or_(
            Environment.name > anchor.name,
            and_(Environment.name == anchor.name, Environment.id > anchor.id),
        ))
    total = session.scalar(select(func.count()).select_from(Environment).where(*filters)) if include_total else None
    rows = list(session.scalars(query.limit(limit + 1) if limit is not None else query))
    items, truncated = take_page(rows, limit=limit) if limit is not None else (rows, False)
    response.headers["Cache-Control"] = "no-store"
    apply_list_meta(
        response, limit=limit if limit is not None else len(items), returned=len(items),
        truncated=truncated, next_cursor=items[-1].id if truncated else None, total=total,
    )
    return items


@router.get("/api/v1/environments/access", response_model=OnboardingAccess)
def onboarding_access(identity: Identity = Depends(require_permission("env:read"))):
    return OnboardingAccess(
        can_create=identity.has_permission("env:manage"),
        can_enroll=identity.has_permission("edge:manage"),
        can_scan=identity.has_permission("env:manage"),
        can_view_assets=identity.has_permission("agent:read"),
    )


@router.get("/api/v1/environments/{environment_id}/onboarding", response_model=OnboardingStatus)
def environment_onboarding(
    environment_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    from app.config import load_settings

    env = _env_or_404(session, identity.tenant_id, environment_id)
    ensure_permission(identity, "env:read")
    now = utcnow()
    stale_seconds = load_settings().heartbeat_stale_seconds
    cutoff = now - timedelta(seconds=stale_seconds)
    count = session.scalar(select(func.count(EdgeAgent.id)).where(EdgeAgent.environment_id == env.id)) or 0
    edges = session.scalars(select(EdgeAgent).where(EdgeAgent.environment_id == env.id).order_by(
        EdgeAgent.registered_at.desc(), EdgeAgent.id
    ).limit(100))
    devices = []
    for edge in edges:
        state = "revoked" if edge.revoked_at else "waiting" if edge.last_seen_at is None else (
            "online" if cutoff <= edge.last_seen_at <= now else "stale"
        )
        declared = edge.capabilities.get("connectors", []) if isinstance(edge.capabilities, dict) else []
        connectors = [
            name for name in ("hermes", "openclaw", "directory", "docker")
            if isinstance(declared, list) and name in declared
        ]
        devices.append(OnboardingDevice(
            id=edge.id, device_identity=edge.device_identity, version=edge.version,
            registered_at=edge.registered_at, last_seen_at=edge.last_seen_at, status=state, connectors=connectors,
        ))
    tasks = list(session.scalars(select(EdgeTask).where(
        EdgeTask.environment_id == env.id, EdgeTask.task_type == "scan"
    ).order_by(EdgeTask.created_at.desc(), EdgeTask.id).limit(21)))
    summaries = {event.resource_id: event.summary for event in session.scalars(select(AuditEvent).where(
        AuditEvent.tenant_id == identity.tenant_id, AuditEvent.action == "edge.task.receipt",
        AuditEvent.resource_id.in_([task.id for task in tasks[:20]]),
    ).order_by(AuditEvent.created_at))}
    scans = []
    for task in tasks[:20]:
        summary = summaries.get(task.id, {})
        def total(key, values=summary):
            value = values.get(key)
            return value if type(value) is int and value >= 0 else None
        scans.append(OnboardingScan(
            id=task.id, connector=task.payload.get("connector") or "hermes",
            status="expired" if task.status in ("pending", "uploaded") and task.expires_at < now else task.status,
            created_at=task.created_at, expires_at=task.expires_at, device_identity=task.lease_owner,
            candidate_count=total("candidate_count"), evidence_count=total("evidence_count"),
        ))
    evidence_query = select(func.count(Evidence.id), func.max(Evidence.collected_at)).where(
        Evidence.tenant_id == identity.tenant_id, Evidence.environment_id == env.id
    )
    evidence_count, last_evidence = session.execute(evidence_query).one()
    return OnboardingStatus(
        environment_id=env.id, evaluated_at=now, heartbeat_stale_seconds=stale_seconds,
        device_count=count, devices=devices, devices_truncated=count > len(devices),
        evidence_count=evidence_count, last_evidence_at=last_evidence,
        scans=scans, scans_truncated=len(tasks) > 20,
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
    from app.config import load_settings
    from app.rate_limit import check_enrollment_create_rate

    env = _env_or_404(session, identity.tenant_id, environment_id)
    ensure_permission(identity, "edge:manage")
    allowed, retry_after = check_enrollment_create_rate(
        tenant_id=identity.tenant_id, environment_id=env.id
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="enrollment_create_rate_limited",
            headers={"Retry-After": str(retry_after)},
        )
    code = f"enr-{secrets.token_urlsafe(24)}"
    ttl = load_settings().enrollment_ttl_seconds
    token = EnrollmentToken(
        id=new_id("enr"),
        environment_id=env.id,
        code_hash=hash_secret(code),
        expires_at=utcnow() + timedelta(seconds=ttl),
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
        request_id=getattr(request.state, "request_id", None),
    )
    session.commit()
    return EnrollmentOut(code=code, expires_at=token.expires_at)


@router.post("/edge/v1/register", response_model=EdgeRegisterOut)
def register_edge(body: EdgeRegisterRequest, session: Session = Depends(get_session)):
    """Edge 使用一次性注册码换取设备身份与 secret。注册码不可重放。

    DEV11-B / M-P5b：重复 device_identity 返回受控 409，且不得消耗注册码。
    DEV11-E / M-P5d：按 device_identity 与 enrollment_code 限速（不按源 IP）。
    """
    from app.evidence_signing import load_edge_public_key
    from app.rate_limit import check_register_rate

    allowed, retry_after = check_register_rate(
        device_identity=body.device_identity, enrollment_code=body.enrollment_code
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="registration_rate_limited",
            headers={"Retry-After": str(retry_after)},
        )

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
    if body.expected_environment_id is not None and body.expected_environment_id != env.id:
        raise HTTPException(status_code=401, detail="enrollment_invalid")

    # 预检：避免唯一约束冲突变成 500，并在失败路径上不标记 used_at
    if session.scalar(select(EdgeAgent.id).where(EdgeAgent.device_identity == body.device_identity)):
        raise HTTPException(status_code=409, detail="device_identity_conflict")

    device_secret = mint_edge_device_secret()
    edge = EdgeAgent(
        id=new_id("edge"),
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
    audit(
        session,
        env.tenant_id,
        "edge",
        body.device_identity,
        "edge.register",
        "edge_agent",
        resource_id=edge.id,
    )
    try:
        session.commit()
    except IntegrityError:
        # 并发双注册同一身份：回滚使注册码仍可用
        session.rollback()
        raise HTTPException(status_code=409, detail="device_identity_conflict") from None
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
    env = session.get(Environment, edge.environment_id)
    if env is None:
        raise HTTPException(status_code=401, detail="edge_environment_missing")
    if body.capabilities is not None:
        capabilities = body.capabilities.model_dump(exclude_none=True)
        if capabilities != edge.capabilities:
            edge.capabilities = capabilities
            audit(
                session, env.tenant_id, "edge", edge.device_identity,
                "edge.capabilities.update", "edge_agent", resource_id=edge.id,
                summary={"connector_count": len(capabilities["connectors"]),
                         "inventory_schema": capabilities["inventory_schema"]},
            )
    edge.last_seen_at = now
    edge.version = body.version or edge.version
    if env is not None:
        env.last_heartbeat_at = now
    session.commit()
    return {"ok": True}


@router.get("/edge/v1/tasks", response_model=list[EdgeTaskOut])
def edge_fetch_tasks(request: Request, session: Session = Depends(get_session)):
    """领取任务（P1-5 原子 claim/lease）。

    候选 = 同环境、pending|uploaded、未过期，且（未租出 / 租约过期 / 本设备持有）。
    uploaded 表示 batch 已持久化、等待最终回执（R04）：允许原持有者或租约过期后
    的接管方再次领取，以便重传回执或在丢失本地 journal 时幂等重传 batch。

    对每个候选执行条件 UPDATE，rowcount==1 才真正领取成功：并发请求中只有
    一个能抢到同一任务（SQLite 单写者串行化同样保证该语义）。同一设备重复
    fetch（重试/重启）可拿回自己租约内的任务（at-least-once）。

    注意：lease 不是分布式锁的完整替代（时钟漂移/持有者进程暂停仍可能
    造成重复投递）；最终一致性由回执幂等（delivered/failed 终态去重）与
    batch result_digest 幂等保障。
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
    connectors = claimable_connectors(edge.capabilities, edge.last_seen_at, now, lease_cutoff)
    device_filter = or_(
        EdgeTask.payload["target_device_identity"].as_string().is_(None),
        EdgeTask.payload["target_device_identity"].as_string() == device_identity,
    )
    capability_filter = true() if connectors is None else or_(
        EdgeTask.task_type != "scan",
        EdgeTask.payload["connector"].as_string().in_(connectors),
        and_(EdgeTask.status == "uploaded", EdgeTask.lease_owner == device_identity),
    )
    skill_capable = can_claim_skills(edge.capabilities, edge.last_seen_at, now, lease_cutoff)
    capability_filter = and_(capability_filter, or_(
        EdgeTask.task_type != "skill_scan",
        and_(
            EdgeTask.payload["connector"].as_string() == "directory",
            EdgeTask.payload["inventory_kind"].as_string() == "skills",
            EdgeTask.payload["target_device_identity"].as_string() == device_identity,
            or_(
                and_(EdgeTask.status == "pending", skill_capable),
                and_(EdgeTask.status == "uploaded", EdgeTask.lease_owner == device_identity),
            ),
        ),
    ))
    # 过期任务顺带标记 expired（惰性清扫）：含 pending 与 uploaded（R04）
    session.query(EdgeTask).filter(
        EdgeTask.environment_id == edge.environment_id,
        EdgeTask.status.in_(("pending", "uploaded")),
        EdgeTask.expires_at < now,
    ).update({EdgeTask.status: "expired"})
    # 租约前提：未租出 / 租约缺少时间戳（防御）/ 租约过期 / 本设备持有
    claimable = or_(
        EdgeTask.lease_owner.is_(None),
        EdgeTask.leased_at.is_(None),
        EdgeTask.leased_at < lease_cutoff,
        EdgeTask.lease_owner == device_identity,
    )
    # pending：待执行；uploaded：结果已持久化、等待回执（R04 允许本设备或接管方再领）
    candidates = list(
        session.scalars(
            select(EdgeTask.id)
            .where(
                EdgeTask.environment_id == edge.environment_id,
                EdgeTask.status.in_(("pending", "uploaded")),
                claimable,
                capability_filter,
                device_filter,
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
            .where(
                EdgeTask.id == task_id,
                EdgeTask.environment_id == edge.environment_id,
                EdgeTask.status.in_(("pending", "uploaded")),
                claimable,
                capability_filter,
                device_filter,
            )
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
    if task.payload.get("target_device_identity") not in (None, device_identity):
        raise HTTPException(status_code=409, detail="receipt_task_device_mismatch")
    if body.task_id is not None and body.task_id != task.id:
        raise HTTPException(status_code=409, detail="receipt_task_mismatch")
    if body.device_identity is not None and body.device_identity != device_identity:
        raise HTTPException(status_code=409, detail="receipt_device_mismatch")
    if task.task_type == "skill_scan":
        from app.skill_receipt import complete_skill_task

        return complete_skill_task(session, edge, task, body)
    if body.skill_batch_digest is not None or body.skill_observation_count is not None:
        raise HTTPException(status_code=422, detail="skill_receipt_fields_not_allowed")
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
