"""Permission facts carry their trusted source environment.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("permission_fact")}
    if "environment_id" not in columns:
        with op.batch_alter_table("permission_fact") as batch:
            batch.add_column(
                sa.Column(
                    "environment_id",
                    sa.String(64),
                    sa.ForeignKey("environment.id", ondelete="CASCADE"),
                    nullable=True,
                )
            )
            batch.create_index(
                "ix_permission_fact_environment_id",
                ["environment_id"],
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("permission_fact")}
    if "environment_id" in columns:
        with op.batch_alter_table("permission_fact") as batch:
            batch.drop_index("ix_permission_fact_environment_id")
            batch.drop_column("environment_id")
