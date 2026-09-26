import copy
import json

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import (
    AgentAsset,
    AuditEvent,
    EdgeAgent,
    EdgeTask,
    OutboxEvent,
    PermissionFact,
    RoleConfigurationObservation,
    utcnow,
)
from app.tests.test_role_skill_sources_view import role_source_case as role_source_case
from app.tests.test_skill_upload import upload_case as upload_case


@pytest.fixture
def saved_configuration(role_source_case, tenant_a):
    asset_id, edge_id, skill_task_id = role_source_case
    with session_scope() as session:
        asset = session.get(AgentAsset, asset_id)
        source = json.loads(asset.attributes['framework_source'])
        roots = json.loads(asset.attributes['skill_source_roots'])
        task = EdgeTask(environment_id=session.get(EdgeAgent, edge_id).environment_id, task_type='scan',
                        payload={'connector': asset.framework}, status='uploaded', result_digest='9' * 64,
                        expires_at=utcnow())
        session.add(task)
        session.flush()
        snapshot = RoleConfigurationObservation(tenant_id=tenant_a['X-Dev-Tenant-Id'], asset_id=asset_id,
                                                edge_agent_id=edge_id, task_id=task.id, batch_digest=task.result_digest,
                                                framework_source=source, skill_source_roots=roots, observed_at=utcnow())
        session.add(snapshot)
        session.flush()
        return asset_id, snapshot.id, edge_id, skill_task_id


@pytest.mark.parametrize('role_source_case', ['openclaw', 'hermes'], indirect=True)
def test_snapshot_comparison_does_not_substitute_latest_attributes(client, tenant_a, saved_configuration):
    asset_id, snapshot_id, edge_id, _ = saved_configuration
    with session_scope() as session:
        asset = session.get(AgentAsset, asset_id)
        hermes = asset.framework == 'hermes'
        asset.attributes = {'unrelated_latest': True}
        session.get(EdgeAgent, edge_id).revoked_at = utcnow()
        before = [session.scalar(select(func.count()).select_from(model))
                  for model in (AuditEvent, OutboxEvent, PermissionFact, RoleConfigurationObservation)]
        old_roots = copy.deepcopy(session.get(RoleConfigurationObservation, snapshot_id).skill_source_roots)
    route = f'/api/v1/agents/{asset_id}/configuration-observations/{snapshot_id}/skill-installation-sources'
    cursor, items = None, []
    for _ in range(3):
        response = client.get(route, headers=tenant_a, params={'limit': 1, **({'cursor': cursor} if cursor else {})})
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        value = response.json()
        assert value['schema_version'] == f'enterprise-role-skill-snapshot-comparison/{"v2" if hermes else "v1"}'
        assert value['status'] == 'historical_comparison'
        assert value['comparison_basis'] == 'latest_skill_observations_against_saved_configuration'
        assert value['configuration_observation']['observation_id'] == snapshot_id
        assert value['configuration_observation']['device_revoked']
        assert value['effective_permissions'] is None and value['runtime_status'] == 'unverified'
        items.extend(value['items'])
        cursor = value['next_cursor']
    assert cursor is None and len({item['installation_id'] for item in items}) == 3
    assert sum(item['relationship_status'] == 'historical_source_match' for item in items) == (1 if hermes else 2)
    history = client.get(f'/api/v1/agents/{asset_id}/configuration-observations', headers=tenant_a).json()
    assert history['schema_version'] == f'enterprise-role-configuration-history/{"v2" if hermes else "v1"}'
    assert history['items'][0]['configuration']['skill_source_roots'] == old_roots
    with session_scope() as session:
        assert old_roots == session.get(RoleConfigurationObservation, snapshot_id).skill_source_roots
        assert before == [session.scalar(select(func.count()).select_from(model))
                          for model in (AuditEvent, OutboxEvent, PermissionFact, RoleConfigurationObservation)]


@pytest.mark.parametrize('fault', ['null', 'unresolved', 'invalid', 'task-digest', 'skill-receipt'])
@pytest.mark.parametrize('role_source_case', ['openclaw', 'hermes'], indirect=True)
def test_snapshot_comparison_unavailable_never_falls_back(client, tenant_a, saved_configuration, fault):
    asset_id, snapshot_id, _, skill_task_id = saved_configuration
    with session_scope() as session:
        snapshot = session.get(RoleConfigurationObservation, snapshot_id)
        if fault == 'null':
            snapshot.skill_source_roots = None
        elif fault == 'unresolved':
            snapshot.skill_source_roots = {'schema_version': 'enterprise-role-skill-roots/v1',
                                           'basis': 'none', 'status': 'unresolved', 'roots': []}
        elif fault == 'invalid':
            snapshot.framework_source = {'private': 'fixture-do-not-show'}
        elif fault == 'task-digest':
            session.get(EdgeTask, snapshot.task_id).result_digest = '0' * 64
        else:
            session.get(EdgeTask, skill_task_id).result_digest = '0' * 64
    route = f'/api/v1/agents/{asset_id}/configuration-observations/{snapshot_id}/skill-installation-sources'
    response = client.get(route, headers=tenant_a)
    assert response.status_code == 200 and 'fixture-do-not-show' not in response.text
    value = response.json()
    if fault == 'skill-receipt':
        assert len(value['items']) == 3
        assert all(item['relationship_status'] == 'unresolved' for item in value['items'])
    else:
        assert value['status'] == 'snapshot_unavailable' and value['items'] == [] and value['next_cursor'] is None


@pytest.mark.parametrize('role_source_case', ['openclaw', 'hermes'], indirect=True)
def test_snapshot_comparison_object_scope_and_permissions(client, tenant_a, tenant_b, saved_configuration):
    asset_id, snapshot_id, _, _ = saved_configuration
    route = f'/api/v1/agents/{asset_id}/configuration-observations/{snapshot_id}/skill-installation-sources'
    assert client.get(route, headers=tenant_b).status_code == 404
    assert client.get(route, headers={**tenant_a, 'X-Dev-Roles': 'viewer'}).status_code == 403
    with session_scope() as session:
        other = AgentAsset(tenant_id=tenant_a['X-Dev-Tenant-Id'], name='other')
        session.add(other)
        session.flush()
        other_id = other.id
    wrong = f'/api/v1/agents/{other_id}/configuration-observations/{snapshot_id}/skill-installation-sources'
    assert client.get(wrong, headers=tenant_a).status_code == 404
    assert client.get(route.replace(snapshot_id, 'rco_missing'), headers=tenant_a).status_code == 404
    for params in ({'limit': 0}, {'limit': 101}, {'cursor': 'bad'}):
        assert client.get(route, headers=tenant_a, params=params).status_code == 422
