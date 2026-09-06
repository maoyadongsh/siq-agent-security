"""API 请求/响应 Pydantic 模型。信任边界：所有入参经 Pydantic 校验。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

StrictModelConfig = ConfigDict(extra="forbid")


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


class EnvironmentModeUpdate(BaseModel):
    model_config = StrictModelConfig

    mode: str = Field(..., pattern="^(discovery|observe|recommend|enforce)$")
    reason: str = Field(..., min_length=1, max_length=256)


class AgentInstanceCreate(BaseModel):
    model_config = StrictModelConfig

    environment_id: str | None = Field(default=None, max_length=64)
    runtime: str = Field(default="hermes", max_length=32)
    version: str | None = Field(default=None, max_length=64)
    artifact_digest: str | None = Field(default=None, max_length=128)
    location: dict = Field(default_factory=dict)
    status: str = Field(default="observed", max_length=16)


class AgentInstanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    asset_id: str
    environment_id: str | None
    runtime: str
    version: str | None
    artifact_digest: str | None
    location: dict
    status: str
    observed_at: datetime


class EnrollmentCreate(BaseModel):
    """创建 Edge 一次性注册码。"""


class EnrollmentOut(BaseModel):
    code: str  # 明文仅本次返回
    expires_at: datetime


class EdgeRegisterRequest(BaseModel):
    model_config = StrictModelConfig

    enrollment_code: str
    device_identity: str = Field(min_length=8, max_length=128)
    public_key_pem: str = Field(min_length=1, max_length=8192)  # 注册路由会进一步校验为 Ed25519 PEM
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


class EdgeReceiptSummary(BaseModel):
    model_config = StrictModelConfig

    applied: bool | None = None


class EdgeReceiptVerification(BaseModel):
    model_config = StrictModelConfig

    backend_revision: str | None = Field(default=None, max_length=128)
    snapshot_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class EdgeReceiptRequest(BaseModel):
    model_config = StrictModelConfig

    task_id: str | None = Field(default=None, min_length=1, max_length=64)
    device_identity: str | None = Field(default=None, min_length=8, max_length=128)
    status: Literal["success", "failed"]
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=512)
    candidate_count: int = Field(default=0, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    evidence_ids: list[str] = Field(default_factory=list, max_length=10000)
    cursor: str | None = Field(default=None, max_length=512)
    truncated: bool = False
    completed_at: datetime | None = None
    # 旧版 publish_policy 回执字段仅保留到 Edge 发布协议正式上线；当前不能使部署 effective。
    summary: EdgeReceiptSummary = Field(default_factory=EdgeReceiptSummary)
    # 回执必须含可机器校验证据（设计文档 §21.1 不变量 #5）：如后端 revision、快照哈希
    verification: EdgeReceiptVerification | None = None


class CandidateConfirm(BaseModel):
    role: str | None = Field(default=None, max_length=128)
    system_id: str | None = Field(default=None, min_length=1, max_length=64)
    # 用户身份的存在性/归属由 SIQ IAM 保证，本服务不解析用户目录；此处只做格式约束
    owner_user_id: str | None = Field(
        default=None, min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]*$"
    )


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

    id: str = Field(validation_alias="evidence_id")
    observation_id: str
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
    environment_id: str | None
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


ConnectorName = Literal[
    "hermes",
    "openclaw",
    "docker",
    "directory",
    "systemd",
    "kubernetes",
    "process",
    "mcp",
    "piagent",
    "workbuddy",
    "dify",
]


class ScanCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment_id: str
    scope: dict = Field(default_factory=dict)
    connector: ConnectorName | None = None


class ScanOut(BaseModel):
    task_id: str


CandidateSourceType = Literal[
    "hermes_profile",
    "openclaw_agent",
    "directory_manifest",
    "docker",
    "kubernetes",
    "systemd",
    "siq_hub",
    "process_list",
    "human",
    "mcp_server",
    "piagent_profile",
    "workbuddy_profile",
    "dify_deployment",
]
EvidenceSourceType = Literal[
    "registry",
    "manifest",
    "openclaw_config",
    "process",
    "container",
    "k8s",
    "iam",
    "gateway",
    "openshell",
    "human",
    "deny_log",
    "systemd",
]


class EdgeCandidateIn(BaseModel):
    model_config = StrictModelConfig

    candidate_id: str = Field(min_length=1, max_length=256)
    source_type: CandidateSourceType
    source_locator: str = Field(min_length=1, max_length=512)
    discovered_at: datetime
    name: str = Field(min_length=1, max_length=256)
    framework: str = Field(min_length=1, max_length=32)
    artifact_digest: str | None = Field(default=None, max_length=256)
    attributes: dict[str, str] | None = None
    evidence_ids: list[str] = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    status: Literal["candidate", "needs_review", "dismissed"] = "candidate"


class EdgeEvidenceIn(BaseModel):
    model_config = StrictModelConfig

    evidence_id: str = Field(min_length=1, max_length=128)
    source_type: EvidenceSourceType
    source_locator: str = Field(min_length=1, max_length=512)
    subject_ref: str | None = Field(default=None, max_length=128)
    observed_at: datetime
    collected_at: datetime
    collector_id: str = Field(min_length=1, max_length=128)
    connector_version: str = Field(min_length=1, max_length=32)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    redaction_profile: Literal["siq.redaction.v1"]
    classification: Literal["public", "internal", "confidential", "secret_ref"]
    payload_ref: str | None = Field(default=None, max_length=256)
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")
    signing_schema: Literal["evidence_utf8/v1"] | None = None
    expires_at: datetime | None = None


class PermissionSubjectIn(BaseModel):
    model_config = StrictModelConfig

    type: Literal["agent_instance", "agent_asset", "identity_binding"]
    id: str = Field(min_length=1, max_length=128)


class PermissionResourceIn(BaseModel):
    model_config = StrictModelConfig

    type: str = Field(min_length=1, max_length=32)
    value: str = Field(min_length=1, max_length=512)


class EdgePermissionFactIn(BaseModel):
    model_config = StrictModelConfig

    subject: PermissionSubjectIn
    delegated_user: dict | None = None
    domain: Literal[
        "business",
        "data_scope",
        "tool",
        "filesystem",
        "network",
        "process",
        "model",
        "credential",
        "resource",
        "control_plane",
    ]
    action: str = Field(min_length=1, max_length=64)
    resource: PermissionResourceIn
    effect: Literal["allow", "deny"]
    conditions: dict = Field(default_factory=dict)
    state: Literal["declared", "inferred", "observed", "effective", "unknown"]
    authority: str = Field(min_length=1, max_length=32)
    authority_revision: str | None = Field(default=None, max_length=64)
    evidence_ids: list[str] = Field(min_length=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None


class EdgeBatchIn(BaseModel):
    model_config = StrictModelConfig

    task_id: str = Field(min_length=1, max_length=64)
    candidates: list[EdgeCandidateIn] = Field(default_factory=list, max_length=10000)
    evidence: list[EdgeEvidenceIn] = Field(default_factory=list, max_length=10000)
    permission_facts: list[EdgePermissionFactIn] = Field(default_factory=list, max_length=10000)
    signature: str = Field(pattern=r"^[0-9a-f]{128}$")


class FindingAcceptRisk(BaseModel):
    model_config = StrictModelConfig

    owner_user_id: str
    reason: str = Field(min_length=1, max_length=512)
    expires_at: datetime


class FindingResolve(BaseModel):
    """解决操作必须指向可追溯的修复证据/工单，且禁止查询串等易夹带凭据的内容。"""

    model_config = StrictModelConfig

    evidence_ref: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    )


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
    analyzer_version: str | None = None
    confidence: float | None = None
    matches: list = Field(default_factory=list)
    first_seen_at: datetime
    last_seen_at: datetime

    @field_validator("matches", "evidence_ids", mode="before")
    @classmethod
    def _null_legacy_columns_to_empty(cls, v):
        """0010 之前的存量行 matches 为 NULL（列后加且无回填时），响应对外一律为列表。"""
        return [] if v is None else v


class ThreatScanRequest(BaseModel):
    """威胁扫描请求（P0-3）：content 为文本或 base64；1 MiB 解码上限在路由侧强制。"""

    model_config = StrictModelConfig

    content: str = Field(min_length=1, max_length=4_000_000)
    encoding: Literal["text", "base64"] = "text"
    filename: str | None = Field(default=None, max_length=256)
    evidence_ids: list[str] = Field(default_factory=list, max_length=1000)


class QuarantineCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    asset_id: str
    finding_id: str | None
    evidence_ids: list
    reason: str
    status: str
    created_by: str
    created_at: datetime
    released_by: str | None
    released_at: datetime | None
    release_reason: str | None


class QuarantineReleaseRequest(BaseModel):
    model_config = StrictModelConfig

    reason: str = Field(min_length=1, max_length=512)


class ThreatScanOut(BaseModel):
    """扫描结果只含标识/哈希/脱敏命中记录，不回传原始内容。"""

    asset_id: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    detected_type: str
    analyzer_version: str
    match_count: int
    findings: list[FindingOut]
    quarantine_case: QuarantineCaseOut | None


class SecretReference(BaseModel):
    """策略只接受凭据引用；任何 value/token/password 等额外字段直接拒绝。"""

    model_config = ConfigDict(extra="forbid")

    ref: str = Field(min_length=1, max_length=512)
    purpose: str = Field(min_length=1, max_length=256)
    injection: Literal["gateway", "env_ref", "none"] = "none"


class PolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    selector: dict
    filesystem: dict | None = None
    network: list | None = None
    process: dict | None = None
    model_routing: dict | None = None
    tools: list | None = None
    tool_policies: dict | None = None
    data_scope_refs: list | None = None
    secrets: list[SecretReference] | None = None
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
    approved_at: datetime | None = None
    review_status: str | None = None
    review_due_at: datetime | None = None
    reviewed_by: str | None = None
    idempotency_key: str
    created_at: datetime


class RuntimeBindingCreate(BaseModel):
    """登记运行时绑定（P0-1）：部署目标只能来自 active 绑定，禁止客户端自由文本。"""

    model_config = StrictModelConfig

    agent_instance_id: str = Field(min_length=1, max_length=64)
    environment_id: str = Field(min_length=1, max_length=64)
    backend: str = Field(min_length=1, max_length=32)
    backend_target_id: str = Field(min_length=1, max_length=128)
    attestation: dict = Field(default_factory=dict)


class RuntimeBindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    environment_id: str
    agent_instance_id: str
    asset_id: str
    backend: str
    backend_target_id: str
    attestation: dict
    status: str
    created_at: datetime
    revoked_at: datetime | None


class DeploymentCreate(BaseModel):
    model_config = StrictModelConfig

    change_request_id: str
    environment_id: str
    binding_id: str = Field(min_length=1, max_length=64)


class DeploymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    environment_id: str
    change_request_id: str
    target: str
    runtime_binding_id: str | None
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
