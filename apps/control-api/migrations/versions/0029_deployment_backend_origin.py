"""Preserve original execution backend; current config is not historical authority."""
import sqlalchemy as sa
from alembic import op

revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('deployment') as batch:
        batch.add_column(sa.Column('execution_backend', sa.String(32), nullable=True))


def downgrade():
    count = op.get_bind().scalar(sa.text(
        'SELECT count(*) FROM deployment WHERE execution_backend IS NOT NULL'
    ))
    if count:
        raise RuntimeError('deployment backend origin must be preserved')
    with op.batch_alter_table('deployment') as batch:
        batch.drop_column('execution_backend')
