"""威胁检测流水线（P0-3）：finding 分析器产物列 + quarantine_case 表。

条件式迁移（同 0003/0009 风格）：fresh 库与旧库均可干净回放。

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    finding_columns = {c["name"] for c in inspector.get_columns("finding")}
    if "analyzer_version" not in finding_columns:
        op.add_column("finding", sa.Column("analyzer_version", sa.String(64), nullable=True))
    if "confidence" not in finding_columns:
        op.add_column("finding", sa.Column("confidence", sa.Float(), nullable=True))
    if "matches" not in finding_columns:
        op.add_column("finding", sa.Column("matches", sa.JSON(), nullable=True))

    if "quarantine_case" not in set(inspector.get_table_names()):
        op.create_table(
            "quarantine_case",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(64), nullable=False),
            sa.Column("asset_id", sa.String(64), nullable=False),
            sa.Column("finding_id", sa.String(64), nullable=True),
            sa.Column("evidence_ids", sa.JSON(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("created_by", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("released_by", sa.String(64), nullable=True),
            sa.Column("released_at", sa.DateTime(), nullable=True),
            sa.Column("release_reason", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["asset_id"], ["agent_asset.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["finding_id"], ["finding.id"]),
        )
        op.create_index("ix_quarantine_case_tenant_id", "quarantine_case", ["tenant_id"])
        op.create_index("ix_quarantine_case_asset_id", "quarantine_case", ["asset_id"])
        op.create_index("ix_quarantine_case_status", "quarantine_case", ["status"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "quarantine_case" in set(inspector.get_table_names()):
        op.drop_table("quarantine_case")
    finding_columns = {c["name"] for c in inspector.get_columns("finding")}
    for column in ("matches", "confidence", "analyzer_version"):
        if column in finding_columns:
            op.drop_column("finding", column)
