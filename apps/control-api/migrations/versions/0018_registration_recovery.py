"""One initial registration recovery per device; immutable replay binding."""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "edge_registration_recovery",
        sa.Column("edge_agent_id", sa.String(64), sa.ForeignKey("edge_agent.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("request_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM edge_registration_recovery")):
        raise RuntimeError("registration recovery records must be preserved")
    op.drop_table("edge_registration_recovery")
