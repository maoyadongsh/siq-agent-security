"""P1-5 Edge 任务原子领取（claim/lease）：edge_task 增加 leased_at / lease_owner / attempt 列。

条件式迁移（同 0010/0011 风格）：fresh 库与旧库均可干净回放。

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    task_columns = {c["name"] for c in inspector.get_columns("edge_task")}
    if "leased_at" not in task_columns:
        op.add_column("edge_task", sa.Column("leased_at", sa.DateTime(), nullable=True))
    if "lease_owner" not in task_columns:
        op.add_column("edge_task", sa.Column("lease_owner", sa.String(128), nullable=True))
    if "attempt" not in task_columns:
        op.add_column(
            "edge_task",
            sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    task_columns = {c["name"] for c in inspector.get_columns("edge_task")}
    if "attempt" in task_columns:
        op.drop_column("edge_task", "attempt")
    if "lease_owner" in task_columns:
        op.drop_column("edge_task", "lease_owner")
    if "leased_at" in task_columns:
        op.drop_column("edge_task", "leased_at")
