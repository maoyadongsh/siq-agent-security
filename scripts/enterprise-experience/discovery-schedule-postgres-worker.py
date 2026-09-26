"""Synthetic scheduler checks; invoked only by the ephemeral PostgreSQL harness."""
import json
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path


def main():
    if os.environ.get("SIQ_SCHEDULE_PG_FIXTURE") != "ephemeral-harness-only":
        raise SystemExit("run deployment-postgres-check.py instead")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/control-api"))
    import pytest
    from app import discovery_scheduler as scheduler
    from app.config import load_settings
    from app.db import get_engine, init_db, session_scope
    from app.models import (
        AuditEvent,
        DiscoveryScheduleRecord,
        DiscoveryScheduleRun,
        EdgeAgent,
        EdgeTask,
        Environment,
        OutboxEvent,
        Tenant,
    )
    from app.outbox import audit
    from app.tests.test_enterprise_install_plan import sample
    from sqlalchemy import func, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import IntegrityError

    settings = load_settings()
    url = make_url(settings.database_url)
    assert url.drivername == "postgresql+psycopg" and url.host == "127.0.0.1" and url.database == "postgres"
    assert settings.dev_mode
    init_db(settings)
    now = datetime.now(UTC)
    stamp = now.replace(tzinfo=None)
    key = "eds-" + uuid.uuid4().hex
    plan = sample()
    plan.update(tenant_id="scheduler-fixture", environment_id="scheduler-env",
                issued_at=(now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                expires_at=(now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"))
    intent = {"schema_version": "enterprise-discovery-schedule/v1", "schedule_id": key,
              "installation_plan_sha256": scheduler.digest(plan), "device_identity": "scheduler-device",
              "starts_at": now.isoformat().replace("+00:00", "Z"),
              "expires_at": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
              "interval_seconds": 900, "max_runs": 4, "purpose": "discovery_only"}
    with session_scope() as session:
        session.add(Tenant(id=plan["tenant_id"], name="scheduler-fixture"))
        session.flush()
        session.add(Environment(id=plan["environment_id"], tenant_id=plan["tenant_id"], name="scheduler-fixture"))
        session.flush()
        session.add(EdgeAgent(id="scheduler-edge", environment_id=plan["environment_id"],
                              device_identity="scheduler-device", secret_hash="a" * 64, public_key_pem="fixture",
                              version="test", last_seen_at=stamp, capabilities={
                                  "inventory_schema": "enterprise-installed-capabilities/v1",
                                  "protocol_version": "connector-protocol.v1", "connectors": ["hermes"],
                                  "connector_versions": {"hermes": plan["connectors"][0]["version"]},
                                  "data_categories": [],
                              }))
        session.flush()
        session.add(DiscoveryScheduleRecord(
            id=key, tenant_id=plan["tenant_id"], environment_id=plan["environment_id"], edge_agent_id="scheduler-edge",
            intent=intent, intent_digest=scheduler.digest(intent), installation_plan=plan,
            installation_plan_digest=scheduler.digest(plan), status="active", starts_at=stamp,
            expires_at=stamp + timedelta(days=1), interval_seconds=900, max_runs=4,
        ))
        audit(session, plan["tenant_id"], "user", "synthetic", "install.plan.create", "environment",
              resource_id=plan["environment_id"], summary={"plan_id": plan["plan_id"], "plan_sha256": scheduler.digest(plan)})
        audit(session, plan["tenant_id"], "edge", "scheduler-device", "scan.schedule.confirm", "discovery_schedule",
              resource_id=key, summary={"intent_digest": scheduler.digest(intent)})

    args = {"tenant_id": plan["tenant_id"], "device_identity": "scheduler-device", "schedule_id": key, "now": now}
    entered, release = threading.Event(), threading.Event()
    original_audit = scheduler.audit
    hits = []

    def hold_audit(*args, **kwargs):
        hits.append(1)
        if len(hits) == 1:
            entered.set()
            assert release.wait(15)
        return original_audit(*args, **kwargs)

    def reserve():
        with session_scope() as session:
            return scheduler.reserve_discovery_round(session, **args)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(scheduler, "audit", hold_audit)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(reserve)
            try:
                assert entered.wait(10)
                second = pool.submit(reserve)
                deadline = time.monotonic() + 5
                locked = False
                while time.monotonic() < deadline:
                    with get_engine().connect() as connection:
                        locked = bool(connection.scalar(text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                            "AND wait_event_type='Lock'"
                        )))
                    if locked:
                        break
                    time.sleep(0.05)
                assert locked, "no actual PostgreSQL lock contention observed"
            finally:
                release.set()
            results = [first.result(timeout=15), second.result(timeout=15)]
    assert results[0] and results[0] == results[1] and hits == [1]
    with session_scope() as session:
        row = session.get(DiscoveryScheduleRecord, key)
        assert row.reserved_runs == 1 and row.revision == 1
        assert session.scalar(select(func.count()).select_from(DiscoveryScheduleRun).where(
            DiscoveryScheduleRun.schedule_id == key)) == 1
        assert session.scalar(select(func.count()).select_from(EdgeTask).where(
            EdgeTask.environment_id == plan["environment_id"])) == len(plan["connectors"])
        assert session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.resource_id == key, AuditEvent.action == "scan.schedule.reserve")) == 1
        for task_id in results[0]:
            session.get(EdgeTask, task_id).status = "delivered"
        session.get(EdgeAgent, "scheduler-edge").last_seen_at = stamp + timedelta(seconds=900)
    args["now"] = now + timedelta(seconds=900)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit unavailable")

    with pytest.MonkeyPatch.context() as patch, session_scope() as session:
        patch.setattr(scheduler, "audit", fail)
        models = [EdgeTask, DiscoveryScheduleRun, AuditEvent, OutboxEvent]
        before = [session.scalar(select(func.count()).select_from(model)) for model in models]
        with pytest.raises(RuntimeError, match="synthetic audit unavailable"):
            scheduler.reserve_discovery_round(session, **args)
        assert before == [session.scalar(select(func.count()).select_from(model)) for model in models]
        row = session.get(DiscoveryScheduleRecord, key)
        assert row.reserved_runs == 1 and row.revision == 1 and row.last_reserved_slot == 0
    with session_scope() as session:
        for tenant, slot in ((plan["tenant_id"], 0), ("dev-tenant", 2)):
            with pytest.raises(IntegrityError) as error, session.begin_nested():
                session.add(DiscoveryScheduleRun(schedule_id=key, tenant_id=tenant, slot=slot, task_ids=[]))
                session.flush()
            assert error.value.orig.diag.constraint_name == (
                "discovery_schedule_run_pkey" if slot == 0 else "fk_discovery_run_schedule"
            )
        assert session.scalar(select(func.count()).select_from(DiscoveryScheduleRun).where(
            DiscoveryScheduleRun.schedule_id == key)) == 1
    get_engine().dispose()
    print(json.dumps({"passed": True, "checks": {
        "scheduler_postgres_real_lock_contention": True,
        "scheduler_postgres_duplicate_single_round_task_and_audit": True,
        "scheduler_postgres_audit_failure_atomic_rollback": True,
        "scheduler_postgres_duplicate_and_cross_tenant_constraints": True,
    }}))


if __name__ == "__main__":
    main()
