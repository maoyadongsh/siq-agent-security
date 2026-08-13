"""classification_run：模型辅助分类运行记录（条件式迁移，同 0002 说明）

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "classification_run" not in inspector.get_table_names():
        op.create_table(
            "classification_run",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("asset_id", sa.String(64), nullable=False),
            sa.Column("classifier", sa.String(32), nullable=False),
            sa.Column("model_ref", sa.String(64), nullable=True),
            sa.Column("prompt_version", sa.String(32), nullable=True),
            sa.Column("schema_version", sa.Integer(), nullable=False),
            sa.Column("temperature", sa.Float(), nullable=True),
            sa.Column("seed", sa.Integer(), nullable=True),
            sa.Column("input_evidence_ids", sa.JSON(), nullable=True),
            sa.Column("output", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("classification_run")
