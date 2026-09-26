"""Durable per-device first scan idempotency."""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "edge_initial_scan",
        sa.Column("edge_agent_id", sa.String(64), sa.ForeignKey("edge_agent.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("plan_digest", sa.String(64), nullable=False),
        sa.Column("task_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM edge_initial_scan")):
        raise RuntimeError("initial scan records must be preserved")
    op.drop_table("edge_initial_scan")
