"""Bind new behavior operations to operator profiles without rewriting history."""
import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("openshell_behavior_operation") as batch:
        batch.add_column(sa.Column("profile_id", sa.String(128), nullable=True))
        batch.add_column(sa.Column("profile_sha256", sa.String(64), nullable=True))
        batch.create_check_constraint("ck_openshell_behavior_profile_pair",
            "(profile_id IS NULL AND profile_sha256 IS NULL) OR "
            "(profile_id IS NOT NULL AND profile_sha256 IS NOT NULL)")


def downgrade():
    if op.get_bind().scalar(sa.text(
        "SELECT count(*) FROM openshell_behavior_operation WHERE profile_id IS NOT NULL OR profile_sha256 IS NOT NULL"
    )):
        raise RuntimeError("operator profile evidence must be preserved")
    with op.batch_alter_table("openshell_behavior_operation") as batch:
        batch.drop_constraint("ck_openshell_behavior_profile_pair", type_="check")
        batch.drop_column("profile_sha256")
        batch.drop_column("profile_id")
