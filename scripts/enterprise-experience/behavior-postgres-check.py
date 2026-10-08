#!/usr/bin/env python3
"""Replay behavior journal cases on a disposable, loopback-only PostgreSQL.

Uses the journal's synthetic observations; no OpenShell or model calls. Only
the container created by this invocation is removed. No existing database URL
is accepted. Requires the already-installed postgres:17-alpine image.
"""

from __future__ import annotations

import inspect
import itertools
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "apps/control-api"


def worker():
    sys.path.insert(0, str(API))
    from app.db import Base
    from app.models import OpenShellBehaviorOperation
    from app.tests import test_openshell_behavior_journal as tests
    from app.tests.test_openshell_behavior_protocol import documents
    from app.tests.test_operation_journal import seed
    from sqlalchemy import create_engine, text
    from sqlalchemy import inspect as db_inspect
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(os.environ["SIQ_AS_DATABASE_URL"])
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    checks = {}
    try:
        columns = db_inspect(engine).get_columns("openshell_behavior_operation")
        assert {c["name"] for c in columns} == set(OpenShellBehaviorOperation.__table__.columns.keys())
        checks["migrated_behavior_columns_match_model"] = True
        assert "uq_openshell_behavior_nonce" in {
            c["name"] for c in db_inspect(engine).get_unique_constraints("openshell_behavior_operation")
        }
        checks["migrated_nonce_uniqueness_present"] = True
        table_names = ",".join(engine.dialect.identifier_preparer.quote(t.name) for t in Base.metadata.tables.values())

        def fresh():
            with engine.begin() as connection:
                connection.execute(text("TRUNCATE " + table_names + " CASCADE"))
            seed(sessions)
            return tests.ready.__wrapped__(sessions, documents.__wrapped__())

        for name, function in inspect.getmembers(tests, inspect.isfunction):
            if not name.startswith("test_"):
                continue
            parameter_groups = []
            for mark in getattr(function, "pytestmark", []):
                if mark.name != "parametrize":
                    raise AssertionError("unsupported test mark")
                names = [n.strip() for n in mark.args[0].split(",")]
                parameter_groups.append([
                    dict(zip(names, (value,) if len(names) == 1 else value, strict=True))
                    for value in mark.args[1]
                ])
            for index, group in enumerate(itertools.product(*parameter_groups)):
                # Every case uses the same schema produced by Alembic, with
                # fresh synthetic rows. This is not ORM create_all validation.
                fixture = fresh()
                parameters = {key: value for item in group for key, value in item.items()}
                function(database=sessions, ready=fixture, **parameters)
                checks[f"{name}[{index}]"] = True

        for phase in ("claim", "finish"):
            challenge, result, current = fresh()
            journal = tests.journal(sessions)
            journal.prepare(challenge, current)
            claim = journal.claim(challenge["verification_id"], current) if phase == "finish" else None

            def contend(phase, challenge, claim, result, current):
                try:
                    if phase == "claim":
                        return tests.journal(sessions).claim(challenge["verification_id"], current)
                    return tests.finish(sessions, claim, result, current)
                except tests.BehaviorJournalError as error:
                    assert str(error) == "behavior_owner_conflict"
                    return None

            # Hold the real row lock until both independent PostgreSQL
            # transactions are observed waiting, then release them together.
            with ThreadPoolExecutor(max_workers=2) as pool:
                with engine.begin() as connection:
                    connection.execute(text("SELECT id FROM openshell_behavior_operation FOR UPDATE")).all()
                    futures = [pool.submit(contend, phase, challenge, claim, result, current) for _ in range(2)]
                    deadline = time.monotonic() + 10
                    while True:
                        with engine.connect() as observer:
                            blocked = observer.scalar(text(
                                "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                                "AND wait_event_type='Lock' AND pid <> pg_backend_pid()"
                            ))
                        if blocked >= 2:
                            break
                        assert time.monotonic() < deadline, "two real PostgreSQL lock waiters required"
                        time.sleep(0.05)
                values = [future.result(timeout=15) for future in futures]
            assert sum(value is not None for value in values) == 1
            assert tests.audit_count(sessions) == (2 if phase == "claim" else 3)
            checks[f"postgres_contended_{phase}_one_winner"] = True
        print(json.dumps({"passed": True, "checks": checks}))
    finally:
        engine.dispose()


