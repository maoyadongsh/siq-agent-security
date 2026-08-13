"""finding.resource_ref：非资产作用域的资源定位（环境/凭据等）

注意：0001 基线为 create_all 基线（同 siq-gateway 惯例），其导入的是"当前"模型。
因此本迁移为条件式：fresh 库（0001 已含该列）跳过；旧库（0001 无该列）补列。
两种路径最终 schema 一致。

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
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("finding")}
    if "resource_ref" not in columns:
        op.add_column("finding", sa.Column("resource_ref", sa.String(128), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("finding")}
    if "resource_ref" in columns:
        op.drop_column("finding", "resource_ref")
