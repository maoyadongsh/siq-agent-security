"""Evidence 改为租户内稳定 ID + 不可变内容观察版本。

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("evidence")}
    if "evidence_id" not in columns:
        op.add_column("evidence", sa.Column("evidence_id", sa.String(128), nullable=True))
        op.execute(sa.text("UPDATE evidence SET evidence_id = id WHERE evidence_id IS NULL"))
        with op.batch_alter_table("evidence") as batch:
            batch.alter_column("evidence_id", existing_type=sa.String(128), nullable=False)

    inspector = sa.inspect(op.get_bind())
    constraints = {item["name"] for item in inspector.get_unique_constraints("evidence")}
    if "uq_evidence_observation" not in constraints:
        with op.batch_alter_table("evidence") as batch:
            batch.create_unique_constraint(
                "uq_evidence_observation",
                ["tenant_id", "evidence_id", "content_hash"],
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    constraints = {item["name"] for item in inspector.get_unique_constraints("evidence")}
    columns = {column["name"] for column in inspector.get_columns("evidence")}
    with op.batch_alter_table("evidence") as batch:
        if "uq_evidence_observation" in constraints:
            batch.drop_constraint("uq_evidence_observation", type_="unique")
        if "evidence_id" in columns:
            batch.drop_column("evidence_id")
