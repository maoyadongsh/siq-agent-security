"""RuntimeBinding 管理路由（P0-1：策略 selector 与运行时目标强绑定）。

绑定登记 = 声明「该租户的某 agent 实例在某环境下对应某后端运行时目标」。
部署只接受 active 绑定并服务端解析 target；backend_target_id 登记后不可变，
变更目标 = 吊销旧绑定 + 登记新绑定（全量审计）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AgentAsset, AgentInstance, Environment, RuntimeBinding, utcnow
from app.outbox import audit, emit_event
from app.schemas import RuntimeBindingCreate, RuntimeBindingOut
from app.security import Identity, ensure_permission, get_identity, require_permission

router = APIRouter(tags=["runtime-bindings"])


@router.post("/api/v1/runtime-bindings", response_model=RuntimeBindingOut, status_code=201)
def create_runtime_binding(
    body: RuntimeBindingCreate,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("policy:manage")),
):
    # 跨租户/不存在统一 404（隐藏存在性，§21.1 不变量 #1）
    instance = session.scalar(
        select(AgentInstance).where(
            AgentInstance.id == body.agent_instance_id, AgentInstance.tenant_id == identity.tenant_id
        )
    )
    if instance is None:
        raise HTTPException(status_code=404, detail="not_found")
    asset = session.scalar(
        select(AgentAsset).where(AgentAsset.id == instance.asset_id, AgentAsset.tenant_id == identity.tenant_id)
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="not_found")
    env = session.scalar(
        select(Environment).where(
            Environment.id == body.environment_id, Environment.tenant_id == identity.tenant_id
        )
    )
    if env is None:
        raise HTTPException(status_code=404, detail="not_found")

    binding = RuntimeBinding(
        tenant_id=identity.tenant_id,
        environment_id=env.id,
        agent_instance_id=instance.id,
        asset_id=asset.id,
        backend=body.backend,
        backend_target_id=body.backend_target_id,
        attestation=body.attestation,
        status="active",
    )
    session.add(binding)
    try:
        session.flush()  # binding.id 为 insert 期默认，审计/事件需要真实 ID
    except IntegrityError:
        # (tenant_id, backend, backend_target_id) 唯一：同一目标重复登记拒绝
        session.rollback()
        raise HTTPException(status_code=409, detail="binding_target_conflict") from None
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "binding.create",
        "runtime_binding",
        resource_id=binding.id,
        summary={"backend": binding.backend, "backend_target_id": binding.backend_target_id},
    )
    emit_event(
        session,
        identity.tenant_id,
        "runtime_binding.created.v1",
        {
            "binding_id": binding.id,
            "agent_instance_id": instance.id,
            "asset_id": asset.id,
            "backend": binding.backend,
            "backend_target_id": binding.backend_target_id,
        },
        environment_id=env.id,
        resource_ref=binding.id,
    )
    session.commit()
    session.refresh(binding)
    return binding


@router.get("/api/v1/runtime-bindings", response_model=list[RuntimeBindingOut])
def list_runtime_bindings(
    cursor: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """绑定列表：租户隔离 + 游标分页（对齐策略列表语义）。"""
    ensure_permission(identity, "policy:read")
    query = (
        select(RuntimeBinding)
        .where(RuntimeBinding.tenant_id == identity.tenant_id)
        .order_by(RuntimeBinding.created_at.desc(), RuntimeBinding.id)
    )
    if cursor:
        from datetime import datetime as _dt

        try:
            ts, rid = cursor.split("|", 1)
            ctime = _dt.fromisoformat(ts)
            query = query.where(
                (RuntimeBinding.created_at < ctime)
                | ((RuntimeBinding.created_at == ctime) & (RuntimeBinding.id > rid))
            )
        except ValueError:
            query = query.where(RuntimeBinding.id > cursor)
    return list(session.scalars(query.limit(min(limit, 200))))


@router.post("/api/v1/runtime-bindings/{binding_id}/revoke", response_model=RuntimeBindingOut)
def revoke_runtime_binding(
    binding_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    # 先租户定位（404）再权限（403）：跨租户 ID 猜测与不存在不可区分
    binding = session.scalar(
        select(RuntimeBinding).where(
            RuntimeBinding.id == binding_id, RuntimeBinding.tenant_id == identity.tenant_id
        )
    )
    if binding is None:
        raise HTTPException(status_code=404, detail="not_found")
    ensure_permission(identity, "policy:manage")
    if binding.status != "active":
        raise HTTPException(status_code=409, detail="invalid_state")
    binding.status = "revoked"
    binding.revoked_at = utcnow()
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "binding.revoke",
        "runtime_binding",
        resource_id=binding.id,
        summary={"backend": binding.backend, "backend_target_id": binding.backend_target_id},
    )
    emit_event(
        session,
        identity.tenant_id,
        "runtime_binding.revoked.v1",
        {"binding_id": binding.id, "backend": binding.backend, "backend_target_id": binding.backend_target_id},
        environment_id=binding.environment_id,
        resource_ref=binding.id,
    )
    session.commit()
    session.refresh(binding)
    return binding
