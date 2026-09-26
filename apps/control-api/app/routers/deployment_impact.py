"""Bound preview identity, with explicit unknown shared-runtime coverage."""

import hashlib
import hmac
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.routers.deployment_preview import (
    BatchPreviewRequest,
    DeploymentPreview,
    PreviewRequest,
    Wire,
    _locate_batch,
    _prepare,
    _snapshot,
)
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=["policies"])


class ImpactRequest(Wire):
    schema_version: Literal["enterprise-deployment-impact-request/v1"]
    change_request_id: str = Field(min_length=1, max_length=64)
    environment_id: str = Field(min_length=1, max_length=64)
    binding_id: str = Field(min_length=1, max_length=64)
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class RegisteredSubject(Wire):
    binding_id: str
    environment_id: str
    asset_id: str
    agent_instance_id: str


class DeploymentImpact(Wire):
    schema_version: Literal["enterprise-deployment-impact/v1"] = "enterprise-deployment-impact/v1"
    preview: DeploymentPreview
    registered_subject: RegisteredSubject
    coverage: Literal["registered_binding_only"] = "registered_binding_only"
    shared_runtime_occupants: Literal["unknown"] = "unknown"
    skill_isolation: Literal["not_established"] = "not_established"
    execution_confirmation_supported: Literal[False] = False
    impact_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


@router.post("/api/v1/deployment-preview/impact", response_model=DeploymentImpact)
def inspect_deployment_impact(
    body: ImpactRequest,
    response: Response,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    selection = PreviewRequest(
        schema_version="deployment-preview-request/v1",
        change_request_id=body.change_request_id,
        environment_id=body.environment_id,
        binding_id=body.binding_id,
    )
    # Locate before permissions; deny additional inventory reads before any external probe.
    _locate_batch(
        BatchPreviewRequest(schema_version="enterprise-deployment-batch-preview-request/v1", items=[selection]),
        session, identity,
    )
    ensure_permission(identity, "agent:read")
    prepared = _prepare(selection, session, identity)
    # 报告生成前复验：_prepare 的外部只读探测（openshell probe）期间可能有别的事务提交绑定
    # 吊销或身份/来源漂移；本请求会话的 ORM identity map 仍持有准备阶段的旧值，preview_digest
    # 与 registered_subject 都会从这份旧值产出，客户端提交的原摘要因此照样匹配。按持久状态
    # 复验（复用执行前复验的同一函数与同一字段集），漂移即拒绝：不采用新值、不重编译、
    # 不把漂移后的身份写成报告、不返回过时影响报告。
    from app.binding_identity import require_binding_identity_unchanged

    require_binding_identity_unchanged(session, prepared.binding_snapshot, identity.tenant_id)
    preview = _snapshot(prepared, identity)
    if not hmac.compare_digest(body.preview_digest, preview.preview_digest):
        raise HTTPException(409, "deployment_preview_changed")
    binding = prepared.binding
    result = DeploymentImpact(
        preview=preview,
        registered_subject=RegisteredSubject(
            binding_id=binding.id, environment_id=binding.environment_id,
            asset_id=binding.asset_id, agent_instance_id=binding.agent_instance_id,
        ),
        impact_digest="0" * 64,
    )
    content = result.model_dump(exclude={"impact_digest"})
    digest = hashlib.sha256(json.dumps(
        {"tenant": identity.tenant_id, "actor": identity.actor_id,
         "actor_type": identity.identity_type, "report": content},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    response.headers["Cache-Control"] = "no-store"
    return result.model_copy(update={"impact_digest": digest})
