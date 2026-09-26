"""Preserve declared role skill selection observations independently of attributes."""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("agent_asset") as batch:
        batch.create_unique_constraint("uq_agent_asset_tenant_id", ["tenant_id", "id"])
    op.create_table(
        "role_skill_selection_observation",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False),
        sa.Column("edge_agent_id", sa.String(64), sa.ForeignKey("edge_agent.id"), nullable=False),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("edge_task.id"), nullable=False),
        sa.Column("batch_digest", sa.String(64), nullable=False),
        sa.Column("selection", sa.JSON(), nullable=False),
        sa.Column("source_evidence", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "asset_id"], ["agent_asset.tenant_id", "agent_asset.id"],
            name="fk_role_skill_asset_tenant",
        ),
        sa.UniqueConstraint("asset_id", "task_id", name="uq_role_skill_asset_task"),
    )
    for field in ("tenant_id", "asset_id"):
        op.create_index(f"ix_role_skill_selection_observation_{field}", "role_skill_selection_observation", [field])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM role_skill_selection_observation")):
        raise RuntimeError("role skill declaration history must be preserved")
    op.drop_table("role_skill_selection_observation")
    with op.batch_alter_table("agent_asset") as batch:
        batch.drop_constraint("uq_agent_asset_tenant_id", type_="unique")
