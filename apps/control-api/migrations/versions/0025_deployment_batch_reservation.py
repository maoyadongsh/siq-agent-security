"""Atomic batch execution claims. No automatic replay of stored claims."""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("deployment_batch_draft") as batch:
        batch.create_unique_constraint("uq_deployment_batch_draft_tenant_id", ["tenant_id", "id"])
    op.create_table(
        "deployment_batch_reservation",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("draft_id", sa.String(64), nullable=False, unique=True),
        sa.Column("submission_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "draft_id"], ["deployment_batch_draft.tenant_id", "deployment_batch_draft.id"],
            name="fk_batch_reservation_draft_tenant",
        ),
    )
    op.create_index("ix_deployment_batch_reservation_tenant_id", "deployment_batch_reservation", ["tenant_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM deployment_batch_reservation")):
        raise RuntimeError("batch execution claims must be preserved")
    op.drop_table("deployment_batch_reservation")
    with op.batch_alter_table("deployment_batch_draft") as batch:
        batch.drop_constraint("uq_deployment_batch_draft_tenant_id", type_="unique")
