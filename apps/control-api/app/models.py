"""核心实体模型（对齐设计文档 §17.1）。

安全不变量（对应设计文档 §21.1）：
- 所有租户实体包含 tenant_id，外键与唯一约束尽量包含租户边界；
- 未授权对象在列表、搜索、导出、深链中都不可见（服务层以 404 隐藏存在性）；
- Secret 只存 sha256 摘要（edge secret_hash / enrollment code_hash），明文永不落库。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
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

    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_environment_tenant_name"),)


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
    system_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("system.id"), nullable=True)
    owner_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # candidate|needs_review|confirmed|managed|stale|retired|dismissed
    status: Mapped[str] = mapped_column(String(16), default="candidate", index=True)
    # 发现去重：同一来源同一位置的候选合并为一行
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_locator: Mapped[str | None] = mapped_column(String(512), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dismissed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    dismissed_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    __table_args__ = (UniqueConstraint("tenant_id", "source_type", "source_locator", name="uq_asset_source"),)


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
    """证据模型（设计文档 §10.5）。原始配置不默认上传。"""

    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ev"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True)
    environment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
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


class PermissionFact(Base):
    """权限事实（设计文档 §12.3，含 delegated_user 委托维度）。"""

    __tablename__ = "permission_fact"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("pf"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True)
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
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    remediation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # open|acknowledged|resolved|risk_accepted|expired
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    owner_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    risk_acceptance: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # reason/approver/expires_at
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


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
    # proposed|approved|rejected|deploying|effective|failed|rolled_back|emergency_applied|post_review_due
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Deployment(Base):
    __tablename__ = "deployment"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("dep"))
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenant.id", ondelete="CASCADE"), index=True)
    environment_id: Mapped[str] = mapped_column(String(64), ForeignKey("environment.id"))
    change_request_id: Mapped[str] = mapped_column(String(64), ForeignKey("change_request.id"))
    target: Mapped[str] = mapped_column(String(128))
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
    signature: Mapped[str | None] = mapped_column(String(256), nullable=True)  # Phase 0 后接 Edge 公钥验证
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending|delivered|failed|expired
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


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
