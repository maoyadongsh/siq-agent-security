"""Signed device confirmation and bounded polling of confirmed discovery plans."""
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.discovery_schedule import DiscoverySchedule
from app.discovery_scheduler import digest, reserve_discovery_round
from app.evidence_signing import verify_hex_signature
from app.install_plan import Digest, EnterpriseInstallPlan, Identifier, StrictWire
from app.models import AuditEvent, DiscoveryScheduleRecord, EdgeAgent, Environment
from app.outbox import audit
from app.routers.discovery_schedules import lock_tenant, projection
from app.security import verify_edge_secret

router = APIRouter(tags=["edge"])


@router.get("/edge/v1/discovery-schedules/{schedule_id}")
def read_schedule_intent(request: Request, response: Response,
                         schedule_id: Annotated[str, Path(pattern=r"^eds-[a-f0-9]{32}$")],
                         session: Session = Depends(get_session)):
    edge = verify_edge_secret(request, request.headers.get("X-Edge-Identity", ""), session)
    authenticated_hash = edge.secret_hash
    env = session.get(Environment, edge.environment_id)
    if env is None:
        raise HTTPException(404, "not_found")
    lock_tenant(session, env.tenant_id)
    edge = session.scalar(select(EdgeAgent).where(EdgeAgent.id == edge.id).with_for_update()
                          .execution_options(populate_existing=True))
    if (edge is None or edge.revoked_at is not None or edge.secret_hash != authenticated_hash
            or edge.environment_id != env.id):
        raise HTTPException(409, "discovery_schedule_device_changed")
    row = session.scalar(select(DiscoveryScheduleRecord).where(
        DiscoveryScheduleRecord.id == schedule_id, DiscoveryScheduleRecord.tenant_id == env.tenant_id,
        DiscoveryScheduleRecord.environment_id == env.id, DiscoveryScheduleRecord.edge_agent_id == edge.id,
    ).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404, "not_found")
    try:
        intent = DiscoverySchedule.model_validate(row.intent)
        intent.require_binding(edge.device_identity, row.installation_plan_digest)
        if (intent.schedule_id != row.id or digest(intent.model_dump()) != row.intent_digest
                or row.starts_at != intent.start.replace(tzinfo=None)
                or row.expires_at != intent.end.replace(tzinfo=None)
                or row.interval_seconds != intent.interval_seconds or row.max_runs != intent.max_runs):
            raise ValueError("inconsistent_projection")
    except ValueError:
        raise HTTPException(409, "discovery_schedule_integrity_failed") from None
    response.headers["Cache-Control"] = "no-store"
    return {"schema_version": "edge-discovery-schedule-intent/v1", "intent": intent.model_dump(),
            "intent_digest": row.intent_digest, "status": row.status, "revision": row.revision}


class ConfirmSchedule(StrictWire):
    schema_version: Literal["edge-discovery-schedule-confirm/v1"]
    schedule_id: Annotated[str, Field(pattern=r"^eds-[a-f0-9]{32}$")]
    device_identity: Identifier
    environment_id: Identifier
    control_plane_origin: str = Field(min_length=1, max_length=2048)
    intent_digest: Digest
    installation_plan_sha256: Digest
    expected_revision: int = Field(ge=0)
    confirmed_at: str
    user_confirmed: bool
    signature: str = Field(pattern=r"^[a-f0-9]{128}$")

    @field_validator("confirmed_at")
    @classmethod
    def timestamp(cls, value):
        return EnterpriseInstallPlan.utc_timestamp(value)

    @field_validator("user_confirmed")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("explicit_confirmation_required")
        return value

    def signed_bytes(self):
        return json.dumps(self.model_dump(exclude={"signature"}), sort_keys=True,
                          separators=(",", ":"), ensure_ascii=True).encode("ascii")


