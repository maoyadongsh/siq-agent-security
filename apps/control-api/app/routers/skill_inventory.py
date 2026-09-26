"""Tenant-scoped historical skill observations, never effective permissions."""

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.db import get_session
from app.models import EdgeAgent, Environment, SkillInstallation, SkillManifestObservation
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=["inventory"])


def inventory_query(tenant_id: str):
    latest = (
        select(
            SkillManifestObservation,
            func.row_number()
            .over(
                partition_by=SkillManifestObservation.installation_id,
                order_by=(SkillManifestObservation.observed_at.desc(), SkillManifestObservation.id.desc()),
            )
            .label("position"),
        )
        .where(SkillManifestObservation.tenant_id == tenant_id)
        .subquery()
    )
    observation = aliased(SkillManifestObservation, latest)
    return (
        select(SkillInstallation, EdgeAgent, Environment, observation)
        .join(EdgeAgent, EdgeAgent.id == SkillInstallation.edge_agent_id)
        .join(Environment, Environment.id == EdgeAgent.environment_id)
        .outerjoin(observation, (observation.installation_id == SkillInstallation.id) & (latest.c.position == 1))
        .where(SkillInstallation.tenant_id == tenant_id, Environment.tenant_id == tenant_id)
    )


def project_observation(observation):
    if observation is None:
        return None
    return {
        "observation_id": observation.id,
        "manifest_sha256": observation.manifest_sha256,
        "parser_version": observation.parser_version,
        "parse_status": observation.parse_status,
        "name": observation.name,
        "allowed_tools_present": observation.allowed_tools_present,
        "declared_tools": observation.declared_tools,
        "observed_at": observation.observed_at.isoformat() + "Z",
        "batch_digest": observation.batch_digest,
    }


def project(row):
    installation, edge, environment, observation = row
    return {
        "installation_id": installation.id,
        "locator_sha256": installation.locator_sha256,
        "environment": {"id": environment.id, "name": environment.name},
        "device": {"id": edge.id, "identity": edge.device_identity, "revoked": edge.revoked_at is not None},
        "presence": "observed_not_verified_current",
        "relationship_status": "unresolved",
        "effective_permissions": None,
        "latest_observation": project_observation(observation),
    }


@router.get("/api/v1/skill-installations")
def list_skill_installations(
    response: Response,
    environment_id: str | None = Query(default=None, max_length=128),
    device_id: str | None = Query(default=None, max_length=128),
    cursor: str | None = Query(default=None, pattern=r"^ski_[A-Za-z0-9_-]{1,60}$"),
    limit: int = Query(default=50, ge=1, le=200),
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
):
    ensure_permission(identity, "agent:read")
    ensure_permission(identity, "env:read")
    query = inventory_query(identity.tenant_id)
    if environment_id is not None:
        query = query.where(Environment.id == environment_id)
    if device_id is not None:
        query = query.where(EdgeAgent.id == device_id)
    if cursor is not None:
        query = query.where(SkillInstallation.id > cursor)
    rows = session.execute(query.order_by(SkillInstallation.id).limit(limit + 1)).all()
    response.headers["Cache-Control"] = "no-store"
    return {
        "schema_version": "enterprise-skill-inventory/v1",
        "items": [project(row) for row in rows[:limit]],
        "next_cursor": rows[limit - 1][0].id if len(rows) > limit else None,
    }


@router.get("/api/v1/skill-installations/{installation_id}")
def skill_installation_detail(
    installation_id: str,
    response: Response,
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
):
    row = session.execute(inventory_query(identity.tenant_id).where(SkillInstallation.id == installation_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    ensure_permission(identity, "agent:read")
    ensure_permission(identity, "env:read")
    response.headers["Cache-Control"] = "no-store"
    return project(row)


@router.get("/api/v1/skill-installations/{installation_id}/observations")
def skill_installation_history(
    installation_id: str,
    response: Response,
    cursor: str | None = Query(default=None, pattern=r"^smo_[A-Za-z0-9_-]{1,60}$"),
    limit: int = Query(default=50, ge=1, le=200),
    identity: Identity = Depends(get_identity),
    session: Session = Depends(get_session),
):
    row = session.execute(inventory_query(identity.tenant_id).where(SkillInstallation.id == installation_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="not_found")
    ensure_permission(identity, "agent:read")
    ensure_permission(identity, "env:read")
    query = select(SkillManifestObservation).where(
        SkillManifestObservation.tenant_id == identity.tenant_id,
        SkillManifestObservation.installation_id == installation_id,
    )
    if cursor is not None:
        anchor = session.scalar(query.where(SkillManifestObservation.id == cursor))
        if anchor is None:
            raise HTTPException(status_code=404, detail="not_found")
        query = query.where(
            or_(
                SkillManifestObservation.observed_at < anchor.observed_at,
                and_(
                    SkillManifestObservation.observed_at == anchor.observed_at, SkillManifestObservation.id < anchor.id
                ),
            )
        )
    rows = session.scalars(
        query.order_by(
            SkillManifestObservation.observed_at.desc(),
            SkillManifestObservation.id.desc(),
        ).limit(limit + 1)
    ).all()
    response.headers["Cache-Control"] = "no-store"
    return {
        "schema_version": "enterprise-skill-history/v1",
        "installation_id": installation_id,
        "items": [project_observation(row) for row in rows[:limit]],
        "next_cursor": rows[limit - 1].id if len(rows) > limit else None,
    }
