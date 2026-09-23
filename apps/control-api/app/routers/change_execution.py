"""Exact, bounded deployment and audit history for one tenant-owned change."""

import re
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AuditEvent, ChangeRequest, Deployment, Environment
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=["policies"])
Digest = str | None


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeploymentHistory(Wire):
    id: str = Field(max_length=64)
    environment_id: str = Field(max_length=64)
    environment_name: str | None = Field(max_length=128)
    binding_id: str | None = Field(max_length=64)
    target: str = Field(max_length=128)
    status: str = Field(max_length=32)
    created_at: datetime
    verification_level: Literal["none", "config_readback", "behavior_enforced", "failed", "stale", "unknown"]
    independent_result: Literal["not_checked", "verified", "mismatch", "unreachable", "no_receipt", "unknown"]
    backend_mutated: bool | None
    error_digest: Digest = Field(pattern=r"^[a-f0-9]{64}$")


class AuditHistory(Wire):
    id: str = Field(max_length=64)
    action: str = Field(max_length=64)
    actor_id: str = Field(max_length=256)
    resource_id: str = Field(max_length=64)
    created_at: datetime
    review_digest: Digest = Field(pattern=r"^[a-f0-9]{64}$")
    error_digest: Digest = Field(pattern=r"^[a-f0-9]{64}$")


class ChangeExecution(Wire):
    schema_version: Literal["change-execution/v1"] = "change-execution/v1"
    change_id: str = Field(max_length=64)
    change_status: str = Field(max_length=32)
    evaluated_at: datetime
    deployments: list[DeploymentHistory] = Field(max_length=100)
    deployments_truncated: bool
    audit_access: Literal["allowed", "denied"]
    audit_events: list[AuditHistory] = Field(max_length=200)
    audit_truncated: bool
    expanded: bool


def _dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _digest(value: object) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) else None


def _utc(value: datetime) -> datetime:
    # DB DateTime columns historically store naive UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _deployment(row: Deployment, names: dict[str, str]) -> DeploymentHistory:
    verification = _dict(row.verification)
    level = verification.get("level", verification.get("verification_level"))
    aliases = {
        "readback_verified": "config_readback",
        "config_readback": "config_readback",
        "enforcement_verified": "behavior_enforced",
        "behavior_verified": "behavior_enforced",
        "failed": "failed",
        "error": "failed",
        "stale": "stale",
        "expired": "stale",
    }
    projected_level = aliases.get(level, "unknown") if isinstance(level, str) and level else "none"
    if verification.get("stale") is True or verification.get("expired") is True:
        projected_level = "stale"
    attestation = _dict(verification.get("independent_attestation"))
    result = attestation.get("result")
    independent = (
        result
        if result in ("verified", "mismatch", "unreachable", "no_receipt")
        else "unknown"
        if attestation
        else "not_checked"
    )
    changed = verification.get("backend_mutated")
    return DeploymentHistory(
        id=row.id,
        environment_id=row.environment_id,
        environment_name=names.get(row.environment_id),
        binding_id=row.runtime_binding_id,
        target=row.target,
        status=row.status,
        created_at=_utc(row.created_at),
        verification_level=projected_level,
        independent_result=independent,
        backend_mutated=changed if isinstance(changed, bool) else None,
        error_digest=_digest(_dict(verification.get("apply_failed")).get("error_digest"))
        or _digest(_dict(row.receipt).get("error_digest")),
    )


@router.get("/api/v1/change-requests/{cr_id}/execution", response_model=ChangeExecution)
def get_execution(
    cr_id: str,
    response: Response,
    expanded: bool = False,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    cr = session.scalar(
        select(ChangeRequest).where(ChangeRequest.id == cr_id, ChangeRequest.tenant_id == identity.tenant_id)
    )
    if cr is None:
        raise HTTPException(404, "not_found")
    ensure_permission(identity, "policy:read")
    dep_limit, audit_limit = (100, 200) if expanded else (20, 50)
    own_deployments = select(Deployment.id).where(
        Deployment.tenant_id == identity.tenant_id, Deployment.change_request_id == cr.id
    )
    rows = list(
        session.scalars(
            select(Deployment)
            .where(Deployment.id.in_(own_deployments))
            .order_by(Deployment.created_at.desc(), Deployment.id)
            .limit(dep_limit + 1)
        )
    )
    names = {}
    if identity.has_permission("env:read") and rows:
        names = dict(
            session.execute(
                select(Environment.id, Environment.name).where(
                    Environment.tenant_id == identity.tenant_id,
                    Environment.id.in_([d.environment_id for d in rows[:dep_limit]]),
                )
            ).all()
        )
    events = []
    can_audit = identity.has_permission("audit:read")
    if can_audit:
        events = list(
            session.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.tenant_id == identity.tenant_id,
                    or_(
                        and_(AuditEvent.resource_type == "change_request", AuditEvent.resource_id == cr.id),
                        and_(AuditEvent.resource_type == "deployment", AuditEvent.resource_id.in_(own_deployments)),
                    ),
                )
                .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
                .limit(audit_limit + 1)
            )
        )
    response.headers["Cache-Control"] = "no-store"
    return ChangeExecution(
        change_id=cr.id,
        change_status=cr.status,
        evaluated_at=datetime.now(UTC),
        expanded=expanded,
        deployments=[_deployment(d, names) for d in rows[:dep_limit]],
        deployments_truncated=len(rows) > dep_limit,
        audit_access="allowed" if can_audit else "denied",
        audit_truncated=len(events) > audit_limit,
        audit_events=[
            AuditHistory(
                id=e.id,
                action=e.action,
                actor_id=e.actor_id,
                resource_id=e.resource_id,
                created_at=_utc(e.created_at),
                review_digest=_digest(_dict(e.summary).get("review_digest")),
                error_digest=_digest(_dict(e.summary).get("error_digest")),
            )
            for e in events[:audit_limit]
        ],
    )
