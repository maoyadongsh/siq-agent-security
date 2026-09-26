"""Tenant-scoped Edge credential revocation; never changes runtime permissions."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import EdgeAgent, Environment, utcnow
from app.outbox import audit, emit_event
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=["environments"])


class RevokeDevice(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["enterprise-device-revoke/v1"]
    confirm_device_id: str = Field(min_length=1, max_length=64)


class CredentialStatus(BaseModel):
    schema_version: Literal["enterprise-device-credential-status/v1"] = "enterprise-device-credential-status/v1"
    environment_id: str
    device_id: str
    status: Literal["active", "revoked"]
    revoked_at: datetime | None
    runtime_permissions_changed: Literal[False] = False


def locate(session: Session, identity: Identity, environment_id: str, device_id: str) -> EdgeAgent:
    edge = session.scalar(select(EdgeAgent).join(Environment).where(
        Environment.tenant_id == identity.tenant_id,
        Environment.id == environment_id,
        EdgeAgent.id == device_id,
    ))
    if edge is None:
        raise HTTPException(404, "not_found")
    return edge


def project(edge: EdgeAgent, response: Response) -> CredentialStatus:
    response.headers["Cache-Control"] = "no-store"
    return CredentialStatus(
        environment_id=edge.environment_id, device_id=edge.id,
        status="revoked" if edge.revoked_at is not None else "active", revoked_at=edge.revoked_at,
    )


@router.get("/api/v1/environments/{environment_id}/devices/{device_id}/credential-status",
            response_model=CredentialStatus)
def read_status(environment_id: str, device_id: str, response: Response,
                session: Session = Depends(get_session), identity: Identity = Depends(get_identity)):
    edge = locate(session, identity, environment_id, device_id)
    ensure_permission(identity, "env:read")
    return project(edge, response)


@router.post("/api/v1/environments/{environment_id}/devices/{device_id}/revoke",
             response_model=CredentialStatus)
def revoke(environment_id: str, device_id: str, body: RevokeDevice, response: Response, request: Request,
           session: Session = Depends(get_session), identity: Identity = Depends(get_identity)):
    edge = locate(session, identity, environment_id, device_id)
    ensure_permission(identity, "edge:manage")
    if body.confirm_device_id != device_id:
        raise HTTPException(422, "device_confirmation_mismatch")
    try:
        changed = session.execute(update(EdgeAgent).where(
            EdgeAgent.id == edge.id, EdgeAgent.environment_id == environment_id,
            EdgeAgent.revoked_at.is_(None),
        ).values(revoked_at=utcnow())).rowcount
        if changed:
            summary = {"environment_id": environment_id, "device_id": device_id}
            correlation = request.state.request_id
            audit(session, identity.tenant_id, identity.identity_type, identity.actor_id,
                  "edge.device.revoke", "edge_agent", resource_id=device_id, summary=summary,
                  request_id=correlation)
            emit_event(session, identity.tenant_id, "edge.device.revoked.v1", summary,
                       environment_id=environment_id, resource_ref=device_id, request_id=correlation)
        session.commit()
        session.refresh(edge)
    except Exception:
        session.rollback()
        raise HTTPException(503, "device_revocation_unavailable") from None
    return project(edge, response)
