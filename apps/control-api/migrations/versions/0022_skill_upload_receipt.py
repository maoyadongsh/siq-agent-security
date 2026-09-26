"""Preserve one canonical skill signature input per task."""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "skill_upload_receipt",
        sa.Column("task_id", sa.String(64), sa.ForeignKey("edge_task.id"), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("edge_agent_id", sa.String(64), sa.ForeignKey("edge_agent.id"), nullable=False),
        sa.Column("batch_digest", sa.String(64), nullable=False),
        sa.Column("signed_payload", sa.Text(), nullable=False),
        sa.Column("signature", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_skill_upload_receipt_tenant_id", "skill_upload_receipt", ["tenant_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM skill_upload_receipt")):
        raise RuntimeError("skill upload signature inputs must be preserved")
    op.drop_table("skill_upload_receipt")
