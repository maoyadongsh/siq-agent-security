"""Internal confirmed-plan reservation. No HTTP authentication or background loop."""
import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import load_settings
from app.discovery_schedule import DiscoverySchedule, due_slot
from app.edge_capabilities import can_claim_skills, claimable_connectors
from app.install_plan import EnterpriseInstallPlan
from app.models import (
    AuditEvent,
    DiscoveryScheduleRecord,
    DiscoveryScheduleRun,
    EdgeAgent,
    EdgeTask,
    Environment,
    Tenant,
)
from app.outbox import audit, emit_event
from app.signing import sign_task_payload


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _connector_specs(connector) -> list[tuple[str, list[str]]]:
    """Deterministic task split for one connector; no capability or time checks.

    directory SKILL.md becomes a standalone skill_scan; remaining includes scan.
    """
    includes = list(connector.scope.include)
    specs: list[tuple[str, list[str]]] = []
    if connector.id == "directory" and "SKILL.md" in includes:
        specs.append(("skill_scan", ["SKILL.md"]))
        includes.remove("SKILL.md")
    if includes:
        specs.append(("scan", includes))
    return specs


def _task_payload(connector, kind: str, include: list[str], device_identity: str) -> dict:
    payload = {"connector": connector.id,
               "scope": {"roots": connector.scope.roots, "include": include},
               "target_device_identity": device_identity}
    if kind == "skill_scan":
        payload["inventory_kind"] = "skills"
    return payload


def _expected_round_tasks(plan, device_identity: str) -> list[tuple[str, dict]]:
    """Expected (task_type, payload) for a round, derived from the bound plan."""
    return [(kind, _task_payload(connector, kind, include, device_identity))
            for connector in plan.connectors
            for kind, include in _connector_specs(connector)]


def _task_key(task_type: str, payload: dict) -> str:
    return task_type + "\x00" + json.dumps(payload, sort_keys=True, separators=(",", ":"))


