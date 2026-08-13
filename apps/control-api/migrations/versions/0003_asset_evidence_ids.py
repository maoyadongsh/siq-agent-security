"""agent_asset.evidence_ids：资产与证据的关联（批次上传时写入）

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_asset", sa.Column("evidence_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_asset", "evidence_ids")
