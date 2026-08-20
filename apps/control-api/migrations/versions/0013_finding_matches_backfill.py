"""finding.matches 存量行回填（NULL → '[]'）。

0010 后加的 matches 列无回填，旧库的存量 finding 行 matches 为 NULL，
ORM 读出 None 会导致 FindingOut 响应校验 500。条件式迁移（对齐 0010 风格）。

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    finding_columns = {c["name"] for c in inspector.get_columns("finding")}
    if "matches" in finding_columns:
        op.execute("UPDATE finding SET matches = '[]' WHERE matches IS NULL")


def downgrade() -> None:
    # 数据回填不可逆也无害（NULL 与 [] 语义等价），downgrade 为空操作
    pass
