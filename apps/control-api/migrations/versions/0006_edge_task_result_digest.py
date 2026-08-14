"""Edge task 上传结果摘要与 uploaded 状态支持。

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("edge_task")}
    if "result_digest" not in columns:
        op.add_column("edge_task", sa.Column("result_digest", sa.String(64), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("edge_task")}
    if "result_digest" in columns:
        op.drop_column("edge_task", "result_digest")
