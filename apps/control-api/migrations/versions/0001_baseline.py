"""baseline：全部核心实体

基线迁移采用 create_all 模式（与 siq-gateway 0001_baseline 同惯例）：
全新数据库可用；后续 schema 变更必须新增迁移并在干净库 + 存量库回放验证。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.db import Base
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from app.db import Base

    Base.metadata.drop_all(bind=op.get_bind())
