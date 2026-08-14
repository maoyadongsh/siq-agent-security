"""Frozen baseline schema through revision 0008.

Revision ID: 0001
Revises: None

The original baseline imported ``app.models`` and called ``create_all()``.
That made an already-published revision mutate whenever the ORM changed.  This
snapshot is deliberately self-contained; later conditional migrations remain
compatible with databases that previously applied the dynamic baseline.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox_event",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_outbox_event_tenant_id", "outbox_event", ["tenant_id"])
    op.create_table(
        "tenant",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("data_residency", sa.String(32), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "audit_event",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("actor_type", sa.String(16), nullable=False),
        sa.Column("actor_id", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_audit_event_created_at", "audit_event", ["created_at"])
    op.create_index("ix_audit_event_tenant_id", "audit_event", ["tenant_id"])
    op.create_table(
        "desired_policy",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("selector", sa.JSON(), nullable=False),
        sa.Column("filesystem", sa.JSON(), nullable=True),
        sa.Column("network", sa.JSON(), nullable=True),
        sa.Column("process", sa.JSON(), nullable=True),
        sa.Column("model_routing", sa.JSON(), nullable=True),
        sa.Column("tools", sa.JSON(), nullable=True),
        sa.Column("tool_policies", sa.JSON(), nullable=True),
        sa.Column("data_scope_refs", sa.JSON(), nullable=True),
        sa.Column("secrets", sa.JSON(), nullable=True),
        sa.Column("resources", sa.JSON(), nullable=True),
        sa.Column("audit", sa.JSON(), nullable=True),
        sa.Column("exceptions", sa.JSON(), nullable=True),
        sa.Column("unsupported_by_backend", sa.JSON(), nullable=False),
        sa.Column("enforcement_mode", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "name", "version", name="uq_policy_tenant_name_version"),
    )
    op.create_index("ix_desired_policy_status", "desired_policy", ["status"])
    op.create_index("ix_desired_policy_tenant_id", "desired_policy", ["tenant_id"])
    op.create_table(
        "environment",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("env_type", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_environment_tenant_name"),
    )
    op.create_index("ix_environment_tenant_id", "environment", ["tenant_id"])
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("evidence_id", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("environment_id", sa.String(64), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_locator", sa.String(512), nullable=False),
        sa.Column("subject_ref", sa.String(128), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("collected_at", sa.DateTime(), nullable=False),
        sa.Column("collector_id", sa.String(128), nullable=False),
        sa.Column("connector_version", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("redaction_profile", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("payload_ref", sa.String(256), nullable=True),
        sa.Column("signature", sa.String(256), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["environment_id"],
            ["environment.id"],
            name="fk_evidence_environment_id_environment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "tenant_id",
            "environment_id",
            "evidence_id",
            "content_hash",
            name="uq_evidence_observation",
        ),
    )
    op.create_index("ix_evidence_tenant_id", "evidence", ["tenant_id"])
    op.create_table(
        "system",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("external_ref", sa.String(256), nullable=True),
        sa.Column("owner_user_id", sa.String(64), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_system_tenant_id", "system", ["tenant_id"])
    op.create_table(
        "agent_asset",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("role", sa.String(128), nullable=True),
        sa.Column("framework", sa.String(32), nullable=False),
        sa.Column("system_id", sa.String(64), nullable=True),
        sa.Column("owner_user_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=True),
        sa.Column("source_locator", sa.String(512), nullable=True),
        sa.Column("confirmed_by", sa.String(64), nullable=True),
        sa.Column("dismissed_reason", sa.Text(), nullable=True),
        sa.Column("dismissed_expires_at", sa.DateTime(), nullable=True),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["system_id"], ["system.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "source_type", "source_locator", name="uq_asset_source"),
    )
    op.create_index("ix_agent_asset_status", "agent_asset", ["status"])
    op.create_index("ix_agent_asset_tenant_id", "agent_asset", ["tenant_id"])
    op.create_table(
        "change_request",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("policy_id", sa.String(64), nullable=False),
        sa.Column("diff", sa.JSON(), nullable=False),
        sa.Column("impact", sa.JSON(), nullable=False),
        sa.Column("proposer_user_id", sa.String(64), nullable=False),
        sa.Column("approver_user_id", sa.String(64), nullable=True),
        sa.Column("approval_policy", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["policy_id"], ["desired_policy.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_change_request_status", "change_request", ["status"])
    op.create_index("ix_change_request_tenant_id", "change_request", ["tenant_id"])
    op.create_table(
        "edge_agent",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("environment_id", sa.String(64), nullable=False),
        sa.Column("device_identity", sa.String(128), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("public_key_pem", sa.Text(), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("registered_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("device_identity"),
    )
    op.create_index("ix_edge_agent_environment_id", "edge_agent", ["environment_id"])
    op.create_table(
        "edge_task",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("environment_id", sa.String(64), nullable=False),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("signature", sa.String(256), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result_digest", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_edge_task_environment_id", "edge_task", ["environment_id"])
    op.create_index("ix_edge_task_status", "edge_task", ["status"])
    op.create_table(
        "enrollment_token",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("environment_id", sa.String(64), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_enrollment_token_environment_id", "enrollment_token", ["environment_id"])
    op.create_table(
        "permission_fact",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("environment_id", sa.String(64), nullable=True),
        sa.Column("subject_type", sa.String(32), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=False),
        sa.Column("delegated_user", sa.JSON(), nullable=True),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_value", sa.String(512), nullable=False),
        sa.Column("effect", sa.String(8), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("authority", sa.String(32), nullable=False),
        sa.Column("authority_revision", sa.String(64), nullable=True),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("valid_from", sa.DateTime(), nullable=True),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_permission_fact_environment_id", "permission_fact", ["environment_id"])
    op.create_index("ix_permission_fact_state", "permission_fact", ["state"])
    op.create_index("ix_permission_fact_subject_id", "permission_fact", ["subject_id"])
    op.create_index("ix_permission_fact_tenant_id", "permission_fact", ["tenant_id"])
    op.create_table(
        "agent_instance",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("environment_id", sa.String(64), nullable=True),
        sa.Column("runtime", sa.String(32), nullable=False),
        sa.Column("version", sa.String(64), nullable=True),
        sa.Column("artifact_digest", sa.String(128), nullable=True),
        sa.Column("location", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["agent_asset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_instance_asset_id", "agent_instance", ["asset_id"])
    op.create_index("ix_agent_instance_tenant_id", "agent_instance", ["tenant_id"])
    op.create_table(
        "classification_run",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("classifier", sa.String(32), nullable=False),
        sa.Column("model_ref", sa.String(64), nullable=True),
        sa.Column("prompt_version", sa.String(32), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("input_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["agent_asset.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_classification_run_asset_id", "classification_run", ["asset_id"])
    op.create_index("ix_classification_run_tenant_id", "classification_run", ["tenant_id"])
    op.create_table(
        "deployment",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("environment_id", sa.String(64), nullable=False),
        sa.Column("change_request_id", sa.String(64), nullable=False),
        sa.Column("target", sa.String(128), nullable=False),
        sa.Column("from_revision", sa.String(64), nullable=True),
        sa.Column("to_revision", sa.String(64), nullable=False),
        sa.Column("edge_task_id", sa.String(64), nullable=True),
        sa.Column("receipt", sa.JSON(), nullable=True),
        sa.Column("verification", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["change_request_id"], ["change_request.id"]),
        sa.ForeignKeyConstraint(["environment_id"], ["environment.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_deployment_status", "deployment", ["status"])
    op.create_index("ix_deployment_tenant_id", "deployment", ["tenant_id"])
    op.create_table(
        "finding",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("rule_id", sa.String(64), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("domain", sa.String(32), nullable=True),
        sa.Column("asset_id", sa.String(64), nullable=True),
        sa.Column("resource_ref", sa.String(128), nullable=True),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("impact", sa.Text(), nullable=True),
        sa.Column("remediation", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("owner_user_id", sa.String(64), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=True),
        sa.Column("risk_acceptance", sa.JSON(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["agent_asset.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_finding_asset_id", "finding", ["asset_id"])
    op.create_index("ix_finding_status", "finding", ["status"])
    op.create_index("ix_finding_tenant_id", "finding", ["tenant_id"])


def downgrade() -> None:
    for table in (
        "finding",
        "deployment",
        "classification_run",
        "agent_instance",
        "permission_fact",
        "enrollment_token",
        "edge_task",
        "edge_agent",
        "change_request",
        "agent_asset",
        "system",
        "evidence",
        "environment",
        "desired_policy",
        "audit_event",
        "tenant",
        "outbox_event",
    ):
        op.drop_table(table)
