"""Revalidate registered identity references, without inventing runtime attestation."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AgentAsset, AgentInstance, RuntimeBinding

# 固定部署目标与登记来源的不可变标量集；准备阶段校验过的身份以此为准。
SNAPSHOT_FIELDS = ("status", "environment_id", "asset_id", "agent_instance_id", "backend", "backend_target_id")


def require_binding_source_identity(session: Session, binding: RuntimeBinding, tenant_id: str) -> None:
    if _source_identity_missing(
        session, binding.agent_instance_id, binding.asset_id, binding.environment_id, tenant_id
    ):
        raise HTTPException(status_code=409, detail="binding_source_identity_changed")


def snapshot_binding_identity(binding: RuntimeBinding) -> dict:
    """准备阶段校验通过的绑定身份标量副本（普通 dict，不随 ORM 对象漂移）。"""
    return {"id": binding.id, **{field: getattr(binding, field) for field in SNAPSHOT_FIELDS}}


def require_binding_identity_unchanged(session: Session, snapshot: dict, tenant_id: str) -> None:
    """执行副作用前按当前持久状态复验绑定（fail-closed）。

    列级查询不经 ORM identity map；tenant 谓词只来自验证身份，不信任准备结果
    中的对象。漂移即拒绝旧准备结果：不采用新值、不重编译、不回写绑定、不恢复
    吊销。复验之后与外部写入之间的残余竞态不由此消除（需后续锁/租约协议）。
    """
    row = session.execute(
        select(
            RuntimeBinding.status,
            RuntimeBinding.environment_id,
            RuntimeBinding.asset_id,
            RuntimeBinding.agent_instance_id,
            RuntimeBinding.backend,
            RuntimeBinding.backend_target_id,
        ).where(RuntimeBinding.id == snapshot["id"], RuntimeBinding.tenant_id == tenant_id)
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=409, detail="binding_source_identity_changed")
    if row["status"] != "active":
        raise HTTPException(status_code=409, detail="binding_revoked")
    if any(row[field] != snapshot[field] for field in SNAPSHOT_FIELDS):
        raise HTTPException(status_code=409, detail="binding_source_identity_changed")
    if _source_identity_missing(session, row["agent_instance_id"], row["asset_id"], row["environment_id"], tenant_id):
        raise HTTPException(status_code=409, detail="binding_source_identity_changed")


def _source_identity_missing(
    session: Session, instance_id: str, asset_id: str, environment_id: str, tenant_id: str
) -> bool:
    return (
        session.execute(
            select(AgentInstance.id)
            .join(AgentAsset, AgentInstance.asset_id == AgentAsset.id)
            .where(
                AgentInstance.id == instance_id,
                AgentInstance.tenant_id == tenant_id,
                AgentAsset.id == asset_id,
                AgentAsset.tenant_id == tenant_id,
                AgentInstance.environment_id == environment_id,
            )
        ).first()
        is None
    )
