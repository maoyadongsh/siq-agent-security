"""API 请求/响应 Pydantic 模型。信任边界：所有入参经 Pydantic 校验。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EnvironmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    env_type: str = Field(default="host", pattern="^(host|container|k8s|account)$")
    mode: str = Field(default="discovery", pattern="^(discovery|observe|recommend|enforce)$")
    risk_level: str = Field(default="medium", pattern="^(low|medium|high)$")


class EnvironmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    name: str
    env_type: str
    mode: str
    risk_level: str
    last_heartbeat_at: datetime | None


class EnrollmentCreate(BaseModel):
    """创建 Edge 一次性注册码。"""


class EnrollmentOut(BaseModel):
    code: str  # 明文仅本次返回
    expires_at: datetime


class EdgeRegisterRequest(BaseModel):
    enrollment_code: str
    device_identity: str = Field(min_length=8, max_length=128)
    public_key_pem: str = Field(min_length=1, max_length=8192)  # Phase 0+ 接真实验签时收紧为合法 PEM 校验
    version: str = Field(max_length=32)
    capabilities: dict = Field(default_factory=dict)


class EdgeRegisterOut(BaseModel):
    edge_agent_id: str
    device_secret: str  # 明文仅本次返回
    control_plane_public_key: str  # Edge 钉住，用于任务验签（ADR-002 / T5）
    environment_id: str  # 任务信封含环境绑定（防跨环境重放）
    expires_at: datetime | None = None


class EdgeHeartbeatRequest(BaseModel):
    version: str = Field(max_length=32)
    metrics: dict = Field(default_factory=dict)


class EdgeTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    environment_id: str
    task_type: str
    payload: dict
    signature: str | None
    expires_at: datetime


class EdgeReceiptRequest(BaseModel):
    status: str = Field(pattern="^(success|failed)$")
    summary: dict = Field(default_factory=dict)
    # 回执必须含可机器校验证据（设计文档 §21.1 不变量 #5）：如后端 revision、快照哈希
    verification: dict | None = None


class CandidateConfirm(BaseModel):
    role: str | None = Field(default=None, max_length=128)
    system_id: str | None = None
    owner_user_id: str | None = None


class CandidateDismiss(BaseModel):
    reason: str = Field(min_length=1, max_length=512)
    expires_at: datetime | None = None


class AgentAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    role: str | None
    framework: str
    status: str
    system_id: str | None
    owner_user_id: str | None
    source_type: str | None
    source_locator: str | None
    updated_at: datetime


class EvidenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_type: str
    source_locator: str
    subject_ref: str | None
    observed_at: datetime
    collected_at: datetime
    collector_id: str
    connector_version: str
    content_hash: str
    redaction_profile: str
    classification: str
    payload_ref: str | None
    expires_at: datetime | None


class PermissionFactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    subject_type: str
    subject_id: str
    delegated_user: dict | None
    domain: str
    action: str
    resource_type: str
    resource_value: str
    effect: str
    conditions: dict
    state: str
    authority: str
    authority_revision: str | None
    evidence_ids: list
    valid_from: datetime | None
    valid_until: datetime | None


class ScanCreate(BaseModel):
    environment_id: str
    scope: dict = Field(default_factory=dict)


class ScanOut(BaseModel):
    task_id: str


class FindingAcceptRisk(BaseModel):
    owner_user_id: str
    reason: str = Field(min_length=1, max_length=512)
    expires_at: datetime


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    rule_id: str
    rule_version: int
    severity: str
    domain: str | None
    asset_id: str | None
    evidence_ids: list
    impact: str | None
    remediation: str | None
    status: str
    owner_user_id: str | None
    due_at: datetime | None
    risk_acceptance: dict | None
    first_seen_at: datetime
    last_seen_at: datetime


class PolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    selector: dict
    filesystem: dict | None = None
    network: list | None = None
    process: dict | None = None
    model_routing: dict | None = None
    tools: list | None = None
    tool_policies: dict | None = None
    data_scope_refs: list | None = None
    secrets: list | None = None
    resources: dict | None = None
    audit: dict | None = None
    exceptions: list | None = None
    enforcement_mode: str = Field(default="audit_only", pattern="^(audit_only|warn|block)$")


class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    selector: dict
    enforcement_mode: str
    version: int
    status: str
    unsupported_by_backend: list
    updated_at: datetime


class ChangeRequestCreate(BaseModel):
    policy_id: str
    idempotency_key: str = Field(min_length=8, max_length=128)
    impact: dict = Field(default_factory=dict)
    approval_policy: str = Field(default="standard", pattern="^(standard|high_risk|break_glass)$")


class ChangeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    policy_id: str
    proposer_user_id: str
    approver_user_id: str | None
    approval_policy: str
    status: str
    idempotency_key: str
    created_at: datetime


class DeploymentCreate(BaseModel):
    change_request_id: str
    environment_id: str
    target: str = Field(max_length=128)


class DeploymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    environment_id: str
    change_request_id: str
    target: str
    from_revision: str | None
    to_revision: str
    status: str
    verification: dict | None


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    actor_type: str
    actor_id: str
    action: str
    resource_type: str
    resource_id: str | None
    decision: str
    request_id: str | None
    summary: dict
    created_at: datetime