def main():
    if sys.argv[1:] == ["--worker"]:
        worker()
        return
    if len(sys.argv) != 2:
        raise SystemExit("usage: behavior-postgres-check.py NEW_OUTPUT_DIRECTORY")
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    image = "postgres:17-alpine"
    name = "siq-behavior-check-" + uuid.uuid4().hex[:12]
    password = secrets.token_hex(24)
    started = False

    def run(argv, **kwargs):
        return subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False, **kwargs)

    try:
        image_result = run(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
        assert image_result.returncode == 0, "existing PostgreSQL image required"
        launched = run([
            "docker", "run", "--detach", "--rm", "--name", name, "--memory", "512m", "--cpus", "1",
            "--publish", "127.0.0.1::5432", "--tmpfs", "/var/lib/postgresql/data:rw,size=256m",
            "--env", "POSTGRES_PASSWORD", image,
        ], env={**os.environ, "POSTGRES_PASSWORD": password})
        assert launched.returncode == 0, "isolated PostgreSQL startup failed"
        started = True
        port_result = run(["docker", "port", name, "5432/tcp"])
        assert port_result.returncode == 0
        port = int(port_result.stdout.strip().rsplit(":", 1)[1])
        import psycopg

        deadline = time.monotonic() + 30
        while True:
            try:
                with psycopg.connect(host="127.0.0.1", port=port, dbname="postgres", user="postgres",
                                     password=password, connect_timeout=2) as connection:
                    assert connection.execute("SELECT 1").fetchone() == (1,)
                break
            except psycopg.OperationalError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("isolated PostgreSQL readiness timeout") from None
                time.sleep(0.1)
        with tempfile.TemporaryDirectory(prefix="siq-behavior-pg-") as temporary:
            settings = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG")}
            settings.update(SIQ_AS_DEV="1", SIQ_AS_ENFORCEMENT_BACKEND="fake",
                            SIQ_AS_DATABASE_URL=f"postgresql+psycopg://postgres:{password}@127.0.0.1:{port}/postgres",
                            SIQ_AS_SIGNING_KEY_FILE=str(Path(temporary) / "signing.seed"))
            for index, command in enumerate((["upgrade", "head"], ["downgrade", "0030"], ["upgrade", "head"])):
                migrated = run([str(API / ".venv/bin/alembic"), *command], cwd=API, env=settings)
                (out / f"migration-{index}.log").write_text(migrated.stdout + migrated.stderr)
                assert migrated.returncode == 0, "migration replay failed; see private log"
            tested = run([sys.executable, __file__, "--worker"], cwd=API, env=settings)
            (out / "worker.log").write_text(tested.stdout + tested.stderr)
            assert tested.returncode == 0, "PostgreSQL journal check failed; see private log"
            proof = json.loads(tested.stdout)
            downgrade = run([str(API / ".venv/bin/alembic"), "downgrade", "0030"], cwd=API, env=settings)
            (out / "retention.log").write_text(downgrade.stdout + downgrade.stderr)
            assert downgrade.returncode != 0 and "behavior evidence must be preserved" in downgrade.stderr
            with psycopg.connect(host="127.0.0.1", port=port, dbname="postgres", user="postgres",
                                 password=password) as connection:
                assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0032",)
                assert connection.execute("SELECT count(*) FROM openshell_behavior_operation").fetchone()[0] > 0
            proof["checks"].update(clean_migration_replay=True, empty_downgrade_reupgrade=True,
                                   nonempty_automatic_downgrade_refused=True, refused_downgrade_preserves_head=True)
            legacy_down = run([str(API / ".venv/bin/alembic"), "downgrade", "0031"], cwd=API, env=settings)
            (out / "legacy-downgrade.log").write_text(legacy_down.stdout + legacy_down.stderr)
            assert legacy_down.returncode == 0
            legacy_up = run([str(API / ".venv/bin/alembic"), "upgrade", "head"], cwd=API, env=settings)
            (out / "legacy-upgrade.log").write_text(legacy_up.stdout + legacy_up.stderr)
            assert legacy_up.returncode == 0
            with psycopg.connect(host="127.0.0.1", port=port, dbname="postgres", user="postgres",
                                 password=password) as connection:
                rows = connection.execute(
                    "SELECT id,profile_id,profile_sha256 FROM openshell_behavior_operation"
                ).fetchall()
                assert rows and all(row[1:] == (None, None) for row in rows)
                proof["checks"]["legacy_rows_preserved_without_invented_profile"] = True
                try:
                    with connection.transaction():
                        connection.execute("UPDATE openshell_behavior_operation SET profile_id='approved'")
                except psycopg.errors.CheckViolation:
                    proof["checks"]["partial_profile_reference_database_rejected"] = True
                else:
                    raise AssertionError("profile metadata pair constraint missing")
                connection.execute(
                    "UPDATE openshell_behavior_operation SET profile_id=%s,profile_sha256=%s WHERE id=%s",
                    ("approved", "a" * 64, rows[0][0]),
                )
            profile_down = run([str(API / ".venv/bin/alembic"), "downgrade", "0031"], cwd=API, env=settings)
            (out / "profile-retention.log").write_text(profile_down.stdout + profile_down.stderr)
            assert profile_down.returncode != 0 and "operator profile evidence must be preserved" in profile_down.stderr
            with psycopg.connect(host="127.0.0.1", port=port, dbname="postgres", user="postgres",
                                 password=password) as connection:
                assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == ("0032",)
                assert connection.execute(
                    "SELECT profile_id,profile_sha256 FROM openshell_behavior_operation WHERE id=%s", (rows[0][0],)
                ).fetchone() == ("approved", "a" * 64)
            proof["checks"]["profile_evidence_downgrade_refused_and_preserved"] = True
            proof.update(image_id=image_result.stdout.strip(), migrated_head="0032", model_calls=0,
                         openshell_calls=0, external_database_access=False)
            (out / "result.json").write_text(json.dumps(proof, indent=2) + "\n")
    finally:
        if started:
            removed = run(["docker", "rm", "-f", name])
            (out / "cleanup.json").write_text(json.dumps({"container": name, "removed": removed.returncode == 0}) + "\n")
            if removed.returncode != 0:
                raise RuntimeError("owned PostgreSQL container cleanup failed")
    print(json.dumps({"passed": True, "checks": len(proof["checks"]), "owned_container_removed": True}))


if __name__ == "__main__":
    main()
