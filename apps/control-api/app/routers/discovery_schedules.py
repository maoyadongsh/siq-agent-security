"""Manage pending discovery intent; never auto-confirm or dispatch scans."""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.discovery_schedule import DiscoverySchedule
from app.discovery_scheduler import digest
from app.install_plan import EnterpriseInstallPlan, StrictWire
from app.models import AuditEvent, DiscoveryScheduleRecord, EdgeAgent, Tenant
from app.outbox import audit
from app.routers.environments import _env_or_404
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=["environments"])


class CreateSchedule(StrictWire):
    intent: DiscoverySchedule
    installation_plan: EnterpriseInstallPlan


class RevokeSchedule(StrictWire):
    expected_revision: int = Field(ge=0)


def projection(row, response):
    response.headers["Cache-Control"] = "no-store"
    return {"schema_version": "enterprise-discovery-schedule-state/v1", "schedule_id": row.id,
            "status": row.status, "revision": row.revision, "intent_digest": row.intent_digest}


def lock_tenant(session, tenant_id):
    tenant = session.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update()
                            .execution_options(populate_existing=True))
    if tenant is None or tenant.status != "active":
        raise HTTPException(409, "discovery_tenant_unavailable")


def _utc_z(value: datetime) -> str:
    """Naive-UTC stored column to UTC Z wire format; no clock or status rewriting."""
    return value.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def management_item(row):
    """Whitelist projection only; never serialize intent, plan, digests or tenant fields."""
    return {"schedule_id": row.id, "edge_agent_id": row.edge_agent_id, "status": row.status,
            "revision": row.revision, "starts_at": _utc_z(row.starts_at), "expires_at": _utc_z(row.expires_at),
            "interval_seconds": row.interval_seconds, "max_runs": row.max_runs, "reserved_runs": row.reserved_runs,
            "last_reserved_slot": row.last_reserved_slot, "created_at": _utc_z(row.created_at)}


@router.get("/api/v1/environments/{environment_id}/discovery-schedules")
def list_schedules(
    environment_id: str, response: Response,
    cursor: str | None = Query(default=None, pattern=r"^eds-[a-f0-9]{32}$"),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session), identity: Identity = Depends(get_identity),
):
    """Read-only paginated projection; no locks, audit, tasks, outbox or reserve/tick calls."""
    env = _env_or_404(session, identity.tenant_id, environment_id)
    ensure_permission(identity, "env:read")
    query = select(DiscoveryScheduleRecord).where(
        DiscoveryScheduleRecord.tenant_id == identity.tenant_id,
        DiscoveryScheduleRecord.environment_id == env.id,
    )
    if cursor is not None:
        query = query.where(DiscoveryScheduleRecord.id > cursor)
    rows = list(session.scalars(query.order_by(DiscoveryScheduleRecord.id).limit(limit + 1)))
    page = rows[:limit]
    response.headers["Cache-Control"] = "no-store"
    return {"schema_version": "enterprise-discovery-schedule-management/v1", "environment_id": env.id,
            "evaluated_at": _utc_z(datetime.now(UTC)),
            "can_revoke": identity.has_permission("env:manage") and identity.has_permission("edge:manage"),
            "items": [management_item(row) for row in page],
            "next_cursor": page[-1].id if len(rows) > limit else None}


