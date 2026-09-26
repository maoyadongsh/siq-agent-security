"""Read-only origin projection; never infer a framework/skill relationship."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.discovery_identity import asset_evidence_device_filter
from app.framework_source_view import project_framework_sources
from app.models import AgentAsset, EdgeAgent, Environment, Evidence, RoleSkillSelectionObservation
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=["inventory"])


@router.get("/api/v1/agents/{asset_id}/framework-source")
def framework_source(
    asset_id: str,
    response: Response,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    asset = session.scalar(select(AgentAsset).where(
        AgentAsset.id == asset_id, AgentAsset.tenant_id == identity.tenant_id,
    ))
    if asset is None:
        raise HTTPException(404, "not_found")
    ensure_permission(identity, "agent:read")
    ensure_permission(identity, "env:read")
    response.headers["Cache-Control"] = "no-store"
    return project_framework_sources(session, identity.tenant_id, [asset])[asset.id]


@router.get("/api/v1/agents/{asset_id}/skill-selections")
def skill_selections(
    asset_id: str,
    response: Response,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    asset = session.scalar(select(AgentAsset).where(
        AgentAsset.id == asset_id, AgentAsset.tenant_id == identity.tenant_id,
    ))
    if asset is None:
        raise HTTPException(status_code=404, detail="not_found")
    ensure_permission(identity, "agent:read")
    ensure_permission(identity, "env:read")
    rows = session.execute(
        select(RoleSkillSelectionObservation, EdgeAgent)
        .join(EdgeAgent, RoleSkillSelectionObservation.edge_agent_id == EdgeAgent.id)
        .join(Environment, EdgeAgent.environment_id == Environment.id)
        .where(
            RoleSkillSelectionObservation.tenant_id == identity.tenant_id,
            RoleSkillSelectionObservation.asset_id == asset.id,
            RoleSkillSelectionObservation.edge_agent_id == asset.discovery_scope,
            Environment.tenant_id == identity.tenant_id,
        )
        .order_by(RoleSkillSelectionObservation.received_at.desc(), RoleSkillSelectionObservation.id.desc())
        .limit(101)
    ).all()
    response.headers["Cache-Control"] = "no-store"
    return {
        "schema_version": "enterprise-role-skill-observations/v1",
        "asset_id": asset.id,
        "status": "historical_declarations" if rows else "no_recorded_declaration",
        "relationship_status": "unresolved",
        "effective_permissions": None,
        "observations_truncated": len(rows) > 100,
        "observations": [{
            "id": row.id,
            "device": {"id": edge.id, "revoked": edge.revoked_at is not None},
            "task_id": row.task_id,
            "batch_digest": row.batch_digest,
            "selection": row.selection,
            "source_evidence": row.source_evidence,
            "observed_at": row.observed_at.isoformat() + "Z",
            "received_at": row.received_at.isoformat() + "Z",
        } for row, edge in rows[:100]],
    }


@router.get("/api/v1/agents/{asset_id}/discovery-origin")
def discovery_origin(
    asset_id: str,
    response: Response,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    asset = session.scalar(
        select(AgentAsset).where(AgentAsset.id == asset_id, AgentAsset.tenant_id == identity.tenant_id)
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="not_found")
    ensure_permission(identity, "agent:read")
    ensure_permission(identity, "env:read")
    response.headers["Cache-Control"] = "no-store"
    result = {
        "schema_version": "enterprise-discovery-origin/v1",
        "asset_id": asset.id,
        "status": "legacy_unresolved" if asset.discovery_scope == "legacy" else "source_unavailable",
        "environment": None,
        "device": None,
        "reported_framework": asset.framework,
        "assigned_role": asset.role,
        "observations": [],
        "observations_truncated": False,
    }
    if asset.discovery_scope == "legacy":
        return result
    source = session.execute(
        select(EdgeAgent, Environment)
        .join(Environment, EdgeAgent.environment_id == Environment.id)
        .where(EdgeAgent.id == asset.discovery_scope, Environment.tenant_id == identity.tenant_id)
    ).first()
    if source is None:
        return result
    edge, environment = source
    result["status"] = "device_bound"
    result["environment"] = {"id": environment.id, "name": environment.name}
    result["device"] = {"id": edge.id, "identity": edge.device_identity, "revoked": edge.revoked_at is not None}
    observations = list(
        session.scalars(
            select(Evidence)
            .where(
                Evidence.tenant_id == identity.tenant_id,
                Evidence.evidence_id.in_(asset.evidence_ids or []) | (Evidence.subject_ref == asset.id),
                asset_evidence_device_filter(asset),
            )
            .order_by(Evidence.observed_at.desc(), Evidence.id)
            .limit(201)
        )
    )
    result["observations_truncated"] = len(observations) > 200
    result["observations"] = [
        {
            "observation_id": row.id,
            "evidence_id": row.evidence_id,
            "content_hash": row.content_hash,
            "observed_at": row.observed_at.isoformat() + "Z",
        }
        for row in observations[:200]
    ]
    return result