@router.post("/edge/v1/discovery-schedules/confirm")
def confirm_schedule(body: ConfirmSchedule, request: Request, response: Response,
                     session: Session = Depends(get_session)):
    edge = verify_edge_secret(request, request.headers.get("X-Edge-Identity", ""), session)
    authenticated_hash = edge.secret_hash
    env = session.get(Environment, edge.environment_id)
    if env is None:
        raise HTTPException(404, "not_found")
    lock_tenant(session, env.tenant_id)
    edge = session.scalar(select(EdgeAgent).where(EdgeAgent.id == edge.id).with_for_update()
                          .execution_options(populate_existing=True))
    if edge is None or edge.revoked_at is not None or edge.secret_hash != authenticated_hash:
        raise HTTPException(409, "discovery_confirmation_device_changed")
    if (body.device_identity != edge.device_identity or body.environment_id != edge.environment_id
            or not verify_hex_signature(edge.public_key_pem, body.signed_bytes(), body.signature)):
        raise HTTPException(401, "discovery_confirmation_denied")
    row = session.scalar(select(DiscoveryScheduleRecord).where(
        DiscoveryScheduleRecord.id == body.schedule_id, DiscoveryScheduleRecord.tenant_id == env.tenant_id,
        DiscoveryScheduleRecord.environment_id == env.id, DiscoveryScheduleRecord.edge_agent_id == edge.id,
    ).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404, "not_found")
    try:
        intent = DiscoverySchedule.model_validate(row.intent)
        plan = EnterpriseInstallPlan.model_validate(row.installation_plan)
        intent.require_binding(edge.device_identity, digest(plan.model_dump()))
    except ValueError:
        raise HTTPException(409, "discovery_confirmation_integrity_failed") from None
    if (body.intent_digest != row.intent_digest or row.intent_digest != digest(intent.model_dump())
            or body.installation_plan_sha256 != row.installation_plan_digest
            or row.installation_plan_digest != intent.installation_plan_sha256
            or body.control_plane_origin != plan.control_plane_origin or intent.schedule_id != row.id
            or plan.tenant_id != env.tenant_id or plan.environment_id != env.id
            or row.starts_at != intent.start.replace(tzinfo=None)
            or row.expires_at != intent.end.replace(tzinfo=None)
            or row.interval_seconds != intent.interval_seconds or row.max_runs != intent.max_runs):
        raise HTTPException(409, "discovery_confirmation_integrity_failed")
    now = datetime.now(UTC)
    if intent.end <= now:
        raise HTTPException(409, "discovery_confirmation_expired")
    request_digest = hashlib.sha256(body.signed_bytes()).hexdigest()
    previous = session.scalar(select(AuditEvent).where(
        AuditEvent.tenant_id == env.tenant_id, AuditEvent.resource_id == row.id,
        AuditEvent.action == "scan.schedule.confirm", AuditEvent.actor_type == "edge",
        AuditEvent.actor_id == edge.device_identity, AuditEvent.decision == "allow",
        AuditEvent.summary["request_digest"].as_string() == request_digest,
    ).limit(1))
    if previous is not None and row.status == "active":
        return projection(row, response)
    confirmed_at = datetime.fromisoformat(body.confirmed_at)
    if (row.status != "pending_confirmation" or row.revision != body.expected_revision
            or not now - timedelta(minutes=5) <= confirmed_at <= now):
        raise HTTPException(409, "discovery_confirmation_conflict")
    for action, resource, predicates in (
        ("install.plan.create", env.id, (
            AuditEvent.summary["plan_id"].as_string() == plan.plan_id,
            AuditEvent.summary["plan_sha256"].as_string() == row.installation_plan_digest,
        )),
        ("scan.schedule.create", row.id, (AuditEvent.summary["intent_digest"].as_string() == row.intent_digest,)),
    ):
        if session.scalar(select(AuditEvent.id).where(
            AuditEvent.tenant_id == env.tenant_id, AuditEvent.resource_id == resource,
            AuditEvent.action == action, AuditEvent.decision == "allow", *predicates,
        ).limit(1)) is None:
            raise HTTPException(409, "discovery_confirmation_source_unverified")
    row.status = "active"
    row.revision += 1
    audit(session, env.tenant_id, "edge", edge.device_identity, "scan.schedule.confirm", "discovery_schedule",
          resource_id=row.id, summary={"intent_digest": row.intent_digest, "request_digest": request_digest})
    session.commit()
    return projection(row, response)


class TickSchedule(StrictWire):
    schema_version: Literal["edge-discovery-schedule-tick/v1"]
    schedule_id: Annotated[str, Field(pattern=r"^eds-[a-f0-9]{32}$")]
    intent_digest: Digest


@router.post("/edge/v1/discovery-schedules/tick")
def tick_schedule(body: TickSchedule, request: Request, response: Response,
                  session: Session = Depends(get_session)):
    edge = verify_edge_secret(request, request.headers.get("X-Edge-Identity", ""), session)
    authenticated_hash = edge.secret_hash
    env = session.get(Environment, edge.environment_id)
    if env is None:
        raise HTTPException(404, "not_found")
    lock_tenant(session, env.tenant_id)
    edge = session.scalar(select(EdgeAgent).where(EdgeAgent.id == edge.id).with_for_update()
                          .execution_options(populate_existing=True))
    if (edge is None or edge.revoked_at is not None or edge.secret_hash != authenticated_hash
            or edge.environment_id != env.id):
        raise HTTPException(409, "discovery_schedule_device_changed")
    row = session.scalar(select(DiscoveryScheduleRecord).where(
        DiscoveryScheduleRecord.id == body.schedule_id, DiscoveryScheduleRecord.tenant_id == env.tenant_id,
        DiscoveryScheduleRecord.environment_id == env.id, DiscoveryScheduleRecord.edge_agent_id == edge.id,
    ).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(404, "not_found")
    if row.intent_digest != body.intent_digest:
        raise HTTPException(409, "discovery_schedule_integrity_failed")
    try:
        tasks = reserve_discovery_round(session, tenant_id=env.tenant_id,
                                        device_identity=edge.device_identity,
                                        schedule_id=row.id, now=datetime.now(UTC))
    except ValueError:
        raise HTTPException(409, "discovery_schedule_unavailable") from None
    result = {"schema_version": "edge-discovery-schedule-tick-result/v1",
              "schedule_id": row.id, "intent_digest": row.intent_digest,
              "status": row.status, "task_ids": tasks or []}
    session.commit()
    response.headers["Cache-Control"] = "no-store"
    return result
