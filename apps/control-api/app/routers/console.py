"""Read-only console context derived from the verified request identity."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Tenant
from app.security import Identity, get_identity

router = APIRouter(tags=["console"])

ROLE_LABELS = {
    "tenant_admin": ("组织管理员", "具备组织管理权限；角色分配由组织身份系统处理。"),
    "security_admin": ("安全管理员", "管理策略与风险，审核安全变更。"),
    "platform_operator": ("平台运维人员", "接入环境、注册设备并管理采集。"),
    "agent_owner": ("智能体负责人", "核对资产并提出变更；不自动获得策略批准权。"),
    "reviewer": ("审批人", "批准已授权的变更；进入变更清单还需策略读取权限。"),
    "auditor": ("审计员", "读取资产、策略与审计记录。"),
    "viewer": ("只读查看者", "读取资产和策略，不处理候选或批准变更。"),
    "admin": ("管理员", "按已验证的管理权限访问控制台。"),
}


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TenantContext(Wire):
    id: str = Field(min_length=1, max_length=256)
    name: str | None = Field(max_length=128)


class ActorContext(Wire):
    id: str = Field(min_length=1, max_length=256)
    type: Literal["user", "service"]


class ConsoleRole(Wire):
    code: str = Field(min_length=1, max_length=256)
    label: str = Field(min_length=1, max_length=256)
    description: str = Field(max_length=256)


class ConsoleAccess(Wire):
    workspace: bool = True
    overview: bool
    agents: bool
    permissions: bool
    findings: bool
    policies: bool
    changes: bool
    runtime_bindings: bool
    environments: bool
    audit: bool
    settings: bool = True


class ConsoleActions(Wire):
    confirm_assets: bool
    manage_environment: bool
    enroll_devices: bool
    manage_policy: bool
    propose_change: bool
    approve_change: bool


class ConsoleContext(Wire):
    schema_version: Literal["console-context/v1"] = "console-context/v1"
    evaluated_at: datetime
    tenant: TenantContext
    actor: ActorContext
    authentication: Literal["development_headers", "verified_token"]
    roles: list[ConsoleRole] = Field(max_length=8)
    custom_role_count: int = Field(ge=0)
    access: ConsoleAccess
    actions: ConsoleActions


@router.get("/api/v1/console-context", response_model=ConsoleContext)
def console_context(
    request: Request,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    from app.config import load_settings

    tenant = session.get(Tenant, identity.tenant_id)
    can = identity.has_permission
    return ConsoleContext(
        evaluated_at=datetime.now(UTC),
        tenant=TenantContext(id=identity.tenant_id, name=tenant.name if tenant else None),
        actor=ActorContext(id=identity.actor_id, type=identity.identity_type),
        authentication="development_headers"
        if load_settings().dev_mode and request.headers.get("X-Dev-Tenant-Id")
        else "verified_token",
        roles=[
            ConsoleRole(code=code, label=ROLE_LABELS[code][0], description=ROLE_LABELS[code][1])
            for code in sorted(identity.roles)
            if code in ROLE_LABELS
        ],
        custom_role_count=sum(code not in ROLE_LABELS for code in identity.roles),
        access=ConsoleAccess(
            overview=all(can(p) for p in ("agent:read", "env:read", "policy:read")),
            agents=can("agent:read"),
            permissions=can("agent:read"),
            findings=can("agent:read"),
            policies=can("policy:read"),
            changes=can("policy:read"),
            runtime_bindings=can("policy:read"),
            environments=can("env:read"),
            audit=can("audit:read"),
        ),
        actions=ConsoleActions(
            confirm_assets=can("agent:confirm"),
            manage_environment=can("env:manage"),
            enroll_devices=can("edge:manage"),
            manage_policy=can("policy:manage"),
            propose_change=can("change:propose"),
            approve_change=can("change:approve"),
        ),
    )
