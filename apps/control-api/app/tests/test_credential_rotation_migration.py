import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.models import EdgeAgent, EdgeCredentialRotation, Environment, Tenant


def test_clean_migration_replay_and_populated_downgrade_guard(tmp_path):
    database = tmp_path / 'rotation-migration.db'
    url = f'sqlite:///{database}'
    environment = dict(os.environ, SIQ_AS_DEV='1', SIQ_AS_ALLOW_SQLITE='1', SIQ_AS_DATABASE_URL=url)
    root = Path(__file__).resolve().parents[2]

    def migrate(*arguments):
        return subprocess.run([sys.executable, '-m', 'alembic', *arguments], cwd=root, env=environment,
                              capture_output=True, text=True, timeout=60)

    upgraded = migrate('upgrade', 'head')
    assert upgraded.returncode == 0, upgraded.stderr
    engine = create_engine(url)
    assert 'edge_credential_rotation' in inspect(engine).get_table_names()
    downgraded = migrate('downgrade', '0025')
    assert downgraded.returncode == 0, downgraded.stderr
    assert 'edge_credential_rotation' not in inspect(engine).get_table_names()
    replayed = migrate('upgrade', 'head')
    assert replayed.returncode == 0, replayed.stderr
    with Session(engine) as session:
        session.add(Tenant(id='fixture-tenant', name='Fixture'))
        session.flush()
        session.add(Environment(id='fixture-env', tenant_id='fixture-tenant', name='Fixture', env_type='host'))
        session.flush()
        session.add(EdgeAgent(id='fixture-edge', environment_id='fixture-env', device_identity='fixture-device',
                              secret_hash='b' * 64, public_key_pem='synthetic only', version='test'))
        session.flush()
        session.add(EdgeCredentialRotation(edge_agent_id='fixture-edge',
                    rotation_id='11111111-1111-4111-8111-111111111111', request_digest='d' * 64,
                    old_secret_hash='a' * 64, new_secret_hash='b' * 64))
        session.commit()
    refused = migrate('downgrade', '0025')
    assert refused.returncode != 0
    assert 'credential rotation history must be preserved' in refused.stderr
    with Session(engine) as session:
        row = session.scalar(select(EdgeCredentialRotation))
        assert row.old_secret_hash == 'a' * 64 and row.new_secret_hash == 'b' * 64
        assert session.get(EdgeAgent, 'fixture-edge').secret_hash == 'b' * 64
    engine.dispose()