@router.post("/api/v1/environments/{environment_id}/discovery-schedules")
def create_schedule(
    environment_id: str, body: CreateSchedule, response: Response,
    session: Session = Depends(get_session), identity: Identity = Depends(get_identity),
):
    env = _env_or_404(session, identity.tenant_id, environment_id)
    edge = session.scalar(select(EdgeAgent).where(
        EdgeAgent.environment_id == env.id, EdgeAgent.device_identity == body.intent.device_identity,
    ))
    if edge is None:
        raise HTTPException(404, "not_found")
    ensure_permission(identity, "env:manage")
    ensure_permission(identity, "edge:manage")
    lock_tenant(session, identity.tenant_id)
    edge = session.scalar(select(EdgeAgent).where(EdgeAgent.id == edge.id).with_for_update()
                          .execution_options(populate_existing=True))
    plan, intent = body.installation_plan, body.intent
    plan_digest, intent_digest = digest(plan.model_dump()), digest(intent.model_dump())
    if (edge.revoked_at is not None or plan.tenant_id != identity.tenant_id or plan.environment_id != env.id
            or intent.installation_plan_sha256 != plan_digest or intent.end <= datetime.now(UTC)):
        raise HTTPException(409, "discovery_schedule_invalid_binding")
    issued = session.scalar(select(AuditEvent.id).where(
        AuditEvent.tenant_id == identity.tenant_id, AuditEvent.resource_id == env.id,
        AuditEvent.action == "install.plan.create", AuditEvent.decision == "allow",
        AuditEvent.summary["plan_id"].as_string() == plan.plan_id,
        AuditEvent.summary["plan_sha256"].as_string() == plan_digest,
    ).limit(1))
    if issued is None:
        raise HTTPException(409, "discovery_install_plan_unverified")
    row = session.get(DiscoveryScheduleRecord, intent.schedule_id)
    if row is not None:
        if row.tenant_id != identity.tenant_id or row.environment_id != env.id or row.edge_agent_id != edge.id:
            raise HTTPException(404, "not_found")
        if row.intent_digest != intent_digest or row.installation_plan_digest != plan_digest:
            raise HTTPException(409, "discovery_schedule_conflict")
        return projection(row, response)
    row = DiscoveryScheduleRecord(
        id=intent.schedule_id, tenant_id=identity.tenant_id, environment_id=env.id, edge_agent_id=edge.id,
        intent=intent.model_dump(), intent_digest=intent_digest, installation_plan=plan.model_dump(),
        installation_plan_digest=plan_digest, starts_at=intent.start.replace(tzinfo=None),
        expires_at=intent.end.replace(tzinfo=None), interval_seconds=intent.interval_seconds, max_runs=intent.max_runs,
    )
    session.add(row)
    audit(session, identity.tenant_id, identity.identity_type, identity.actor_id, "scan.schedule.create",
          "discovery_schedule", resource_id=row.id, summary={"intent_digest": intent_digest})
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "discovery_schedule_retry_same_intent") from None
    return projection(row, response)


@router.post("/api/v1/environments/{environment_id}/discovery-schedules/{schedule_id}/revoke")
def revoke_schedule(
    environment_id: str, schedule_id: str, body: RevokeSchedule, response: Response,
    session: Session = Depends(get_session), identity: Identity = Depends(get_identity),
):
    _env_or_404(session, identity.tenant_id, environment_id)
    row = session.scalar(select(DiscoveryScheduleRecord).where(
        DiscoveryScheduleRecord.id == schedule_id, DiscoveryScheduleRecord.tenant_id == identity.tenant_id,
        DiscoveryScheduleRecord.environment_id == environment_id,
    ))
    if row is None:
        raise HTTPException(404, "not_found")
    ensure_permission(identity, "env:manage")
    ensure_permission(identity, "edge:manage")
    lock_tenant(session, identity.tenant_id)
    session.scalar(select(EdgeAgent).where(EdgeAgent.id == row.edge_agent_id).with_for_update())
    row = session.scalar(select(DiscoveryScheduleRecord).where(DiscoveryScheduleRecord.id == row.id)
                         .with_for_update().execution_options(populate_existing=True))
    if row.status == "revoked":
        return projection(row, response)
    if row.revision != body.expected_revision:
        raise HTTPException(409, "discovery_schedule_revision_conflict")
    row.status = "revoked"
    row.revision += 1
    audit(session, identity.tenant_id, identity.identity_type, identity.actor_id, "scan.schedule.revoke",
          "discovery_schedule", resource_id=row.id, summary={"revision": row.revision})
    session.commit()
    return projection(row, response)
