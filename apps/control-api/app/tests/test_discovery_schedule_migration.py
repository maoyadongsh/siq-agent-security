"""Real migrations and database constraints, confined to synthetic SQLite."""
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import DiscoveryScheduleRecord, DiscoveryScheduleRun, EdgeAgent, Environment, Tenant, utcnow


def test_schedule_migration_constraints_and_preserved_history(tmp_path):
    database = tmp_path / "schedules.db"
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "TZ"}}
    env.update(SIQ_AS_DEV="1", SIQ_AS_ALLOW_SQLITE="1", SIQ_AS_DATABASE_URL=f"sqlite:///{database}",
               SIQ_AS_SIGNING_KEY_FILE=str(tmp_path / "synthetic.seed"))

    def migrate(*args):
        return subprocess.run([sys.executable, "-m", "alembic", *args],
                              cwd=Path(__file__).resolve().parents[2], env=env,
                              capture_output=True, text=True, timeout=30)

    for command in (("upgrade", "0028"), ("downgrade", "0027"), ("upgrade", "0028")):
        result = migrate(*command)
        assert result.returncode == 0, result.stderr
    engine = create_engine(f"sqlite:///{database}")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
            with Session(connection) as session:
                session.add_all([Tenant(id="a", name="a"), Tenant(id="b", name="b")])
                session.flush()
                session.add_all([Environment(id="env-a", tenant_id="a", name="a"),
                                 Environment(id="env-b", tenant_id="b", name="b")])
                session.flush()
                session.add_all([EdgeAgent(id="edge-" + key, environment_id="env-" + key,
                                          device_identity="synthetic-" + key, secret_hash="a" * 64,
                                          public_key_pem="fixture", version="test") for key in ("a", "b")])
                session.flush()
                now = utcnow()
                values = dict(tenant_id="a", environment_id="env-a", edge_agent_id="edge-a",
                              intent={}, intent_digest="b" * 64, installation_plan={},
                              installation_plan_digest="c" * 64, starts_at=now,
                              expires_at=now + timedelta(days=1), interval_seconds=900, max_runs=4)
                session.add(DiscoveryScheduleRecord(id="schedule", **values))
                session.commit()
                assert session.get(DiscoveryScheduleRecord, "schedule").status == "pending_confirmation"
                for patch in (
                    {"tenant_id": "b"}, {"edge_agent_id": "edge-b"},
                    {"interval_seconds": 899}, {"status": "approved_by_model"},
                    {"reserved_runs": 5, "last_reserved_slot": 6},
                    {"reserved_runs": 1}, {"last_reserved_slot": 0},
                    {"expires_at": now}, {"revision": -1},
                ):
                    with pytest.raises(IntegrityError), session.begin_nested():
                        session.add(DiscoveryScheduleRecord(id="invalid", **{**values, **patch}))
                        session.flush()
                session.add(DiscoveryScheduleRun(schedule_id="schedule", tenant_id="a", slot=0, task_ids=[]))
                session.commit()
                for tenant, slot in (("a", 0), ("b", 1), ("a", -1)):
                    with pytest.raises(IntegrityError), session.begin_nested():
                        session.add(DiscoveryScheduleRun(schedule_id="schedule", tenant_id=tenant,
                                                         slot=slot, task_ids=[]))
                        session.flush()
                # FK protection prevents parent deletion; no history cascade.
                with pytest.raises(IntegrityError), session.begin_nested():
                    session.execute(text("DELETE FROM discovery_schedule WHERE id='schedule'"))
                assert session.scalars(select(DiscoveryScheduleRun.slot)).all() == [0]
        result = migrate("downgrade", "0027")
        assert result.returncode != 0 and "discovery schedule history must be preserved" in result.stderr
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0028"
            assert connection.scalar(text("SELECT count(*) FROM discovery_schedule")) == 1
            assert connection.scalar(text("SELECT count(*) FROM discovery_schedule_run")) == 1
    finally:
        engine.dispose()
