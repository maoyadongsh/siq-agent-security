"""DEV12-A：break-glass 复核字段与业务 status 正交。

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-06
"""

from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("change_request")}
    if "approved_at" not in columns:
        op.add_column("change_request", sa.Column("approved_at", sa.DateTime(), nullable=True))
    if "review_status" not in columns:
        op.add_column("change_request", sa.Column("review_status", sa.String(16), nullable=True))
        op.create_index("ix_change_request_review_status", "change_request", ["review_status"])
    if "review_due_at" not in columns:
        op.add_column("change_request", sa.Column("review_due_at", sa.DateTime(), nullable=True))
    if "reviewed_by" not in columns:
        op.add_column("change_request", sa.Column("reviewed_by", sa.String(64), nullable=True))

    # 存量 post_review_due：只标记复核 due，不猜测还原业务终态
    bind.execute(
        sa.text(
            """
            UPDATE change_request
            SET review_status = 'due'
            WHERE approval_policy = 'break_glass'
              AND status = 'post_review_due'
              AND (review_status IS NULL OR review_status = '')
            """
        )
    )

    # 已批准 break-glass：挂起复核；期限按批准/创建时间 + 24h（迁移回填，非运行时合同源）
    rows = bind.execute(
        sa.text(
            """
            SELECT id, created_at, approved_at
            FROM change_request
            WHERE approval_policy = 'break_glass'
              AND approver_user_id IS NOT NULL
              AND status IN (
                    'emergency_applied', 'approved', 'deploying',
                    'effective', 'failed', 'rolled_back'
                  )
              AND (review_status IS NULL OR review_status = '')
            """
        )
    ).mappings()
    for row in rows:
        base = row["approved_at"] or row["created_at"]
        due = base + timedelta(days=1) if base is not None else None
        bind.execute(
            sa.text(
                """
                UPDATE change_request
                SET review_status = 'pending',
                    approved_at = COALESCE(approved_at, created_at),
                    review_due_at = COALESCE(review_due_at, :due)
                WHERE id = :id
                """
            ),
            {"id": row["id"], "due": due},
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("change_request")}
    if "reviewed_by" in columns:
        op.drop_column("change_request", "reviewed_by")
    if "review_due_at" in columns:
        op.drop_column("change_request", "review_due_at")
    if "review_status" in columns:
        op.drop_index("ix_change_request_review_status", table_name="change_request")
        op.drop_column("change_request", "review_status")
    if "approved_at" in columns:
        op.drop_column("change_request", "approved_at")
