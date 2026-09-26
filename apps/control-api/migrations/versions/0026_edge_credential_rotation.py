"""Preserve device credential rotation recovery and hash reuse barriers."""
import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "edge_credential_rotation",
        sa.Column("edge_agent_id", sa.String(64), sa.ForeignKey("edge_agent.id"), primary_key=True),
        sa.Column("rotation_id", sa.String(36), primary_key=True),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("old_secret_hash", sa.String(64), nullable=False),
        sa.Column("new_secret_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("edge_agent_id", "new_secret_hash", name="uq_edge_rotation_new_hash"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM edge_credential_rotation")):
        raise RuntimeError("credential rotation history must be preserved")
    op.drop_table("edge_credential_rotation")
