"""finding.resource_ref：非资产作用域的资源定位（环境/凭据等）

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("finding", sa.Column("resource_ref", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("finding", "resource_ref")
