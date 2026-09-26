"""Separate discovery identities and evidence observations by trusted device."""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("agent_asset") as batch:
        batch.add_column(sa.Column("discovery_scope", sa.String(64), nullable=False, server_default="legacy"))
        batch.drop_constraint("uq_asset_source", type_="unique")
        batch.create_unique_constraint(
            "uq_asset_source", ["tenant_id", "discovery_scope", "source_type", "source_locator"]
        )
    with op.batch_alter_table("evidence") as batch:
        batch.drop_constraint("uq_evidence_observation", type_="unique")
        batch.create_unique_constraint(
            "uq_evidence_observation", ["tenant_id", "environment_id", "collector_id", "evidence_id", "content_hash"]
        )


def downgrade():
    raise RuntimeError("device-scoped discovery cannot be merged by automatic downgrade")
