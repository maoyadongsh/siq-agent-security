import copy
import uuid

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AgentAsset, AuditEvent, EdgeAgent, EdgeTask, OutboxEvent, RoleConfigurationObservation, utcnow
from app.tests.test_role_configuration_history import config_history as config_history


@pytest.fixture
def history_view(config_history):
    tenant, prepare, upload = config_history
    for index, char in enumerate('bcd'):
        assert upload(prepare(char, roots=index != 1)).status_code == 200
    with session_scope() as session:
        rows = list(session.scalars(select(RoleConfigurationObservation).where(
            RoleConfigurationObservation.tenant_id == tenant['X-Dev-Tenant-Id'])))
        stamp = utcnow()
        for row in rows:
            row.received_at = stamp
        expected = sorted([row.id for row in rows], reverse=True)
        return tenant, rows[0].asset_id, rows[0].edge_agent_id, expected


def test_configuration_history_same_timestamp_pagination_and_old_values(client, history_view):
    tenant, asset_id, edge_id, expected = history_view
    with session_scope() as session:
        session.get(AgentAsset, asset_id).attributes = {'fixture': 'latest-no-longer-has-source'}
        session.get(EdgeAgent, edge_id).revoked_at = utcnow()
        before = {row.id: (copy.deepcopy(row.framework_source), copy.deepcopy(row.skill_source_roots), row.received_at)
                  for row in session.scalars(select(RoleConfigurationObservation).where(
                      RoleConfigurationObservation.asset_id == asset_id))}
        counts = [session.scalar(select(func.count()).select_from(model)) for model in (AuditEvent, OutboxEvent)]
    route = f'/api/v1/agents/{asset_id}/configuration-observations'
    items, cursor = [], None
    for _ in range(3):
        response = client.get(route, headers=tenant, params={'limit': 1, **({'cursor': cursor} if cursor else {})})
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        value = response.json()
        assert value['coverage'] == 'recorded_configuration_observations'
        assert value['runtime_status'] == 'unverified' and value['effective_permissions'] is None
        items.extend(value['items'])
        cursor = value['next_cursor']
    assert cursor is None and [item['observation_id'] for item in items] == expected
    assert all(item['device_revoked'] and item['status'] == 'recorded_snapshot' for item in items)
    assert {item['configuration']['framework_source']['config_sha256'] for item in items} == {c * 64 for c in 'bcd'}
    assert sum(item['configuration']['skill_source_roots'] is None for item in items) == 1
    assert client.get(route, headers=tenant, params={'cursor': expected[-1]}).json()['items'] == []
    with session_scope() as session:
        assert before == {row.id: (row.framework_source, row.skill_source_roots, row.received_at)
                          for row in session.scalars(select(RoleConfigurationObservation).where(
                              RoleConfigurationObservation.asset_id == asset_id))}
        assert counts == [session.scalar(select(func.count()).select_from(model))
                          for model in (AuditEvent, OutboxEvent)]


def test_configuration_history_permissions_and_cursor_scope(client, history_view, tenant_b):
    tenant, asset_id, _, expected = history_view
    route = f'/api/v1/agents/{asset_id}/configuration-observations'
    assert client.get(route, headers=tenant_b).status_code == 404
    assert client.get(route, headers={**tenant, 'X-Dev-Roles': 'viewer'}).status_code == 403
    assert client.get(route, headers=tenant, params={'tenant_id': tenant_b['X-Dev-Tenant-Id']}).json()['items']
    for params in ({'limit': 0}, {'limit': 101}, {'cursor': 'wrong'}):
        assert client.get(route, headers=tenant, params=params).status_code == 422
    assert client.get(route, headers=tenant, params={'cursor': 'rco_missing'}).status_code == 404
    with session_scope() as session:
        other = AgentAsset(tenant_id=tenant['X-Dev-Tenant-Id'], name='different-role')
        session.add(other)
        session.flush()
        other_id = other.id
    assert client.get(f'/api/v1/agents/{other_id}/configuration-observations', headers=tenant,
                      params={'cursor': expected[0]}).status_code == 404


@pytest.mark.parametrize('fault', ['source', 'roots', 'digest', 'connector', 'target'])
def test_configuration_history_invalid_snapshot_has_no_raw_fields(client, history_view, fault):
    tenant, asset_id, _, expected = history_view
    with session_scope() as session:
        row = session.get(RoleConfigurationObservation, expected[0])
        task = session.get(EdgeTask, row.task_id)
        if fault == 'source':
            row.framework_source = {'private': 'synthetic-private-marker'}
        elif fault == 'roots':
            row.skill_source_roots = {'private': 'synthetic-private-marker'}
        elif fault == 'digest':
            task.result_digest = '0' * 64
        elif fault == 'connector':
            task.payload = {**task.payload, 'connector': 'hermes'}
        elif fault == 'target':
            task.payload = {**task.payload, 'target_device_identity': 'other'}
    response = client.get(f'/api/v1/agents/{asset_id}/configuration-observations', headers=tenant)
    assert response.status_code == 200 and 'synthetic-private-marker' not in response.text
    items = response.json()['items']
    assert items[0]['status'] == 'snapshot_unavailable' and items[0]['configuration'] is None
    assert all(item['status'] == 'recorded_snapshot' for item in items[1:])


def test_configuration_history_foreign_environment_hidden(client, history_view, tenant_b):
    tenant, asset_id, edge_id, expected = history_view
    foreign = client.post('/api/v1/environments', headers=tenant_b,
                          json={'name': 'foreign-history-' + uuid.uuid4().hex}).json()['id']
    with session_scope() as session:
        session.get(EdgeAgent, edge_id).environment_id = foreign
    route = f'/api/v1/agents/{asset_id}/configuration-observations'
    response = client.get(route, headers=tenant)
    assert response.status_code == 200 and response.json()['items'] == []
    assert foreign not in response.text and edge_id not in response.text
    assert client.get(route, headers=tenant, params={'cursor': expected[0]}).status_code == 404


def test_legacy_role_has_no_fabricated_configuration_history(client, config_history):
    tenant, prepare, upload = config_history
    assert upload(prepare(legacy=True)).status_code == 200
    with session_scope() as session:
        asset = session.scalar(select(AgentAsset).where(AgentAsset.tenant_id == tenant['X-Dev-Tenant-Id']))
        asset_id = asset.id
    response = client.get(f'/api/v1/agents/{asset_id}/configuration-observations', headers=tenant)
    assert response.status_code == 200
    assert response.json()['items'] == [] and response.json()['next_cursor'] is None


@pytest.mark.parametrize('permissions,expected', [([], 403), (['agent:read'], 403), (['env:read'], 403),
                                               (['agent:read', 'env:read'], 200)])
def test_history_permission_set_not_role_label(client, history_view, monkeypatch, permissions, expected):
    from app.security import Identity, get_identity

    tenant, asset_id, _, _ = history_view
    identity = Identity('user', 'fixture', tenant['X-Dev-Tenant-Id'],
                        roles=frozenset({'admin'}), permissions=frozenset(permissions))
    monkeypatch.setitem(client.app.dependency_overrides, get_identity, lambda: identity)
    assert client.get(f'/api/v1/agents/{asset_id}/configuration-observations').status_code == expected
