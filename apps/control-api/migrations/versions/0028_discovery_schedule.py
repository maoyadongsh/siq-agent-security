"""Bounded discovery plans and non-replayable per-slot reservations."""
import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("environment") as batch:
        batch.create_unique_constraint("uq_environment_tenant_id", ["tenant_id", "id"])
    with op.batch_alter_table("edge_agent") as batch:
        batch.create_unique_constraint("uq_edge_environment_id", ["environment_id", "id"])
    op.create_table(
        "discovery_schedule",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("environment_id", sa.String(64), nullable=False),
        sa.Column("edge_agent_id", sa.String(64), nullable=False),
        sa.Column("intent", sa.JSON(), nullable=False),
        sa.Column("intent_digest", sa.String(64), nullable=False),
        sa.Column("installation_plan", sa.JSON(), nullable=False),
        sa.Column("installation_plan_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("max_runs", sa.Integer(), nullable=False),
        sa.Column("reserved_runs", sa.Integer(), nullable=False),
        sa.Column("last_reserved_slot", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id", name="uq_discovery_schedule_tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id", "environment_id"], ["environment.tenant_id", "environment.id"],
                                name="fk_discovery_schedule_environment"),
        sa.ForeignKeyConstraint(["environment_id", "edge_agent_id"], ["edge_agent.environment_id", "edge_agent.id"],
                                name="fk_discovery_schedule_device"),
        sa.CheckConstraint("status IN ('pending_confirmation', 'active', 'paused', 'revoked')",
                           name="ck_discovery_schedule_status"),
        sa.CheckConstraint("interval_seconds >= 900 AND interval_seconds <= 86400",
                           name="ck_discovery_schedule_interval"),
        sa.CheckConstraint("max_runs >= 1 AND max_runs <= 2880 AND reserved_runs >= 0 AND reserved_runs <= max_runs",
                           name="ck_discovery_schedule_budget"),
        sa.CheckConstraint("expires_at > starts_at AND revision >= 0", name="ck_discovery_schedule_window"),
        sa.CheckConstraint("(reserved_runs = 0 AND last_reserved_slot IS NULL) OR "
                           "(reserved_runs > 0 AND last_reserved_slot IS NOT NULL AND "
                           "last_reserved_slot >= 0 AND reserved_runs <= last_reserved_slot + 1)",
                           name="ck_discovery_schedule_progress"),
    )
    for field in ("tenant_id", "edge_agent_id"):
        op.create_index(f"ix_discovery_schedule_{field}", "discovery_schedule", [field])
    op.create_table(
        "discovery_schedule_run",
        sa.Column("schedule_id", sa.String(64), primary_key=True),
        sa.Column("slot", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("task_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "schedule_id"], ["discovery_schedule.tenant_id", "discovery_schedule.id"],
                                name="fk_discovery_run_schedule"),
        sa.CheckConstraint("slot >= 0", name="ck_discovery_run_slot"),
    )
    op.create_index("ix_discovery_schedule_run_tenant_id", "discovery_schedule_run", ["tenant_id"])


def downgrade():
    connection = op.get_bind()
    if (connection.scalar(sa.text("SELECT count(*) FROM discovery_schedule"))
            or connection.scalar(sa.text("SELECT count(*) FROM discovery_schedule_run"))):
        raise RuntimeError("discovery schedule history must be preserved")
    op.drop_table("discovery_schedule_run")
    op.drop_table("discovery_schedule")
    with op.batch_alter_table("edge_agent") as batch:
        batch.drop_constraint("uq_edge_environment_id", type_="unique")
    with op.batch_alter_table("environment") as batch:
        batch.drop_constraint("uq_environment_tenant_id", type_="unique")