def reserve_discovery_round(
    session: Session, *, tenant_id: str, device_identity: str, schedule_id: str, now: datetime,
) -> list[str] | None:
    """Verified caller inputs required; None means not due/backpressured. No commit."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("verification_time_requires_timezone")
    now = now.astimezone(UTC)
    stamp = now.replace(tzinfo=None)
    with session.begin_nested():
        tenant = session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update()
                                .execution_options(populate_existing=True))
        if tenant is None or tenant.status != "active":
            raise ValueError("discovery_schedule_unavailable")
        edge = session.scalar(select(EdgeAgent).join(Environment).where(
            Environment.tenant_id == tenant_id, EdgeAgent.device_identity == device_identity,
        ).with_for_update(of=EdgeAgent).execution_options(populate_existing=True))
        row = session.scalar(select(DiscoveryScheduleRecord).where(
            DiscoveryScheduleRecord.tenant_id == tenant_id, DiscoveryScheduleRecord.id == schedule_id,
        ).with_for_update().execution_options(populate_existing=True))
        if (edge is None or edge.revoked_at is not None or row is None
                or row.edge_agent_id != edge.id or row.environment_id != edge.environment_id):
            raise ValueError("discovery_schedule_unavailable")
        intent = DiscoverySchedule.model_validate(row.intent)
        plan = EnterpriseInstallPlan.model_validate(row.installation_plan)
        intent.require_binding(device_identity, digest(plan.model_dump()))
        if (row.id != intent.schedule_id or row.intent_digest != digest(intent.model_dump())
                or row.installation_plan_digest != intent.installation_plan_sha256
                or plan.tenant_id != tenant_id or plan.environment_id != edge.environment_id
                or row.starts_at != intent.start.replace(tzinfo=None)
                or row.expires_at != intent.end.replace(tzinfo=None)
                or row.max_runs != intent.max_runs or row.interval_seconds != intent.interval_seconds):
            raise ValueError("discovery_schedule_integrity_failed")
        if row.status != "active" or not intent.start <= now < intent.end:
            return None
        for action, resource, predicates in (
            ("install.plan.create", row.environment_id, (
                AuditEvent.summary["plan_id"].as_string() == plan.plan_id,
                AuditEvent.summary["plan_sha256"].as_string() == row.installation_plan_digest,
            )),
            ("scan.schedule.confirm", row.id, (
                AuditEvent.actor_type == "edge", AuditEvent.actor_id == device_identity,
                AuditEvent.summary["intent_digest"].as_string() == row.intent_digest,
            )),
        ):
            if session.scalar(select(AuditEvent.id).where(
                AuditEvent.tenant_id == tenant_id, AuditEvent.action == action,
                AuditEvent.resource_id == resource, AuditEvent.decision == "allow", *predicates,
            ).limit(1)) is None:
                raise ValueError("discovery_schedule_confirmation_missing")
        slot = (now - intent.start) // timedelta(seconds=intent.interval_seconds)
        previous = session.get(DiscoveryScheduleRun, (row.id, slot))
        if previous is not None:
            # Same-slot retry must return the original tasks only if their scope still
            # matches the bound plan; a tampered type/payload is a fixed failure.
            task_ids = previous.task_ids
            if (previous.tenant_id != tenant_id or not isinstance(task_ids, list)
                    or not task_ids or any(not isinstance(task_id, str) for task_id in task_ids)
                    or len(set(task_ids)) != len(task_ids)):
                raise ValueError("discovery_schedule_replay_unavailable")
            tasks = session.scalars(select(EdgeTask).where(EdgeTask.id.in_(task_ids))).all()
            if (len(tasks) != len(task_ids)
                    or any(t.environment_id != row.environment_id for t in tasks)):
                raise ValueError("discovery_schedule_replay_unavailable")
            observed = [_task_key(t.task_type, t.payload) for t in tasks]
            expected = [_task_key(kind, payload)
                        for kind, payload in _expected_round_tasks(plan, device_identity)]
            if sorted(observed) != sorted(expected):
                raise ValueError("discovery_schedule_replay_unavailable")
            return list(task_ids)
        slot = due_slot(intent, now=now, last_reserved_slot=row.last_reserved_slot,
                        reserved_runs=row.reserved_runs, active=True)
        if slot is None:
            return None
        settings = load_settings()
        cutoff = stamp - timedelta(seconds=settings.heartbeat_stale_seconds)
        available = claimable_connectors(edge.capabilities, edge.last_seen_at, stamp, cutoff) or []
        specs = []
        for connector in plan.connectors:
            if edge.capabilities.get("connector_versions", {}).get(connector.id) != connector.version:
                raise ValueError("discovery_schedule_capabilities_unverified")
            for kind, include in _connector_specs(connector):
                if kind == "skill_scan":
                    if (len(connector.scope.roots) > 16 or any("*" in r for r in connector.scope.roots)
                            or not can_claim_skills(edge.capabilities, edge.last_seen_at, stamp, cutoff)):
                        raise ValueError("discovery_schedule_skills_unverified")
                elif connector.id not in available:
                    raise ValueError("discovery_schedule_capabilities_unverified")
                specs.append((connector, kind, include))
        if session.scalar(select(EdgeTask.id).where(
            EdgeTask.environment_id == row.environment_id,
            EdgeTask.task_type.in_(("scan", "skill_scan")),
            EdgeTask.payload["target_device_identity"].as_string() == device_identity,
            EdgeTask.status.not_in(("delivered", "failed", "expired")),
        ).limit(1)):
            return None
        pending = session.scalar(select(func.count(EdgeTask.id)).join(Environment).where(
            Environment.tenant_id == tenant_id, EdgeTask.task_type.in_(("scan", "skill_scan")),
            EdgeTask.status.not_in(("delivered", "failed", "expired")),
        ))
        if pending + len(specs) > settings.scan_quota_per_tenant:
            return None
        expires = min(row.expires_at, stamp + timedelta(seconds=settings.edge_task_ttl_seconds))
        task_ids = []
        for connector, kind, include in specs:
            payload = _task_payload(connector, kind, include, device_identity)
            task = EdgeTask(environment_id=row.environment_id, task_type=kind, payload=payload, expires_at=expires)
            session.add(task)
            session.flush()
            task.signature = sign_task_payload(task.id, kind, row.environment_id, payload, expires.isoformat())
            task_ids.append(task.id)
            emit_event(session, tenant_id, "skill.scan.created.v1" if kind == "skill_scan" else "scan.created.v1",
                       {"task_id": task.id, "environment_id": row.environment_id})
        session.add(DiscoveryScheduleRun(schedule_id=row.id, slot=slot, tenant_id=tenant_id, task_ids=task_ids))
        row.reserved_runs += 1
        row.last_reserved_slot = slot
        row.revision += 1
        audit(session, tenant_id, "edge", device_identity, "scan.schedule.reserve", "discovery_schedule",
              resource_id=row.id,
              summary={"slot": slot, "task_count": len(task_ids), "intent_digest": row.intent_digest})
        session.flush()
        return task_ids
