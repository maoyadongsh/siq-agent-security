#!/usr/bin/env python3
"""Called only by the owned ephemeral PostgreSQL acceptance harness."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/control-api"))


def main():
    from app.adapters.openshell.operation_journal import JournalError
    from app.adapters.openshell.target_mutex import target_mutex
    from app.models import AuditEvent
    from app.tests.test_operation_journal import journal, seed
    from app.tests.test_sealed_snapshot import ORIGIN, POLICY
    from sqlalchemy import create_engine, func, select
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker

    assert os.environ.get("SIQ_JOURNAL_PG_FIXTURE") == "ephemeral-harness-only"
    assert os.environ.get("SIQ_AS_DEV") == "1"
    url = make_url(os.environ["SIQ_AS_DATABASE_URL"])
    assert url.host == "127.0.0.1" and url.database == "postgres" and url.drivername == "postgresql+psycopg"
    engine = create_engine(url)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    checks = {}
    try:
        seed(sessions)
        j = journal(sessions)
        j.prepare(POLICY)
        assert journal(sessions).read().policy == POLICY
        checks["journal_new_connection_exact_snapshot"] = True

        from app.tests.test_operation_journal import (
            test_concurrent_workers_only_one_transition,
        )

        test_concurrent_workers_only_one_transition(sessions)
        checks["journal_postgres_concurrent_cas"] = True
        j.transition(expected_state="applying", expected_epoch=1, state="applied",
                     revision="2", digest=ORIGIN.expected_digest)
        j.transition(expected_state="applied", expected_epoch=2, state="rollback_pending")
        j.transition(expected_state="rollback_pending", expected_epoch=3, state="rolled_back",
                     revision="3", digest=ORIGIN.base_digest)
        assert journal(sessions).read().restored_revision == "3"
        checks["journal_postgres_state_lifecycle"] = True
        try:
            j.transition(expected_state="applied", expected_epoch=2, state="rollback_pending")
        except JournalError as exc:
            assert str(exc) == "operation_transition_conflict"
        else:
            raise AssertionError("stale transition accepted")
        with sessions() as session:
            assert session.scalar(select(func.count()).select_from(AuditEvent).where(
                AuditEvent.resource_id == ORIGIN.deployment_id,
            )) == 5
        checks["journal_postgres_exact_transactional_audit_count"] = True
        child_code = """
import os, sys
from sqlalchemy import create_engine
from app.adapters.openshell.target_mutex import target_mutex, TargetLockError
engine = create_engine(os.environ['SIQ_AS_DATABASE_URL'])
try:
    with target_mutex(engine, 'synthetic-gateway', 'synthetic-target', timeout=0):
        pass
except TargetLockError as exc:
    assert str(exc) == 'operation_target_busy'
    sys.exit(3)
finally:
    engine.dispose()
"""
        with target_mutex(engine, "synthetic-gateway", "synthetic-target"):
            child = subprocess.run([sys.executable, "-c", child_code], capture_output=True, timeout=10, check=False)
            assert child.returncode == 3, "PostgreSQL cross-process mutex failed"
            with target_mutex(engine, "synthetic-gateway", "different-target", timeout=0):
                pass
        child = subprocess.run([sys.executable, "-c", child_code], capture_output=True, timeout=10, check=False)
        assert child.returncode == 0, "PostgreSQL cross-process mutex not released"
        checks["journal_postgres_target_mutex_across_processes"] = True
        checks["journal_postgres_target_mutex_release_and_independent_target"] = True
        print(json.dumps({"passed": True, "checks": checks}))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
