"""Runtime bindings pin policy deployments to registered runtime targets (P0-1).

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "runtime_binding" not in tables:
        op.create_table(
            "runtime_binding",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("environment_id", sa.String(64), nullable=False),
            sa.Column("agent_instance_id", sa.String(64), nullable=False),
            sa.Column("asset_id", sa.String(64), nullable=False),
            sa.Column("backend", sa.String(32), nullable=False),
            sa.Column("backend_target_id", sa.String(128), nullable=False),
            sa.Column("attestation", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["agent_instance_id"], ["agent_instance.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["asset_id"], ["agent_asset.id"], ondelete="CASCADE"),
            sa.UniqueConstraint(
                "tenant_id", "backend", "backend_target_id", name="uq_runtime_binding_target"
            ),
        )
        op.create_index("ix_runtime_binding_tenant_id", "runtime_binding", ["tenant_id"])
        op.create_index("ix_runtime_binding_environment_id", "runtime_binding", ["environment_id"])
        op.create_index(
            "ix_runtime_binding_agent_instance_id", "runtime_binding", ["agent_instance_id"]
        )
        op.create_index("ix_runtime_binding_asset_id", "runtime_binding", ["asset_id"])
        op.create_index("ix_runtime_binding_status", "runtime_binding", ["status"])

    columns = {column["name"] for column in inspector.get_columns("deployment")}
    if "runtime_binding_id" not in columns:
        with op.batch_alter_table("deployment") as batch:
            batch.add_column(
                sa.Column(
                    "runtime_binding_id",
                    sa.String(64),
                    sa.ForeignKey("runtime_binding.id", name="fk_deployment_runtime_binding_id"),
                    nullable=True,
                )
            )
            batch.create_index("ix_deployment_runtime_binding_id", ["runtime_binding_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("deployment")}
    if "runtime_binding_id" in columns:
        with op.batch_alter_table("deployment") as batch:
            batch.drop_index("ix_deployment_runtime_binding_id")
            batch.drop_column("runtime_binding_id")
    if "runtime_binding" in set(inspector.get_table_names()):
        op.drop_table("runtime_binding")
