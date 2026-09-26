"""Paginated framework/role source inventory; not a runtime or skill resolver."""
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.framework_source_view import project_framework_sources
from app.models import AgentAsset, EdgeAgent, Environment
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=['inventory'])


@router.get('/api/v1/framework-role-inventory')
def framework_role_inventory(
    response: Response,
    environment_id: str | None = Query(default=None, min_length=1, max_length=64),
    device_id: str | None = Query(default=None, min_length=1, max_length=64),
    cursor: str | None = Query(default=None, pattern=r'^agt_[A-Za-z0-9_-]{1,60}$'),
    limit: int = Query(default=50, ge=1, le=100),
    identity: Identity = Depends(get_identity), session: Session = Depends(get_session),
):
    ensure_permission(identity, 'agent:read')
    ensure_permission(identity, 'env:read')
    query = select(AgentAsset).where(AgentAsset.tenant_id == identity.tenant_id)
    if environment_id is not None or device_id is not None:
        devices = select(EdgeAgent.id).join(Environment, EdgeAgent.environment_id == Environment.id).where(
            Environment.tenant_id == identity.tenant_id)
        if environment_id is not None:
            devices = devices.where(Environment.id == environment_id)
        if device_id is not None:
            devices = devices.where(EdgeAgent.id == device_id)
        query = query.where(AgentAsset.discovery_scope.in_(devices))
    if cursor is not None:
        query = query.where(AgentAsset.id > cursor)
    rows = list(session.scalars(query.order_by(AgentAsset.id).limit(limit + 1)))
    page = rows[:limit]
    sources = project_framework_sources(session, identity.tenant_id, page)
    response.headers['Cache-Control'] = 'no-store'
    version = 'v2' if any(s['schema_version'].endswith('/v2') for s in sources.values()) else 'v1'
    return {'schema_version': f'enterprise-framework-role-inventory/{version}', 'coverage': 'page_of_tenant_assets',
            'items': [{'asset_id': asset.id, 'name': asset.name, 'reported_framework': asset.framework,
                       'asset_status': asset.status, 'framework_source': sources[asset.id]} for asset in page],
            'next_cursor': page[-1].id if len(rows) > limit else None}
