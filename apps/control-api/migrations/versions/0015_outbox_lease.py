"""DEV12-B：Outbox 领取租约与退避字段。

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("outbox_event")}
    adds = [
        ("lease_owner", sa.Column("lease_owner", sa.String(128), nullable=True)),
        ("leased_at", sa.Column("leased_at", sa.DateTime(), nullable=True)),
        ("lease_revision", sa.Column("lease_revision", sa.Integer(), nullable=False, server_default="0")),
        ("attempt", sa.Column("attempt", sa.Integer(), nullable=False, server_default="0")),
        ("next_attempt_at", sa.Column("next_attempt_at", sa.DateTime(), nullable=True)),
        ("dead_lettered_at", sa.Column("dead_lettered_at", sa.DateTime(), nullable=True)),
    ]
    for name, col in adds:
        if name not in columns:
            op.add_column("outbox_event", col)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("outbox_event")}
    for name in (
        "dead_lettered_at",
        "next_attempt_at",
        "attempt",
        "lease_revision",
        "leased_at",
        "lease_owner",
    ):
        if name in columns:
            op.drop_column("outbox_event", name)
