import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app import discovery_scheduler as scheduler
from app.db import session_scope
from app.models import (
    AuditEvent,
    DiscoveryScheduleRecord,
    DiscoveryScheduleRun,
    EdgeAgent,
    EdgeTask,
    OutboxEvent,
    Tenant,
)
from app.outbox import audit
from app.tests.test_initial_scan import catalog, initial_context  # noqa: F401


@pytest.fixture
def confirmed(request):
    env, headers, plan = request.getfixturevalue("initial_context")
    now = datetime.now(UTC)
    identity = headers["X-Edge-Identity"]
    key = "eds-" + uuid.uuid4().hex
    intent = dict(schema_version="enterprise-discovery-schedule/v1", schedule_id=key,
                  installation_plan_sha256=scheduler.digest(plan), device_identity=identity,
                  starts_at=now.isoformat().replace("+00:00", "Z"),
                  expires_at=(now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                  interval_seconds=900, max_runs=4, purpose="discovery_only")
    with session_scope() as session:
        if session.get(Tenant, plan["tenant_id"]) is None:
            session.add(Tenant(id=plan["tenant_id"], name="synthetic-scheduler-tenant"))
            session.flush()
        edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity))
        session.add(DiscoveryScheduleRecord(
            id=key, tenant_id=plan["tenant_id"], environment_id=env, edge_agent_id=edge.id,
            intent=intent, intent_digest=scheduler.digest(intent), installation_plan=plan,
            installation_plan_digest=scheduler.digest(plan), status="active",
            starts_at=now.replace(tzinfo=None), expires_at=(now + timedelta(days=1)).replace(tzinfo=None),
            interval_seconds=900, max_runs=4,
        ))
        # Synthetic confirmation only: the product confirmation endpoint is not implemented yet.
        audit(session, plan["tenant_id"], "edge", identity, "scan.schedule.confirm", "discovery_schedule",
              resource_id=key, summary={"intent_digest": scheduler.digest(intent)})
    return dict(tenant_id=plan["tenant_id"], device_identity=identity, schedule_id=key, now=now)


def counts(session):
    return [session.scalar(select(func.count()).select_from(model))
            for model in (EdgeTask, DiscoveryScheduleRun, AuditEvent, OutboxEvent)]


def test_reservation_exact_tasks_replay_and_backpressure(confirmed):
    with session_scope() as session:
        ids = scheduler.reserve_discovery_round(session, **confirmed)
        before = counts(session)
        assert scheduler.reserve_discovery_round(session, **confirmed) == ids
        assert counts(session) == before
        row = session.get(DiscoveryScheduleRecord, confirmed["schedule_id"])
        assert row.reserved_runs == 1 and row.revision == 1
        for task_id in ids:
            task = session.get(EdgeTask, task_id)
            assert task.signature and task.payload["target_device_identity"] == confirmed["device_identity"]
            assert task.payload["scope"] == row.installation_plan["connectors"][0]["scope"]
        later = {**confirmed, "now": confirmed["now"] + timedelta(seconds=900)}
        edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == confirmed["device_identity"]))
        edge.last_seen_at = later["now"].replace(tzinfo=None)
        session.flush()
        assert scheduler.reserve_discovery_round(session, **later) is None
        assert counts(session) == before
        for task_id in ids:
            session.get(EdgeTask, task_id).status = "delivered"
        session.flush()
        next_ids = scheduler.reserve_discovery_round(session, **later)
        assert next_ids and not set(next_ids) & set(ids)
        assert row.reserved_runs == 2


@pytest.mark.parametrize("fault", ["tenant", "device", "revoked", "digest", "missing_confirmation", "stale", "version"])
def test_denial_creates_nothing(confirmed, fault):
    args = dict(confirmed)
    with session_scope() as session:
        row = session.get(DiscoveryScheduleRecord, confirmed["schedule_id"])
        edge = session.get(EdgeAgent, row.edge_agent_id)
        if fault == "tenant":
            args["tenant_id"] = "foreign"
        elif fault == "device":
            args["device_identity"] = "foreign"
        elif fault == "revoked":
            edge.revoked_at = confirmed["now"].replace(tzinfo=None)
        elif fault == "digest":
            row.intent_digest = "f" * 64
        elif fault == "missing_confirmation":
            event = session.scalar(select(AuditEvent).where(AuditEvent.resource_id == row.id))
            event.decision = "deny"
        elif fault == "stale":
            edge.last_seen_at = confirmed["now"].replace(tzinfo=None) - timedelta(days=1)
        else:
            edge.capabilities = {**edge.capabilities, "connector_versions": {"hermes": "unknown"}}
        session.flush()
        before = counts(session)
        message = {
            "tenant": "unavailable", "device": "unavailable", "revoked": "unavailable",
            "digest": "integrity_failed", "missing_confirmation": "confirmation_missing",
            "stale": "capabilities_unverified", "version": "capabilities_unverified",
        }[fault]
        with pytest.raises(ValueError, match=message):
            scheduler.reserve_discovery_round(session, **args)
        assert counts(session) == before
        assert row.reserved_runs == 0


