"""Backend provenance survives upgrade and cannot be discarded by downgrade."""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models import ChangeRequest, Deployment, DesiredPolicy, Environment, Tenant


def test_backend_origin_migration_preserves_legacy_and_refuses_destructive_downgrade(tmp_path):
    database = tmp_path / "backend-origin.db"
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "TZ"}}
    env.update(
        SIQ_AS_DEV="1",
        SIQ_AS_ALLOW_SQLITE="1",
        SIQ_AS_DATABASE_URL=f"sqlite:///{database}",
        SIQ_AS_SIGNING_KEY_FILE=str(tmp_path / "synthetic.seed"),
    )

    def migrate(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    for args in [("upgrade", "0029"), ("downgrade", "0028"), ("upgrade", "0029")]:
        result = migrate(*args)
        assert result.returncode == 0, result.stderr
    engine = create_engine(f"sqlite:///{database}")
    try:
        with Session(engine) as session:
            session.add(Tenant(id="t", name="synthetic"))
            session.flush()
            session.add(Environment(id="e", tenant_id="t", name="synthetic"))
            session.flush()
            session.add(DesiredPolicy(id="p", tenant_id="t", name="synthetic", selector={}))
            session.flush()
            session.add(ChangeRequest(id="c", tenant_id="t", policy_id="p", proposer_user_id="u", idempotency_key="k"))
            session.flush()
            session.add(
                Deployment(
                    id="d",
                    tenant_id="t",
                    environment_id="e",
                    change_request_id="c",
                    target="synthetic-target",
                    to_revision="r",
                    execution_backend=None,
                )
            )
            session.commit()
        # Null provenance can round-trip without guessing a backend or losing the row.
        assert migrate("downgrade", "0028").returncode == 0
        assert migrate("upgrade", "0029").returncode == 0
        with Session(engine) as session:
            row = session.get(Deployment, "d")
            assert row.execution_backend is None and row.target == "synthetic-target"
            row.execution_backend = "fake"
            session.commit()
        result = migrate("downgrade", "0028")
        assert result.returncode != 0 and "deployment backend origin must be preserved" in result.stderr
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0029"
            assert connection.scalar(text("SELECT execution_backend FROM deployment WHERE id='d'")) == "fake"
    finally:
        engine.dispose()
