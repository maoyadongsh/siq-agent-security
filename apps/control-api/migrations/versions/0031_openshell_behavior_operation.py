"""Single-use behavior probe operations; preserve evidence on downgrade."""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "openshell_behavior_operation",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("deployment_id", sa.String(64), sa.ForeignKey("deployment.id"), nullable=False),
        sa.Column("operation_id", sa.String(64), sa.ForeignKey("openshell_operation.id"), nullable=False),
        sa.Column("challenge", sa.JSON(), nullable=False),
        sa.Column("challenge_digest", sa.String(64), nullable=False),
        sa.Column("nonce_sha256", sa.String(64), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("owner_sha256", sa.String(64), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("result_digest", sa.String(64), nullable=True),
        sa.Column("reason_code", sa.String(80), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "nonce_sha256", name="uq_openshell_behavior_nonce"),
        sa.CheckConstraint("epoch >= 0", name="ck_openshell_behavior_epoch"),
        sa.CheckConstraint(
            "state IN ('prepared','running','accepted','rejected','unknown','expired')",
            name="ck_openshell_behavior_state",
        ),
    )
    for column in ("tenant_id", "deployment_id"):
        op.create_index("ix_openshell_behavior_operation_" + column, "openshell_behavior_operation", [column])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM openshell_behavior_operation")):
        raise RuntimeError("openshell behavior evidence must be preserved")
    for column in ("tenant_id", "deployment_id"):
        op.drop_index("ix_openshell_behavior_operation_" + column, table_name="openshell_behavior_operation")
    op.drop_table("openshell_behavior_operation")
