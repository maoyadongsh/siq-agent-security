"""Durable deployment submission reservation.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "deployment_submission",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("change_request_id", sa.String(64), sa.ForeignKey("change_request.id"), nullable=False),
        sa.Column("deployment_id", sa.String(64), sa.ForeignKey("deployment.id"), nullable=False, unique=True),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("preview_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "request_key", name="uq_deployment_submission_key"),
        sa.UniqueConstraint("tenant_id", "change_request_id", name="uq_deployment_submission_change"),
    )
    op.create_index("ix_deployment_submission_tenant_id", "deployment_submission", ["tenant_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM deployment_submission")):
        raise RuntimeError("deployment submissions must be preserved; refusing destructive downgrade")
    op.drop_index("ix_deployment_submission_tenant_id", table_name="deployment_submission")
    op.drop_table("deployment_submission")
