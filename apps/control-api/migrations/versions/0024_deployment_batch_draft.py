"""Durable, expiring batch preview snapshots, without execution authority."""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "deployment_batch_draft",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("preview", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "request_key", name="uq_deployment_batch_draft_key"),
    )
    op.create_index("ix_deployment_batch_draft_tenant_id", "deployment_batch_draft", ["tenant_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM deployment_batch_draft")):
        raise RuntimeError("batch preview history must be preserved")
    op.drop_table("deployment_batch_draft")
