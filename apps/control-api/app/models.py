"""核心实体模型（对齐设计文档 §17.1）。

安全不变量（对应设计文档 §21.1）：
- 所有租户实体包含 tenant_id，外键与唯一约束尽量包含租户边界；
- 未授权对象在列表、搜索、导出、深链中都不可见（服务层以 404 隐藏存在性）；
- Secret 只存 sha256 摘要（edge secret_hash / enrollment code_hash），明文永不落库。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


class Tenant(Base):
    __tablename__ = "tenant"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("tnt"))
    name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|suspended
    data_residency: Mapped[str] = mapped_column(String(32), default="default")
    retention_days: Mapped[int] = mapped_column(Integer, default=180)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SkillUploadReceipt(Base):
    """One validated canonical signature input per task, for later verification."""

    __tablename__ = "skill_upload_receipt"
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("edge_task.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id"), index=True)
    edge_agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("edge_agent.id"))
    batch_digest: Mapped[str] = mapped_column(String(64))
    signed_payload: Mapped[str] = mapped_column(Text)
    signature: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SkillInstallation(Base):
    """Discovery location only; never an agent role or permission grant."""

    __tablename__ = "skill_installation"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ski"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id"), index=True)
    edge_agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("edge_agent.id"), index=True)
    locator_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (
        UniqueConstraint("tenant_id", "edge_agent_id", "locator_sha256", name="uq_skill_installation_location"),
        UniqueConstraint("tenant_id", "id", name="uq_skill_installation_tenant_id"),
    )


class RoleConfigurationObservation(Base):
    """Append-only validated config provenance, not independently replayable batch proof."""

    __tablename__ = "role_configuration_observation"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("rco"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    asset_id: Mapped[str] = mapped_column(String(64), index=True)
    edge_agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("edge_agent.id"))
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("edge_task.id"))
    batch_digest: Mapped[str] = mapped_column(String(64))
    framework_source: Mapped[dict] = mapped_column(JSON)
    skill_source_roots: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "asset_id"], ["agent_asset.tenant_id", "agent_asset.id"],
                             name="fk_role_config_asset_tenant"),
        UniqueConstraint("asset_id", "task_id", name="uq_role_config_asset_task"),
    )


class RoleSkillSelectionObservation(Base):
    """Append-only declared visibility scope; no installed-skill or grant inference."""

    __tablename__ = "role_skill_selection_observation"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("rso"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    asset_id: Mapped[str] = mapped_column(String(64), index=True)
    edge_agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("edge_agent.id"))
    task_id: Mapped[str] = mapped_column(String(64), ForeignKey("edge_task.id"))
    batch_digest: Mapped[str] = mapped_column(String(64))
    selection: Mapped[dict] = mapped_column(JSON)
    source_evidence: Mapped[list] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "asset_id"], ["agent_asset.tenant_id", "agent_asset.id"],
            name="fk_role_skill_asset_tenant",
        ),
        UniqueConstraint("asset_id", "task_id", name="uq_role_skill_asset_task"),
    )


class SkillManifestObservation(Base):
    """Append-only observation of a manifest, not a complete package digest."""

    __tablename__ = "skill_manifest_observation"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("smo"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    installation_id: Mapped[str] = mapped_column(String(64), index=True)
    manifest_sha256: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(64))
    parse_status: Mapped[str] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    allowed_tools_present: Mapped[bool] = mapped_column(Boolean, default=False)
    declared_tools: Mapped[list] = mapped_column(JSON, default=list)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    batch_digest: Mapped[str] = mapped_column(String(64))
    batch_signature: Mapped[str] = mapped_column(String(128))
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "installation_id"], ["skill_installation.tenant_id", "skill_installation.id"],
            name="fk_skill_observation_installation_tenant",
        ),
        UniqueConstraint("installation_id", "batch_digest", name="uq_skill_observation_batch"),
        CheckConstraint(
            "parse_status IN ('parsed', 'missing_frontmatter', 'unsupported', 'invalid_utf8')",
            name="ck_skill_observation_parse_status",
        ),
    )


class Environment(Base):
    __tablename__ = "environment"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("env"))
    tenant_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    env_type: Mapped[str] = mapped_column(String(32), default="host")  # host|container|k8s|account
    mode: Mapped[str] = mapped_column(String(16), default="discovery")  # discovery|observe|recommend|enforce
    risk_level: Mapped[str] = mapped_column(String(16), default="medium")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_environment_tenant_name"),
        UniqueConstraint("tenant_id", "id", name="uq_environment_tenant_id"),
    )


class EdgeAgent(Base):
    __tablename__ = "edge_agent"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("edge"))
    environment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("environment.id", ondelete="CASCADE"), index=True
    )
    device_identity: Mapped[str] = mapped_column(String(128), unique=True)
    secret_hash: Mapped[str] = mapped_column(String(64))  # sha256(device_secret)，明文仅注册时返回一次
    public_key_pem: Mapped[Text] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(32))
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("environment_id", "id", name="uq_edge_environment_id"),)


class EdgeCredentialRotation(Base):
    """Credential verifier history; not exposed through audit or device projections."""

    __tablename__ = "edge_credential_rotation"
    edge_agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("edge_agent.id"), primary_key=True)
    rotation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    old_secret_hash: Mapped[str] = mapped_column(String(64))
    new_secret_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("edge_agent_id", "new_secret_hash", name="uq_edge_rotation_new_hash"),)


class EdgeRegistrationRecovery(Base):
    __tablename__ = "edge_registration_recovery"

    edge_agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("edge_agent.id", ondelete="CASCADE"), primary_key=True
    )
    request_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EnrollmentToken(Base):
    __tablename__ = "enrollment_token"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("enr"))
    environment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("environment.id", ondelete="CASCADE"), index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64))  # 一次性注册码只存哈希
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class System(Base):
    __tablename__ = "system"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("sys"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    external_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags: Mapped[dict] = mapped_column(JSON, default=dict)


class AgentAsset(Base):
    """Candidate → confirmed → managed 状态机（设计文档 §10.4）。"""

    __tablename__ = "agent_asset"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("agt"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(256))
    role: Mapped[str | None] = mapped_column(String(128), nullable=True)
    framework: Mapped[str] = mapped_column(String(32), default="unknown")
    discovery_scope: Mapped[str] = mapped_column(String(64), default="legacy", server_default="legacy")
    # system 引用的租户一致性无法用纯 FK 表达（复合约束需引用 system(tenant_id, id)），
    # 由应用层在写入路径校验（confirm 端点：system 必须存在且同租户，见 routers/inventory.py）。
    system_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("system.id"), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # P1-8 制品指纹入账：候选上报的制品摘要与脱敏属性随资产保存
    artifact_digest: Mapped[str | None] = mapped_column(String(256), nullable=True)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict)  # 脱敏候选属性 + digest 变更观察记录
    # candidate|needs_review|confirmed|managed|stale|retired|dismissed
    status: Mapped[str] = mapped_column(String(16), default="candidate", index=True)
    # 发现去重：同一来源同一位置的候选合并为一行
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_locator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dismissed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    dismissed_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)  # 本资产关联的证据（批次上传时写入）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "discovery_scope", "source_type", "source_locator", name="uq_asset_source"),
        UniqueConstraint("tenant_id", "id", name="uq_agent_asset_tenant_id"),
    )


class AgentInstance(Base):
    __tablename__ = "agent_instance"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("inst"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_asset.id", ondelete="CASCADE"), index=True)
    environment_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("environment.id"), nullable=True)
    runtime: Mapped[str] = mapped_column(String(32), default="hermes")  # hermes|openclaw|pi|embedded|unknown
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    artifact_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)
    location: Mapped[dict] = mapped_column(JSON, default=dict)  # 运行位置（容器/hub 子进程/系统服务）
    status: Mapped[str] = mapped_column(String(16), default="observed")  # observed|running|stopped
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Evidence(Base):
    """不可变证据观察；同一外部 evidence_id 的内容变化会新增 observation。"""

    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("evo"))
    evidence_id: Mapped[str] = mapped_column(String(128))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True)
    environment_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("environment.id", ondelete="CASCADE"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(32))
    source_locator: Mapped[str] = mapped_column(String(512))
    subject_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    collected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    collector_id: Mapped[str] = mapped_column(String(128))
    connector_version: Mapped[str] = mapped_column(String(32))
    content_hash: Mapped[str] = mapped_column(String(64))
    redaction_profile: Mapped[str] = mapped_column(String(64), default="siq.redaction.v1")
    classification: Mapped[str] = mapped_column(String(16), default="internal")
    payload_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    signature: Mapped[str] = mapped_column(String(256))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "environment_id",
            "collector_id",
            "evidence_id",
            "content_hash",
            name="uq_evidence_observation",
        ),
    )

    @property
    def observation_id(self) -> str:
        return self.id


class ClassificationRun(Base):
    """模型辅助分类运行记录（设计文档 §11.3：可重新计算/可追溯重跑）。"""

    __tablename__ = "classification_run"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cls"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_asset.id", ondelete="CASCADE"), index=True)
    classifier: Mapped[str] = mapped_column(String(32))  # baseline|model-off|provider
    model_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    temperature: Mapped[float | None] = mapped_column(nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_evidence_ids: Mapped[list] = mapped_column(JSON, default=list)  # 只存引用，不存原始内容
    # DEV14-B：可追溯元数据（无原始正文 / 无 secret）
    input_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_ref: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output: Mapped[dict] = mapped_column(JSON, default=dict)  # 结构化结论（§11.3 Schema）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PermissionFact(Base):
    """权限事实（设计文档 §12.3，含 delegated_user 委托维度）。"""

    __tablename__ = "permission_fact"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("pf"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True)
    environment_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("environment.id", ondelete="CASCADE"), nullable=True, index=True
    )
    subject_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[str] = mapped_column(String(64), index=True)
    delegated_user: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    domain: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(32))
    resource_value: Mapped[str] = mapped_column(String(512))
    effect: Mapped[str] = mapped_column(String(8))  # allow|deny
    conditions: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(16), index=True)  # declared|inferred|observed|effective|unknown
    authority: Mapped[str] = mapped_column(String(32))
    authority_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Finding(Base):
    __tablename__ = "finding"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("fnd"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[str] = mapped_column(String(64))
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    severity: Mapped[str] = mapped_column(String(16))  # critical|high|medium|low|info
    domain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    asset_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("agent_asset.id"), nullable=True, index=True)
    resource_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 非资产作用域的资源（环境/凭据等）
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    remediation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # open|acknowledged|resolved|risk_accepted
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    owner_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    risk_acceptance: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # reason/approver/expires_at
    # P0-3 威胁检测流水线产物（仅 domain="threat" 的 Finding 使用；脱敏命中记录，不存原文）
    analyzer_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    matches: Mapped[list] = mapped_column(JSON, default=list)  # [{rule_id,line,excerpt_sha256,excerpt,...}]
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class QuarantineCase(Base):
    """威胁检测隔离处置（P0-3）：critical/high 命中即隔离，释放须显式理由。

    处置分离：释放隔离不会自动改动关联 Finding 的状态（Finding 生命周期独立管理）。
    """

    __tablename__ = "quarantine_case"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("qr"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_asset.id", ondelete="CASCADE"), index=True)
    finding_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("finding.id"), nullable=True)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(Text)  # 隔离原因（命中规则 id 汇总）
    status: Mapped[str] = mapped_column(String(16), default="quarantined", index=True)  # quarantined|released
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    released_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class DesiredPolicy(Base):
    __tablename__ = "desired_policy"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("pol"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    selector: Mapped[dict] = mapped_column(JSON)
    filesystem: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    network: Mapped[list | None] = mapped_column(JSON, nullable=True)
    process: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_routing: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tools: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tool_policies: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    data_scope_refs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    secrets: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 仅引用与用途，永不存明文
    resources: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    audit: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    exceptions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    unsupported_by_backend: Mapped[list] = mapped_column(JSON, default=list)
    enforcement_mode: Mapped[str] = mapped_column(String(16), default="audit_only")  # audit_only|warn|block
    version: Mapped[int] = mapped_column(Integer, default=1)
    # draft|validated|proposed|approved|deploying|effective|rejected|failed|superseded|rollback_pending|rolled_back
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "name", "version", name="uq_policy_tenant_name_version"),)


class ChangeRequest(Base):
    __tablename__ = "change_request"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cr"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True)
    policy_id: Mapped[str] = mapped_column(String(64), ForeignKey("desired_policy.id"))
    diff: Mapped[dict] = mapped_column(JSON, default=dict)
    impact: Mapped[dict] = mapped_column(JSON, default=dict)
    proposer_user_id: Mapped[str] = mapped_column(String(64))
    approver_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_policy: Mapped[str] = mapped_column(String(16), default="standard")  # standard|high_risk|break_glass
    # 业务生命周期：proposed|approved|rejected|deploying|effective|failed|rolled_back|emergency_applied
    # 遗留值 post_review_due 仅存量迁移保留，新代码不再写入（复核见 review_status）
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    # DEV12-A：复核正交于业务终态（M-P4）
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_status: Mapped[str | None] = mapped_column(
        String(16), nullable=True, index=True
    )  # none|pending|due|completed；非 break_glass 为 none/NULL
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RuntimeBinding(Base):
    """策略 selector 与运行时目标的强绑定（P0-1）。

    部署目标不再接受客户端自由文本，只允许来自本表登记且 active 的绑定；
    backend_target_id 登记后不可变（变更 = 吊销重建），防止部署被重定向到未登记运行时。
    当前登记是人工声明；active/attestation 不等同后端核验的运行身份、沙箱归属或执行效果。
    """

    __tablename__ = "runtime_binding"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("rb"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True)
    environment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("environment.id", ondelete="CASCADE"), index=True
    )
    agent_instance_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("agent_instance.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_asset.id", ondelete="CASCADE"), index=True)
    backend: Mapped[str] = mapped_column(String(32))  # openshell-cli|fake|...
    backend_target_id: Mapped[str] = mapped_column(String(128))  # 不可变运行时目标（如 sandbox 名）
    attestation: Mapped[dict] = mapped_column(JSON, default=dict)  # 后端版本/启动证明等登记佐证
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)  # active|revoked
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("tenant_id", "backend", "backend_target_id", name="uq_runtime_binding_target"),
    )


class Deployment(Base):
    __tablename__ = "deployment"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("dep"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True)
    environment_id: Mapped[str] = mapped_column(String(64), ForeignKey("environment.id"))
    change_request_id: Mapped[str] = mapped_column(String(64), ForeignKey("change_request.id"))
    # P0-1：target 服务端从 RuntimeBinding.backend_target_id 解析，客户端不可指定
    target: Mapped[str] = mapped_column(String(128))
    runtime_binding_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("runtime_binding.id"), nullable=True, index=True
    )
    from_revision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_revision: Mapped[str] = mapped_column(String(64))
    edge_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receipt: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # pending|sent|verifying|effective|failed|rolled_back
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EdgeTask(Base):
    __tablename__ = "edge_task"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("tsk"))
    environment_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("environment.id", ondelete="CASCADE"), index=True
    )
    task_type: Mapped[str] = mapped_column(String(32))  # scan|publish_policy|verify|rollback
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    signature: Mapped[str | None] = mapped_column(String(256), nullable=True)  # 控制面 Ed25519 任务签名
    # pending|uploaded|delivered|failed|expired；uploaded 表示结果已持久化、等待最终回执。
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    result_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # P1-5 任务租约（claim/lease）：lease_owner 为当前持有者 device_identity，
    # leased_at 为最近一次领取/续约时间，attempt 累计领取次数。
    # 注意：lease 不是分布式锁的完整替代（时钟漂移/进程暂停下仍可能重复投递），
    # at-least-once 语义的最终一致性由回执幂等（delivered/failed 终态去重）保障。
    leased_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EdgeInitialScan(Base):
    __tablename__ = "edge_initial_scan"

    edge_agent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("edge_agent.id", ondelete="CASCADE"), primary_key=True,
    )
    plan_digest: Mapped[str] = mapped_column(String(64))
    task_ids: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DiscoveryScheduleRecord(Base):
    __tablename__ = "discovery_schedule"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    environment_id: Mapped[str] = mapped_column(String(64))
    edge_agent_id: Mapped[str] = mapped_column(String(64), index=True)
    intent: Mapped[dict] = mapped_column(JSON)
    intent_digest: Mapped[str] = mapped_column(String(64))
    installation_plan: Mapped[dict] = mapped_column(JSON)
    installation_plan_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending_confirmation")
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    interval_seconds: Mapped[int] = mapped_column(Integer)
    max_runs: Mapped[int] = mapped_column(Integer)
    reserved_runs: Mapped[int] = mapped_column(Integer, default=0)
    last_reserved_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_discovery_schedule_tenant_id"),
        ForeignKeyConstraint(["tenant_id", "environment_id"], ["environment.tenant_id", "environment.id"],
                             name="fk_discovery_schedule_environment"),
        ForeignKeyConstraint(["environment_id", "edge_agent_id"], ["edge_agent.environment_id", "edge_agent.id"],
                             name="fk_discovery_schedule_device"),
        CheckConstraint("status IN ('pending_confirmation', 'active', 'paused', 'revoked')",
                        name="ck_discovery_schedule_status"),
        CheckConstraint("interval_seconds >= 900 AND interval_seconds <= 86400",
                        name="ck_discovery_schedule_interval"),
        CheckConstraint("max_runs >= 1 AND max_runs <= 2880 AND reserved_runs >= 0 AND reserved_runs <= max_runs",
                        name="ck_discovery_schedule_budget"),
        CheckConstraint("expires_at > starts_at AND revision >= 0", name="ck_discovery_schedule_window"),
        CheckConstraint("(reserved_runs = 0 AND last_reserved_slot IS NULL) OR "
                        "(reserved_runs > 0 AND last_reserved_slot IS NOT NULL AND "
                        "last_reserved_slot >= 0 AND reserved_runs <= last_reserved_slot + 1)",
                        name="ck_discovery_schedule_progress"),
    )


class DiscoveryScheduleRun(Base):
    __tablename__ = "discovery_schedule_run"

    schedule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slot: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    task_ids: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "schedule_id"], ["discovery_schedule.tenant_id", "discovery_schedule.id"],
                             name="fk_discovery_run_schedule"),
        CheckConstraint("slot >= 0", name="ck_discovery_run_slot"),
    )


class AuditEvent(Base):
    __tablename__ = "audit_event"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("aud"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True)
    actor_type: Mapped[str] = mapped_column(String(16))  # user|service|edge|system
    actor_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    resource_type: Mapped[str] = mapped_column(String(32))
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decision: Mapped[str] = mapped_column(String(16))  # allow|deny
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)  # 脱敏摘要：标识/数量/哈希，禁止原文
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class OutboxEvent(Base):
    """Transactional Outbox（设计文档 §23.1）：状态变化与事件发布同事务。"""

    __tablename__ = "outbox_event"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("out"))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # 必须已脱敏
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # DEV12-B：多实例领取/租约（至少一次投递；确认前崩溃可被接管）
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    leased_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_revision: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DeploymentBatchDraft(Base):
    """Persisted preview only; never an execution reservation."""

    __tablename__ = "deployment_batch_draft"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("bdraft"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(128))
    actor_type: Mapped[str] = mapped_column(String(32))
    request_key: Mapped[str] = mapped_column(String(36))
    request_digest: Mapped[str] = mapped_column(String(64))
    preview: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    __table_args__ = (
        UniqueConstraint("tenant_id", "request_key", name="uq_deployment_batch_draft_key"),
        UniqueConstraint("tenant_id", "id", name="uq_deployment_batch_draft_tenant_id"),
    )


class DeploymentBatchReservation(Base):
    """Atomic batch-to-item claims; existing claims never confer replay authority."""

    __tablename__ = "deployment_batch_reservation"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("bres"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id"), index=True)
    draft_id: Mapped[str] = mapped_column(String(64), unique=True)
    submission_ids: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (ForeignKeyConstraint(
        ["tenant_id", "draft_id"], ["deployment_batch_draft.tenant_id", "deployment_batch_draft.id"],
        name="fk_batch_reservation_draft_tenant",
    ),)


class DeploymentSubmission(Base):
    """Durable single execution reservation; unknown outcomes are never replayed."""

    __tablename__ = 'deployment_submission'
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id('dsub'))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey('tenant.id', ondelete='CASCADE'), index=True)
    change_request_id: Mapped[str] = mapped_column(String(64), ForeignKey('change_request.id'))
    deployment_id: Mapped[str] = mapped_column(String(64), ForeignKey('deployment.id'), unique=True)
    request_key: Mapped[str] = mapped_column(String(36))
    request_digest: Mapped[str] = mapped_column(String(64))
    preview_digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (
        UniqueConstraint('tenant_id', 'request_key', name='uq_deployment_submission_key'),
        UniqueConstraint('tenant_id', 'change_request_id', name='uq_deployment_submission_change'),
    )