@pytest.mark.parametrize("stage", ["audit", "emit_event", "sign_task_payload"])
def test_failure_rolls_back_even_when_caller_catches_exception(confirmed, monkeypatch, stage):
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(scheduler, stage, fail)
    with session_scope() as session:
        before = counts(session)
        with pytest.raises(RuntimeError, match="synthetic failure"):
            scheduler.reserve_discovery_round(session, **confirmed)
        assert counts(session) == before
        row = session.get(DiscoveryScheduleRecord, confirmed["schedule_id"])
        assert row.reserved_runs == 0 and row.last_reserved_slot is None and row.revision == 0


@pytest.mark.parametrize("condition", ["paused", "pending_confirmation", "revoked", "expired", "budget"])
def test_inactive_expired_or_budget_exhausted_never_schedules(confirmed, condition):
    args = dict(confirmed)
    with session_scope() as session:
        row = session.get(DiscoveryScheduleRecord, confirmed["schedule_id"])
        if condition == "expired":
            args["now"] += timedelta(days=1)
        elif condition == "budget":
            row.reserved_runs, row.last_reserved_slot = row.max_runs, 3
        else:
            row.status = condition
        session.flush()
        before = counts(session)
        assert scheduler.reserve_discovery_round(session, **args) is None
        assert counts(session) == before


def test_lost_replay_task_does_not_create_replacement(confirmed):
    with session_scope() as session:
        ids = scheduler.reserve_discovery_round(session, **confirmed)
        session.delete(session.get(EdgeTask, ids[0]))
        session.flush()
        before = counts(session)
        with pytest.raises(ValueError, match="replay_unavailable"):
            scheduler.reserve_discovery_round(session, **confirmed)
        assert counts(session) == before


@pytest.mark.parametrize("tamper", ["connector", "roots", "include", "task_type", "inventory_kind", "device"])
def test_replay_rejects_tampered_task_scope(confirmed, tamper):
    with session_scope() as session:
        ids = scheduler.reserve_discovery_round(session, **confirmed)
        task = session.get(EdgeTask, ids[0])
        payload = dict(task.payload)
        if tamper == "connector":
            payload["connector"] = "openclaw"
        elif tamper == "roots":
            payload["scope"] = {**payload["scope"], "roots": ["/tmp/other"]}
        elif tamper == "include":
            payload["scope"] = {**payload["scope"], "include": ["SOUL.md"]}
        elif tamper == "task_type":
            task.task_type = "skill_scan"
        elif tamper == "inventory_kind":
            payload["inventory_kind"] = "skills"
        else:
            payload["target_device_identity"] = "other-device"
        task.payload = payload
        session.flush()
        before = counts(session)
        with pytest.raises(ValueError, match="replay_unavailable"):
            scheduler.reserve_discovery_round(session, **confirmed)
        assert counts(session) == before


def test_replay_rejects_duplicate_or_missing_task_ids(confirmed):
    with session_scope() as session:
        ids = scheduler.reserve_discovery_round(session, **confirmed)
        run = session.get(DiscoveryScheduleRun, (confirmed["schedule_id"], 0))
        before = counts(session)
        run.task_ids = [ids[0], ids[0]]
        session.flush()
        with pytest.raises(ValueError, match="replay_unavailable"):
            scheduler.reserve_discovery_round(session, **confirmed)
        assert counts(session) == before
        run.task_ids = ids + ["tsk-does-not-exist"]
        session.flush()
        with pytest.raises(ValueError, match="replay_unavailable"):
            scheduler.reserve_discovery_round(session, **confirmed)
        assert counts(session) == before


