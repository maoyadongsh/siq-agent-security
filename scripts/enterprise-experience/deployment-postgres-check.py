#!/usr/bin/env python3
"""Ephemeral loopback PostgreSQL migration and durable deployment race checks."""

import hashlib
import importlib.util
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def worker():
    sys.path.insert(0, str(ROOT / "apps/control-api"))
    import pytest
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from app.db import get_engine
    from app.main import app
    from app.routers import deployment_submission as route
    from app.tests import test_deployment_submission as tests
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    checks = {}
    headers = {
        "X-Dev-Tenant-Id": "dev-tenant",
        "X-Dev-User-Id": "pg-owner",
        "X-Dev-Roles": "tenant_admin,security_admin,agent_owner,platform_operator,auditor",
    }
    with TestClient(app) as client:
        env = client.post(
            "/api/v1/environments",
            headers=headers,
            json={"name": "isolated-postgres", "mode": "enforce"},
        ).json()
        tests.test_durable_submit_replay_and_exact_readback(client, headers, env)
        checks["postgres_submit_replay_and_audit"] = True
        for name in [
            "test_persisted_reservation_survives_unknown_execute_failure",
            "test_concurrent_delivery_reads_claim_without_second_execution",
            "test_reservation_audit_failure_never_calls_execute",
            "test_binding_revoked_during_reservation_is_rechecked_before_execute",
        ]:
            with pytest.MonkeyPatch.context() as patch:
                getattr(tests, name)(client, headers, env, patch)
            checks[name] = True
        for outcome in ("success", "adapter_failure", "audit_failure_after_apply"):
            with (
                tempfile.TemporaryDirectory(prefix="siq-pg-authority-") as authority_dir,
                pytest.MonkeyPatch.context() as patch,
            ):
                tests.test_openshell_execution_is_never_replayed_after_effect(
                    client, headers, env, patch, outcome, Path(authority_dir)
                )
            checks["postgres_openshell_" + outcome] = True
        # Two independent transactions arrive before reservation commit.
        body = tests.prepared(client, headers, env)
        entered, release = threading.Event(), threading.Event()
        original_snapshot, original_execute = route._snapshot, route.execute_deployment
        hits, executions = [], []

        def hold_first(*args):
            value = original_snapshot(*args)
            hits.append(1)
            if len(hits) == 1:
                entered.set()
                assert release.wait(10)
            return value

        def execute_once(*args, **kwargs):
            executions.append(1)
            return original_execute(*args, **kwargs)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(route, "_snapshot", hold_first)
            patch.setattr(route, "execute_deployment", execute_once)
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(tests.post, client, headers, body)
                assert entered.wait(10)
                second = pool.submit(tests.post, client, headers, body)
                locked = False
                try:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        with get_engine().connect() as connection:
                            locked = bool(
                                connection.scalar(
                                    text(
                                        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"
                                    )
                                )
                            )
                        if locked:
                            break
                        time.sleep(0.05)
                    assert locked, "expected actual PostgreSQL row lock contention"
                finally:
                    release.set()
                results = [first.result(timeout=15), second.result(timeout=15)]
        assert sorted(r.status_code for r in results) == [200, 201]
        assert results[0].json()["deployment_id"] == results[1].json()["deployment_id"]
        assert executions == [1]
        checks["postgres_row_lock_serializes_precommit_duplicate"] = True
        # Exercise this older guard directly: revision 0020 deliberately stops
        # a normal downgrade before Alembic can reach revision 0017.
        spec = importlib.util.spec_from_file_location(
            "submission_migration",
            ROOT / "apps/control-api/migrations/versions/0017_deployment_submission.py",
        )
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with get_engine().connect() as connection:
            before = connection.scalar(text("SELECT count(*) FROM deployment_submission"))
            assert before > 0
            with (
                Operations.context(MigrationContext.configure(connection)),
                pytest.raises(RuntimeError, match="refusing destructive downgrade"),
            ):
                migration.downgrade()
            assert connection.scalar(text("SELECT count(*) FROM deployment_submission")) == before
            connection.rollback()
        checks["populated_reservations_direct_migration_guard"] = True
    print(json.dumps({"passed": True, "checks": checks}))


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "--worker":
        worker()
        return
    if len(sys.argv) != 2:
        raise SystemExit("usage: deployment-postgres-check.py NEW_OUTPUT_DIRECTORY")
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    name = "siq-deployment-check-" + uuid.uuid4().hex[:12]
    image = "postgres:17-alpine"
    password = secrets.token_hex(24)
    env = {**os.environ, "POSTGRES_PASSWORD": password}
    started = False

    def run(argv, **kwargs):
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=90, check=False, **kwargs
        )

    try:
        image_id = run(["docker", "image", "inspect", image, "--format", "{{.Id}}"])
        assert image_id.returncode == 0, (
            "existing PostgreSQL image required; no automatic pull"
        )
        launched = run(
            [
                "docker",
                "run",
                "--detach",
                "--rm",
                "--name",
                name,
                "--memory",
                "512m",
                "--cpus",
                "1",
                "--publish",
                "127.0.0.1::5432",
                "--tmpfs",
                "/var/lib/postgresql/data:rw,size=256m",
                "--env",
                "POSTGRES_PASSWORD",
                image,
            ],
            env=env,
        )
        assert launched.returncode == 0, "isolated PostgreSQL did not start"
        started = True
        port = (
            run(["docker", "port", name, "5432/tcp"]).stdout.strip().rsplit(":", 1)[1]
        )
        # Probe the same published TCP endpoint used by Alembic. The image's
        # bootstrap Unix-socket server can report ready before final startup.
        import psycopg

        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with psycopg.connect(
                    host="127.0.0.1", port=int(port), dbname="postgres",
                    user="postgres", password=password, connect_timeout=2,
                ) as connection:
                    assert connection.execute("SELECT 1").fetchone() == (1,)
                break
            except psycopg.OperationalError:
                time.sleep(0.1)
        else:
            raise RuntimeError("isolated PostgreSQL readiness timeout")
        with tempfile.TemporaryDirectory(prefix="siq-pg-submission-") as temporary:
            settings = {
                k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG")
            }
            settings.update(
                {
                    "SIQ_AS_DEV": "1",
                    "SIQ_AS_ENFORCEMENT_BACKEND": "fake",
                    "SIQ_AS_DATABASE_URL": f"postgresql+psycopg://postgres:{password}@127.0.0.1:{port}/postgres",
                    "SIQ_AS_SIGNING_KEY_FILE": str(Path(temporary) / "signing.seed"),
                }
            )
            api = ROOT / "apps/control-api"
            for index, command in enumerate(
                [
                    ["upgrade", "0017"], ["downgrade", "0016"],
                    ["upgrade", "head"], ["downgrade", "0020"],
                    ["upgrade", "head"],
                ]
            ):
                result = run(
                    [str(api / ".venv/bin/alembic"), *command], cwd=api, env=settings
                )
                (out / f"migration-{index}.log").write_text(
                    (result.stdout + result.stderr).replace(password, "[REDACTED]")
                )
                assert result.returncode == 0, (
                    "isolated migration failed; inspect redacted migration log"
                )
            with psycopg.connect(
                host="127.0.0.1", port=int(port), dbname="postgres",
                user="postgres", password=password, connect_timeout=2,
            ) as connection:
                migrated_head = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            result = run(
                [sys.executable, str(Path(__file__).resolve()), "--worker"],
                cwd=api,
                env=settings,
            )
            (out / "worker.log").write_text(
                (result.stdout + result.stderr).replace(password, "[REDACTED]")
            )
            assert result.returncode == 0, (
                "isolated PostgreSQL acceptance failed; inspect redacted worker log"
            )
            proof = json.loads(result.stdout)
            down = run(
                [str(api / ".venv/bin/alembic"), "downgrade", "0016"],
                cwd=api,
                env=settings,
            )
            (out / "refused-downgrade.log").write_text(
                (down.stdout + down.stderr).replace(password, "[REDACTED]")
            )
            assert (
                down.returncode != 0
                and "device-scoped discovery cannot be merged" in down.stderr
            )
            proof["checks"]["device_scope_automatic_downgrade_refused"] = True
            with psycopg.connect(
                host="127.0.0.1", port=int(port), dbname="postgres",
                user="postgres", password=password, connect_timeout=2,
            ) as connection:
                assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == migrated_head
                assert connection.execute("SELECT count(*) FROM deployment_submission").fetchone()[0] > 0
            proof["checks"]["refused_downgrade_keeps_head_and_reservations"] = True
            proof["checks"]["empty_supported_intervals_downgrade_and_reupgrade"] = True
            scheduler_worker = ROOT / "scripts/enterprise-experience/discovery-schedule-postgres-worker.py"
            scheduler_result = run(
                [sys.executable, str(scheduler_worker)], cwd=api,
                env={**settings, "SIQ_SCHEDULE_PG_FIXTURE": "ephemeral-harness-only"},
            )
            (out / "scheduler-worker.log").write_text(
                (scheduler_result.stdout + scheduler_result.stderr).replace(password, "[REDACTED]")
            )
            assert scheduler_result.returncode == 0, "scheduler PostgreSQL check failed; inspect redacted log"
            scheduler_proof = json.loads(scheduler_result.stdout)
            assert scheduler_proof["passed"] is True
            proof["checks"].update(scheduler_proof["checks"])
            proof["scheduler_worker_sha256"] = hashlib.sha256(scheduler_worker.read_bytes()).hexdigest()
            scheduler_down = run(
                [str(api / ".venv/bin/alembic"), "downgrade", "0027"], cwd=api, env=settings,
            )
            (out / "scheduler-refused-downgrade.log").write_text(
                (scheduler_down.stdout + scheduler_down.stderr).replace(password, "[REDACTED]")
            )
            assert scheduler_down.returncode != 0 and "discovery schedule history must be preserved" in scheduler_down.stderr
            with psycopg.connect(
                host="127.0.0.1", port=int(port), dbname="postgres",
                user="postgres", password=password, connect_timeout=2,
            ) as connection:
                assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == migrated_head
                assert connection.execute("SELECT count(*) FROM discovery_schedule_run").fetchone()[0] == 1
            proof["checks"]["scheduler_postgres_populated_downgrade_refused"] = True
            proof.update(
                {
                    "schema_version": "deployment-postgres-check/v1",
                    "database_image_id": image_id.stdout.strip(),
                    "ephemeral_database": True,
                    "production_identity_tested": False,
                    "migrated_head": migrated_head[0],
                    "script_sha256": hashlib.sha256(
                        Path(__file__).read_bytes()
                    ).hexdigest(),
                }
            )
            (out / "result.json").write_text(json.dumps(proof, indent=2) + "\n")
            print(json.dumps({"passed": True, "checks": len(proof["checks"])}))
    finally:
        if started:
            cleanup = run(["docker", "rm", "-f", name])
            assert cleanup.returncode == 0, "isolated PostgreSQL cleanup failed"


if __name__ == "__main__":
    main()
