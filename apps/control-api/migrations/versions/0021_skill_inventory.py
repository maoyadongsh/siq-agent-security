"""Independent skill discovery locations and signed manifest observations."""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "skill_installation",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenant.id"), nullable=False),
        sa.Column("edge_agent_id", sa.String(64), sa.ForeignKey("edge_agent.id"), nullable=False),
        sa.Column("locator_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "edge_agent_id", "locator_sha256", name="uq_skill_installation_location"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_skill_installation_tenant_id"),
    )
    op.create_index("ix_skill_installation_tenant_id", "skill_installation", ["tenant_id"])
    op.create_index("ix_skill_installation_edge_agent_id", "skill_installation", ["edge_agent_id"])
    op.create_table(
        "skill_manifest_observation",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("installation_id", sa.String(64), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("parse_status", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("allowed_tools_present", sa.Boolean(), nullable=False),
        sa.Column("declared_tools", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("batch_digest", sa.String(64), nullable=False),
        sa.Column("batch_signature", sa.String(128), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "installation_id"],
            ["skill_installation.tenant_id", "skill_installation.id"],
            name="fk_skill_observation_installation_tenant",
        ),
        sa.UniqueConstraint("installation_id", "batch_digest", name="uq_skill_observation_batch"),
        sa.CheckConstraint(
            "parse_status IN ('parsed', 'missing_frontmatter', 'unsupported', 'invalid_utf8')",
            name="ck_skill_observation_parse_status",
        ),
    )
    op.create_index("ix_skill_manifest_observation_tenant_id", "skill_manifest_observation", ["tenant_id"])
    op.create_index("ix_skill_manifest_observation_installation_id", "skill_manifest_observation", ["installation_id"])


def downgrade():
    connection = op.get_bind()
    for table in ("skill_manifest_observation", "skill_installation"):
        if connection.scalar(sa.text(f"SELECT count(*) FROM {table}")):
            raise RuntimeError("skill discovery history must be preserved")
    op.drop_table("skill_manifest_observation")
    op.drop_table("skill_installation")
