"""Encrypted recovery journal; no automatic deletion of recovery material."""
import sqlalchemy as sa
from alembic import op

revision = '0030'
down_revision = '0029'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'openshell_operation',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), sa.ForeignKey('tenant.id'), nullable=False),
        sa.Column('deployment_id', sa.String(64), sa.ForeignKey('deployment.id'), nullable=False),
        sa.Column('origin', sa.JSON(), nullable=False),
        sa.Column('sealed_snapshot', sa.JSON(), nullable=False),
        sa.Column('state', sa.String(32), nullable=False),
        sa.Column('epoch', sa.Integer(), nullable=False),
        sa.Column('applied_revision', sa.String(64), nullable=True),
        sa.Column('applied_digest', sa.String(64), nullable=True),
        sa.Column('restored_revision', sa.String(64), nullable=True),
        sa.Column('restored_digest', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('deployment_id', name='uq_openshell_operation_deployment'),
        sa.CheckConstraint('epoch >= 0', name='ck_openshell_operation_epoch'),
        sa.CheckConstraint(
            "state IN ('prepared','applying','applied','rollback_pending','rolled_back','unknown')",
            name='ck_openshell_operation_state',
        ),
    )
    op.create_index('ix_openshell_operation_tenant_id', 'openshell_operation', ['tenant_id'])


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT count(*) FROM openshell_operation')):
        raise RuntimeError('openshell recovery journal must be preserved')
    op.drop_index('ix_openshell_operation_tenant_id', table_name='openshell_operation')
    op.drop_table('openshell_operation')
