"""Preview and revalidate the same prepared deployment before any apply."""

import hashlib
import hmac
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.binding_identity import require_binding_identity_unchanged
from app.db import get_session
from app.models import ChangeRequest, DesiredPolicy, Environment, RuntimeBinding
from app.routers.change_review import _section
from app.routers.policies import PreparedDeployment, _desired_from_policy, execute_deployment, prepare_deployment
from app.rulepack import load_rulepack
from app.schemas import DeploymentCreate, DeploymentOut
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=["policies"])


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PreviewRequest(Wire):
    schema_version: Literal["deployment-preview-request/v1"]
    change_request_id: str = Field(min_length=1, max_length=64)
    environment_id: str = Field(min_length=1, max_length=64)
    binding_id: str = Field(min_length=1, max_length=64)


class PreviewSubmit(Wire):
    schema_version: Literal["deployment-preview-submit/v1"]
    change_request_id: str = Field(min_length=1, max_length=64)
    environment_id: str = Field(min_length=1, max_length=64)
    binding_id: str = Field(min_length=1, max_length=64)
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class DeploymentPreview(Wire):
    schema_version: Literal["deployment-preview/v1"] = "deployment-preview/v1"
    change_id: str = Field(min_length=1, max_length=64)
    policy_id: str = Field(min_length=1, max_length=64)
    policy_name: str = Field(min_length=1, max_length=128)
    policy_version: int = Field(ge=1)
    enforcement_mode: Literal["audit_only", "warn", "block"]
    environment_id: str = Field(min_length=1, max_length=64)
    environment_name: str = Field(min_length=1, max_length=128)
    binding_id: str = Field(min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=128)
    backend: Literal["fake", "openshell-cli"]
    action: Literal["development_task", "dynamic_update"]
    base_revision: str | None = Field(min_length=1, max_length=128)
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class BatchPreviewRequest(Wire):
    schema_version: Literal["enterprise-deployment-batch-preview-request/v1"]
    items: list[PreviewRequest] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_targets(self):
        for field in ("binding_id", "change_request_id"):
            if len({getattr(item, field) for item in self.items}) != len(self.items):
                raise ValueError("duplicate preview target")
        return self


class BatchDeploymentPreview(Wire):
    schema_version: Literal["enterprise-deployment-batch-preview/v1"] = "enterprise-deployment-batch-preview/v1"
    items: list[DeploymentPreview]
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    batch_submission_supported: Literal[False] = False


def _locate_batch(body: BatchPreviewRequest, session: Session, identity: Identity) -> None:
    # Locate the complete tenant-owned set before permissions or external probes.
    # _prepare still rechecks each item; these reads are not a lock/snapshot claim.
    change_ids = {item.change_request_id for item in body.items}
    changes = session.execute(
        select(ChangeRequest.id, ChangeRequest.policy_id).where(
            ChangeRequest.tenant_id == identity.tenant_id, ChangeRequest.id.in_(change_ids)
        )
    ).all()
    if {row.id for row in changes} != change_ids:
        raise HTTPException(404, "not_found")
    for model, ids in (
        (DesiredPolicy, {row.policy_id for row in changes}),
        (Environment, {item.environment_id for item in body.items}),
        (RuntimeBinding, {item.binding_id for item in body.items}),
    ):
        found = set(session.scalars(select(model.id).where(model.tenant_id == identity.tenant_id, model.id.in_(ids))))
        if found != ids:
            raise HTTPException(404, "not_found")
    for permission in ("policy:manage", "policy:read", "env:read"):
        ensure_permission(identity, permission)


def _prepare(
    body: PreviewRequest | PreviewSubmit,
    session: Session,
    identity: Identity,
    *,
    allowed_submission_id: str | None = None,
) -> PreparedDeployment:
    try:
        return prepare_deployment(
            DeploymentCreate(
                change_request_id=body.change_request_id, environment_id=body.environment_id, binding_id=body.binding_id
            ),
            session,
            identity,
            extra_permissions=("policy:read", "env:read"),
            allowed_submission_id=allowed_submission_id,
        )
    except HTTPException as exc:
        # Keep stable codes; never echo arbitrary adapter/compile diagnostics into the dialog.
        code = str(exc.detail).split(":", 1)[0]
        allowed = {
            "not_found",
            "forbidden",
            "change_not_approved",
            "deployment_submission_exists",
            "environment_not_in_enforce_mode",
            "binding_revoked",
            "binding_environment_mismatch",
            "binding_source_identity_changed",
            "asset_under_quarantine",
            "selector_unknown_agent_id",
            "binding_not_in_policy_selector",
            "enforcement_backend_disabled",
            "binding_backend_mismatch",
            "fake_enforcement_backend_is_dev_only",
            "capability_unsupported",
            "compile_invalid",
            "compile_rejected",
            "openshell_preflight_failed",
            "deployment_target_identity_unconfirmed",
            "deployment_target_authority_unverified",
            "deployment_target_authority_changed",
            "static_generation_unavailable",
            "unknown_enforcement_backend",
        }
        raise HTTPException(exc.status_code, code if code in allowed else "deployment_preflight_failed") from None


