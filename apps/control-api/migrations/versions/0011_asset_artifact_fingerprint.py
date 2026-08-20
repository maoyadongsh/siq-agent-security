"""P1-8 制品指纹入账：agent_asset 增加 artifact_digest / attributes 列。

条件式迁移（同 0003/0009/0010 风格）：fresh 库与旧库均可干净回放。

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    asset_columns = {c["name"] for c in inspector.get_columns("agent_asset")}
    if "artifact_digest" not in asset_columns:
        op.add_column("agent_asset", sa.Column("artifact_digest", sa.String(256), nullable=True))
    if "attributes" not in asset_columns:
        op.add_column("agent_asset", sa.Column("attributes", sa.JSON(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    asset_columns = {c["name"] for c in inspector.get_columns("agent_asset")}
    if "attributes" in asset_columns:
        op.drop_column("agent_asset", "attributes")
    if "artifact_digest" in asset_columns:
        op.drop_column("agent_asset", "artifact_digest")
