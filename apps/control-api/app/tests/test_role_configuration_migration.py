"""Replay only against a fresh synthetic SQLite database, never deployed state."""
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AgentAsset, EdgeAgent, EdgeTask, Environment, RoleConfigurationObservation, Tenant, utcnow


def test_role_configuration_migration_and_tenant_constraints(tmp_path):
    database = tmp_path / 'history.db'
    env = {key: value for key, value in os.environ.items() if key in {'PATH', 'LANG', 'LC_ALL', 'TZ'}}
    env.update(SIQ_AS_DEV='1', SIQ_AS_ALLOW_SQLITE='1', SIQ_AS_DATABASE_URL=f'sqlite:///{database}',
               SIQ_AS_SIGNING_KEY_FILE=str(tmp_path / 'fixture.seed'))

    def migrate(*args):
        return subprocess.run([sys.executable, '-m', 'alembic', *args], env=env,
                              cwd=Path(__file__).resolve().parents[2], capture_output=True, timeout=30)

    assert migrate('upgrade', '0027').returncode == 0
    assert migrate('downgrade', '0026').returncode == 0
    assert migrate('upgrade', '0027').returncode == 0
    engine = create_engine(f'sqlite:///{database}')
    try:
        assert 'role_configuration_observation' in inspect(engine).get_table_names()
        with engine.connect() as connection:
            connection.exec_driver_sql('PRAGMA foreign_keys=ON')
            connection.commit()
            with Session(connection) as session:
                session.add_all([Tenant(id='tenant-a', name='a'), Tenant(id='tenant-b', name='b')])
                session.flush()
                environment = Environment(id='env', tenant_id='tenant-a', name='fixture')
                session.add(environment)
                session.flush()
                edge = EdgeAgent(id='edge', environment_id='env', device_identity='fixture',
                                 secret_hash='0' * 64, public_key_pem='fixture', version='test')
                task = EdgeTask(id='task', environment_id='env', task_type='scan',
                                expires_at=utcnow() + timedelta(hours=1))
                asset = AgentAsset(id='asset', tenant_id='tenant-a', name='fixture')
                session.add_all([edge, task, asset, AgentAsset(id='other-asset', tenant_id='tenant-a', name='other')])
                session.flush()
                values = dict(tenant_id='tenant-a', asset_id='asset', edge_agent_id='edge', task_id='task',
                              batch_digest='a' * 64, framework_source={}, skill_source_roots=None, observed_at=utcnow())
                session.add(RoleConfigurationObservation(id='history', **values))
                session.commit()
                for patch in ({'tenant_id': 'tenant-b', 'asset_id': 'other-asset'}, {}):
                    with pytest.raises(IntegrityError) as error, session.begin_nested():
                        session.add(RoleConfigurationObservation(id='invalid', **{**values, **patch}))
                        session.flush()
                    assert ('FOREIGN KEY' if patch else 'UNIQUE') in str(error.value)
                assert session.scalar(select(RoleConfigurationObservation.id)) == 'history'
        blocked = migrate('downgrade', '0026')
        assert blocked.returncode != 0 and b'history must be preserved' in blocked.stderr
        assert 'role_configuration_observation' in inspect(engine).get_table_names()
    finally:
        engine.dispose()
