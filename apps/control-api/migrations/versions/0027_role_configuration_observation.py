"""Preserve validated role configuration snapshots independently of latest attributes."""
import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "role_configuration_observation",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("edge_agent_id", sa.String(64), sa.ForeignKey("edge_agent.id"), nullable=False),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("edge_task.id"), nullable=False),
        sa.Column("batch_digest", sa.String(64), nullable=False),
        sa.Column("framework_source", sa.JSON(), nullable=False),
        sa.Column("skill_source_roots", sa.JSON(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "asset_id"], ["agent_asset.tenant_id", "agent_asset.id"],
                                name="fk_role_config_asset_tenant"),
        sa.UniqueConstraint("asset_id", "task_id", name="uq_role_config_asset_task"),
    )
    for field in ("tenant_id", "asset_id"):
        op.create_index(f"ix_role_configuration_observation_{field}", "role_configuration_observation", [field])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM role_configuration_observation")):
        raise RuntimeError("role configuration history must be preserved")
    op.drop_table("role_configuration_observation")
