"""Replay real migrations and refuse to discard persisted recovery material."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.tests.test_operation_journal import journal, seed
from app.tests.test_sealed_snapshot import POLICY


def test_journal_migration_replays_and_protects_populated_history(tmp_path):
    database = tmp_path / "journal-migration.db"
    environment = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "TZ"}}
    environment.update(
        SIQ_AS_DEV="1", SIQ_AS_ALLOW_SQLITE="1", SIQ_AS_DATABASE_URL=f"sqlite:///{database}",
        SIQ_AS_SIGNING_KEY_FILE=str(tmp_path / "synthetic.seed"),
    )

    def migrate(*args):
        return subprocess.run([sys.executable, "-m", "alembic", *args], env=environment,
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=30)

    for args in [("upgrade", "0030"), ("downgrade", "0029"), ("upgrade", "0030")]:
        result = migrate(*args)
        assert result.returncode == 0, result.stderr
    engine = create_engine(f"sqlite:///{database}")
    try:
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        seed(sessions)
        journal(sessions).prepare(POLICY)
        result = migrate("downgrade", "0029")
        assert result.returncode != 0 and "openshell recovery journal must be preserved" in result.stderr
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0030"
        assert journal(sessions).read().policy == POLICY
    finally:
        engine.dispose()
