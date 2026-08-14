"""Bind immutable evidence observations to their source environment.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine.reflection import Inspector

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_UNIQUE_COLUMNS = ["tenant_id", "environment_id", "evidence_id", "content_hash"]
_LEGACY_UNIQUE_COLUMNS = ["tenant_id", "evidence_id", "content_hash"]
_FK_NAME = "fk_evidence_environment_id_environment"


def _environment_fk_present(inspector: Inspector) -> bool:
    return any(
        item.get("referred_table") == "environment"
        and item.get("constrained_columns") == ["environment_id"]
        for item in inspector.get_foreign_keys("evidence")
    )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    unique = next(
        (
            item
            for item in inspector.get_unique_constraints("evidence")
            if item["name"] == "uq_evidence_observation"
        ),
        None,
    )
    unique_current = unique is not None and unique.get("column_names") == _UNIQUE_COLUMNS
    fk_current = _environment_fk_present(inspector)
    if unique_current and fk_current:
        return

    with op.batch_alter_table("evidence") as batch:
        if not unique_current:
            if unique is not None:
                batch.drop_constraint("uq_evidence_observation", type_="unique")
            batch.create_unique_constraint("uq_evidence_observation", _UNIQUE_COLUMNS)
        if not fk_current:
            batch.create_foreign_key(
                _FK_NAME,
                "environment",
                ["environment_id"],
                ["id"],
                ondelete="CASCADE",
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    unique = next(
        (
            item
            for item in inspector.get_unique_constraints("evidence")
            if item["name"] == "uq_evidence_observation"
        ),
        None,
    )
    with op.batch_alter_table("evidence") as batch:
        if _environment_fk_present(inspector):
            batch.drop_constraint(_FK_NAME, type_="foreignkey")
        if unique is not None and unique.get("column_names") == _UNIQUE_COLUMNS:
            batch.drop_constraint("uq_evidence_observation", type_="unique")
            batch.create_unique_constraint("uq_evidence_observation", _LEGACY_UNIQUE_COLUMNS)
