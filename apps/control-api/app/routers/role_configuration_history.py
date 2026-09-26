"""Read saved configuration snapshots without upgrading them to runtime authority."""

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.framework_source import parse_framework_source
from app.models import AgentAsset, EdgeAgent, EdgeTask, Environment, RoleConfigurationObservation
from app.role_skill_roots import parse_role_skill_roots
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=['inventory'])


def configuration_history_query(tenant_id, asset_id):
    return select(RoleConfigurationObservation, EdgeAgent, Environment, EdgeTask).join(
        EdgeAgent, EdgeAgent.id == RoleConfigurationObservation.edge_agent_id,
    ).join(Environment, Environment.id == EdgeAgent.environment_id).join(
        EdgeTask, EdgeTask.id == RoleConfigurationObservation.task_id,
    ).where(RoleConfigurationObservation.tenant_id == tenant_id,
            RoleConfigurationObservation.asset_id == asset_id, Environment.tenant_id == tenant_id,
            EdgeTask.environment_id == Environment.id, EdgeTask.task_type == 'scan')


def project_configuration_snapshot(row, expected_framework=None):
    observation, edge, environment, task = row
    result = {'observation_id': observation.id, 'observed_at': observation.observed_at.isoformat() + 'Z',
              'received_at': observation.received_at.isoformat() + 'Z', 'environment_id': environment.id,
              'device_id': edge.id, 'device_revoked': edge.revoked_at is not None,
              'status': 'snapshot_unavailable', 'configuration': None}
    try:
        source = parse_framework_source(json.dumps(observation.framework_source, ensure_ascii=False))
        roots = parse_role_skill_roots(json.dumps(observation.skill_source_roots, ensure_ascii=False)) \
            if observation.skill_source_roots is not None else None
        version = 'v2' if source['framework'] == 'hermes' else 'v1'
        if (not re.fullmatch(r'[a-f0-9]{64}', observation.batch_digest or '')
                or task.result_digest != observation.batch_digest or not isinstance(task.payload, dict)
                or task.payload.get('connector') != source['framework']
                or (expected_framework is not None and source['framework'] != expected_framework)
                or (roots is not None and roots['schema_version'] != f'enterprise-role-skill-roots/{version}')
                or task.payload.get('target_device_identity') not in (None, edge.device_identity)):
            return result
    except (ValueError, TypeError, RecursionError):
        return result
    result.update(status='recorded_snapshot', configuration={
        'framework_source': source, 'skill_source_roots': roots,
        'task_id': task.id, 'batch_digest': observation.batch_digest,
    })
    return result


@router.get('/api/v1/agents/{asset_id}/configuration-observations')
def configuration_history(
    asset_id: str, response: Response,
    cursor: str | None = Query(default=None, pattern=r'^rco_[A-Za-z0-9_-]{1,60}$'),
    limit: int = Query(default=50, ge=1, le=100),
    identity: Identity = Depends(get_identity), session: Session = Depends(get_session),
):
    asset = session.scalar(select(AgentAsset).where(
        AgentAsset.tenant_id == identity.tenant_id, AgentAsset.id == asset_id))
    if asset is None:
        raise HTTPException(404, 'not_found')
    ensure_permission(identity, 'agent:read')
    ensure_permission(identity, 'env:read')
    query = configuration_history_query(identity.tenant_id, asset_id)
    if cursor is not None:
        anchor = session.execute(query.where(RoleConfigurationObservation.id == cursor)).first()
        if anchor is None:
            raise HTTPException(404, 'not_found')
        query = query.where(or_(
            RoleConfigurationObservation.received_at < anchor[0].received_at,
            and_(RoleConfigurationObservation.received_at == anchor[0].received_at,
                 RoleConfigurationObservation.id < anchor[0].id),
        ))
    rows = session.execute(query.order_by(RoleConfigurationObservation.received_at.desc(),
                                          RoleConfigurationObservation.id.desc()).limit(limit + 1)).all()
    response.headers['Cache-Control'] = 'no-store'
    version = 'v2' if asset.framework == 'hermes' else 'v1'
    return {'schema_version': f'enterprise-role-configuration-history/{version}', 'asset_id': asset_id,
            'coverage': 'recorded_configuration_observations',
            'items': [project_configuration_snapshot(row, asset.framework) for row in rows[:limit]],
            'next_cursor': rows[limit - 1][0].id if len(rows) > limit else None,
            'runtime_status': 'unverified', 'effective_permissions': None}
