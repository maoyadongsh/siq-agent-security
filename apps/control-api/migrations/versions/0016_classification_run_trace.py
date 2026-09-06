"""DEV14-B：classification_run 可追溯元数据列。

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "classification_run" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("classification_run")}
    adds = [
        ("input_summary", sa.Column("input_summary", sa.JSON(), nullable=True)),
        ("error_ref", sa.Column("error_ref", sa.JSON(), nullable=True)),
        ("latency_ms", sa.Column("latency_ms", sa.Integer(), nullable=True)),
        ("prompt_tokens", sa.Column("prompt_tokens", sa.Integer(), nullable=True)),
        ("completion_tokens", sa.Column("completion_tokens", sa.Integer(), nullable=True)),
    ]
    for name, col in adds:
        if name not in columns:
            op.add_column("classification_run", col)
    # model_ref 加长：既有 String(64) → String(128)（SQLite 多为 noop / batch）
    if "model_ref" in columns:
        try:
            op.alter_column(
                "classification_run",
                "model_ref",
                existing_type=sa.String(64),
                type_=sa.String(128),
                existing_nullable=True,
            )
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "classification_run" not in inspector.get_table_names():
        return
    columns = {c["name"] for c in inspector.get_columns("classification_run")}
    for name in ("completion_tokens", "prompt_tokens", "latency_ms", "error_ref", "input_summary"):
        if name in columns:
            op.drop_column("classification_run", name)