@pytest.mark.parametrize("invalid_id", [[], {}], ids=["array", "object"])
def test_replay_rejects_unhashable_task_id_without_state_changes(confirmed, invalid_id):
    with session_scope() as session:
        ids = scheduler.reserve_discovery_round(session, **confirmed)
        run = session.get(DiscoveryScheduleRun, (confirmed["schedule_id"], 0))
        run.task_ids = ids + [invalid_id]
        session.flush()
        row = session.get(DiscoveryScheduleRecord, confirmed["schedule_id"])
        budget = (row.reserved_runs, row.last_reserved_slot, row.revision)
        before = counts(session)
        with pytest.raises(ValueError, match="^discovery_schedule_replay_unavailable$"):
            scheduler.reserve_discovery_round(session, **confirmed)
        assert counts(session) == before
        assert (row.reserved_runs, row.last_reserved_slot, row.revision) == budget
        assert run.task_ids == ids + [invalid_id]


@pytest.fixture
def confirmed_directory(request):
    env, headers, plan = request.getfixturevalue("initial_context")
    now = datetime.now(UTC)
    identity = headers["X-Edge-Identity"]
    key = "eds-" + uuid.uuid4().hex
    version = plan["connectors"][0]["version"]
    directory_plan = {**plan, "connectors": [{
        "id": "directory", "version": version, "artifact_sha256": "c" * 64,
        "protocol_version": "connector-protocol.v1",
        "scope": {"roots": ["/home/user/skills"], "include": ["SKILL.md", "config.yaml"]}}]}
    intent = dict(schema_version="enterprise-discovery-schedule/v1", schedule_id=key,
                  installation_plan_sha256=scheduler.digest(directory_plan), device_identity=identity,
                  starts_at=now.isoformat().replace("+00:00", "Z"),
                  expires_at=(now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                  interval_seconds=900, max_runs=4, purpose="discovery_only")
    with session_scope() as session:
        if session.get(Tenant, plan["tenant_id"]) is None:
            session.add(Tenant(id=plan["tenant_id"], name="synthetic-directory-tenant"))
            session.flush()
        edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity))
        edge.capabilities = {
            "inventory_schema": "enterprise-installed-capabilities/v2",
            "protocol_version": "connector-protocol.v1",
            "connectors": ["directory"],
            "connector_versions": {"directory": version},
            "data_categories": [],
            "connector_task_types": {"directory": ["scan", "skill_scan"]},
        }
        edge.last_seen_at = now.replace(tzinfo=None)
        session.add(DiscoveryScheduleRecord(
            id=key, tenant_id=plan["tenant_id"], environment_id=env, edge_agent_id=edge.id,
            intent=intent, intent_digest=scheduler.digest(intent), installation_plan=directory_plan,
            installation_plan_digest=scheduler.digest(directory_plan), status="active",
            starts_at=now.replace(tzinfo=None), expires_at=(now + timedelta(days=1)).replace(tzinfo=None),
            interval_seconds=900, max_runs=4,
        ))
        audit(session, plan["tenant_id"], "edge", identity, "scan.schedule.confirm", "discovery_schedule",
              resource_id=key, summary={"intent_digest": scheduler.digest(intent)})
        audit(session, plan["tenant_id"], "user", identity, "install.plan.create", "environment",
              resource_id=env, summary={"plan_id": directory_plan["plan_id"],
                                        "plan_sha256": scheduler.digest(directory_plan)})
        session.flush()
    return dict(tenant_id=plan["tenant_id"], device_identity=identity, schedule_id=key, now=now)


def test_directory_skill_split_replay_and_tamper(confirmed_directory):
    with session_scope() as session:
        ids = scheduler.reserve_discovery_round(session, **confirmed_directory)
        assert len(ids) == 2
        skill_task, scan_task = (session.get(EdgeTask, i) for i in ids)
        assert skill_task.task_type == "skill_scan" and skill_task.payload["inventory_kind"] == "skills"
        assert skill_task.payload["scope"]["include"] == ["SKILL.md"]
        assert scan_task.task_type == "scan" and scan_task.payload["scope"]["include"] == ["config.yaml"]
        assert scheduler.reserve_discovery_round(session, **confirmed_directory) == ids
        before = counts(session)
        skill_task.payload = {**skill_task.payload,
                              "scope": {"roots": ["/home/user/skills"], "include": ["config.yaml"]}}
        session.flush()
        with pytest.raises(ValueError, match="replay_unavailable"):
            scheduler.reserve_discovery_round(session, **confirmed_directory)
        assert counts(session) == before