def _snapshot(prepared: PreparedDeployment, identity: Identity) -> DeploymentPreview:
    cr, env, policy, binding = prepared.change, prepared.environment, prepared.policy, prepared.binding
    live = None
    if prepared.openshell_preflight:
        _, compiled, plan = prepared.openshell_preflight
        scope = prepared.backend_scope
        if not scope.get("endpoint_fingerprint") or scope.get("handshake_verified") is not True:
            raise HTTPException(409, "deployment_target_identity_unconfirmed")
        live = {
            "target": plan.target,
            "kind": plan.kind,
            "expected_revision": plan.expected_revision,
            "base_policy_digest": plan.base_policy_digest,
            "base_static_digest": plan.base_static_digest,
            "artifact_hash": compiled.artifact_hash,
            "network_change": plan.network_change,
        }
    _, _, rules = load_rulepack()
    for value in (policy.name, env.name, binding.backend_target_id):
        projected = _section("name", "name", value, rules)
        if projected.redacted or projected.truncated:
            raise HTTPException(409, "deployment_preview_content_unavailable")
    digest = hashlib.sha256(
        json.dumps(
            {
                "version": "deployment-preview/v1",
                "tenant": identity.tenant_id,
                "actor": identity.actor_id,
                "actor_type": identity.identity_type,
                "change": {
                    "id": cr.id,
                    "status": cr.status,
                    "approver": cr.approver_user_id,
                    "approved_at": cr.approved_at.isoformat() if cr.approved_at else None,
                    "approval_policy": cr.approval_policy,
                    "impact": cr.impact,
                    "diff": cr.diff,
                },
                "policy": _desired_from_policy(policy),
                "policy_name": policy.name,
                "environment": {"id": env.id, "name": env.name, "mode": env.mode, "type": env.env_type},
                "binding": {
                    "id": binding.id,
                    "environment": binding.environment_id,
                    "asset": binding.asset_id,
                    "instance": binding.agent_instance_id,
                    "backend": binding.backend,
                    "target": binding.backend_target_id,
                    "status": binding.status,
                    "attestation": binding.attestation,
                },
                "backend": prepared.backend,
                "backend_scope": prepared.backend_scope,
                "compiled": prepared.task_payload.get("compiled"),
                "live": live,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return DeploymentPreview(
        change_id=cr.id,
        policy_id=policy.id,
        policy_name=policy.name,
        policy_version=policy.version,
        enforcement_mode=policy.enforcement_mode,
        environment_id=env.id,
        environment_name=env.name,
        binding_id=binding.id,
        target=binding.backend_target_id,
        backend=prepared.backend,
        action="dynamic_update" if live else "development_task",
        base_revision=live["expected_revision"] if live else None,
        preview_digest=digest,
    )


@router.post("/api/v1/deployment-preview", response_model=DeploymentPreview)
def preview_deployment(
    body: PreviewRequest,
    response: Response,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    response.headers["Cache-Control"] = "no-store"
    prepared = _prepare(body, session, identity)
    # 准备完成后的登记身份复验：_prepare 的外部只读探测（openshell probe）期间可能有别的事务提交
    # 绑定吊销或身份/来源漂移，而 _snapshot 可能仍读到 prepared 的 ORM 缓存旧值，会返回
    # 漂移前的旧预览。按持久状态复验（复用执行前复验的同一函数与同一字段集），漂移即拒绝：
    # 不采用新值、不重编译、不返回过时预览。
    require_binding_identity_unchanged(session, prepared.binding_snapshot, identity.tenant_id)
    return _snapshot(prepared, identity)


@router.post("/api/v1/deployment-preview/submit", response_model=DeploymentOut, status_code=201)
def submit_deployment(
    body: PreviewSubmit, session: Session = Depends(get_session), identity: Identity = Depends(get_identity)
):
    prepared = _prepare(body, session, identity)
    current = _snapshot(prepared, identity)
    if not hmac.compare_digest(body.preview_digest, current.preview_digest):
        raise HTTPException(409, "deployment_preview_changed")
    return execute_deployment(prepared, session, identity, preview_digest=current.preview_digest)


@router.post("/api/v1/deployment-previews/batch", response_model=BatchDeploymentPreview)
def preview_deployment_batch(
    body: BatchPreviewRequest,
    response: Response,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    _locate_batch(body, session, identity)
    items = []
    targets = set()
    prepared_items = []
    for item in sorted(body.items, key=lambda item: item.binding_id):
        prepared = _prepare(item, session, identity)
        value = _snapshot(prepared, identity)
        target = (value.backend, value.target)
        if target in targets:
            raise HTTPException(409, "batch_preview_target_overlap")
        targets.add(target)
        prepared_items.append(prepared)
        items.append(value)
    # 全部外部准备完成之后、生成成功批次响应之前，对本批每个登记身份做最终复验：后续条目的
    # 外部只读探测可能已使前面条目失效，逐项在各自 prepare 之后立即复验覆盖不到这个跨条目窗口。
    # 任一条目漂移即拒绝，整批不返回成功预览；不复用漂移后的新身份、不重试、不重新 prepare。
    for prepared in prepared_items:
        require_binding_identity_unchanged(session, prepared.binding_snapshot, identity.tenant_id)
    digest = hashlib.sha256(
        json.dumps(
            {
                "schema_version": "enterprise-deployment-batch-preview/v1",
                "tenant": identity.tenant_id,
                "actor": identity.actor_id,
                "actor_type": identity.identity_type,
                "items": [item.model_dump() for item in items],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    response.headers["Cache-Control"] = "no-store"
    return BatchDeploymentPreview(items=items, preview_digest=digest)
