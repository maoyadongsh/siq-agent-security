import json
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import session_scope
from app.models import AgentAsset, AuditEvent, EdgeAgent, Evidence, OutboxEvent, utcnow
from app.tests.edge_helpers import register_edge


@pytest.mark.parametrize('fault', ['none', 'profile-key', 'config-locator', 'evidence-type'])
def test_hermes_projection_and_inventory_pair(client, tenant_a, tenant_b, source_view, fault):
    asset_id, evidence_id, _ = source_view
    with session_scope() as session:
        asset = session.get(AgentAsset, asset_id)
        evidence = session.get(Evidence, evidence_id)
        source = json.loads(asset.attributes['framework_source'])
        source.update(schema_version='enterprise-framework-source/v2', framework='hermes', instance_key='c' * 64)
        if fault == 'profile-key':
            source['instance_key'] = 'a' * 64
        asset.framework, asset.source_type = 'hermes', 'hermes_profile'
        asset.source_locator = 'hermes://profiles/v2/' + 'c' * 64
        asset.attributes = {'framework_source': json.dumps(source)}
        evidence.source_type = 'manifest' if fault != 'evidence-type' else 'openclaw_config'
        evidence.source_locator = 'c' * 64 + ('/SOUL.md' if fault == 'config-locator' else '/config.yaml')
        evidence.subject_ref = 'hermes:v2:' + 'c' * 64
    path = f'/api/v1/agents/{asset_id}/framework-source'
    response = client.get(path, headers=tenant_a)
    assert response.status_code == 200
    value = response.json()
    assert value['schema_version'] == 'enterprise-framework-source-view/v2'
    assert value['status'] == ('historical_reported_source' if fault == 'none' else 'source_unavailable')
    assert value['effective_permissions'] is None and value['runtime_status'] == 'unverified'
    assert (value['source'] is not None) == (fault == 'none')
    assert client.get(path, headers=tenant_b).status_code == 404
    page = client.get('/api/v1/framework-role-inventory', headers=tenant_a,
                      params={'device_id': source_view[2]}).json()
    assert page['schema_version'] == 'enterprise-framework-role-inventory/v2'
    assert next(item for item in page['items'] if item['asset_id'] == asset_id)['framework_source'] == value


@pytest.fixture
def source_view(client, tenant_a):
    identity = 'source-view-' + uuid.uuid4().hex
    env = client.post('/api/v1/environments', headers=tenant_a, json={'name': identity}).json()['id']
    register_edge(client, tenant_a, env, identity)
    with session_scope() as session:
        edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity))
        source = {'schema_version': 'enterprise-framework-source/v1', 'framework': 'openclaw',
                  'instance_key': 'a' * 64, 'config_sha256': 'b' * 64, 'evidence_id': 'source-fixture'}
        asset = AgentAsset(tenant_id=tenant_a['X-Dev-Tenant-Id'], name='fixture', framework='openclaw',
                           source_type='openclaw_agent', source_locator='openclaw://agents/v2/' + 'c' * 64,
                           discovery_scope=edge.id, evidence_ids=['source-fixture'],
                           attributes={'framework_source': json.dumps(source)})
        evidence = Evidence(tenant_id=asset.tenant_id, environment_id=env, collector_id=identity,
                            evidence_id='source-fixture', source_type='openclaw_config',
                            source_locator='private-fixture-path', subject_ref='openclaw:v2:' + 'c' * 64,
                            content_hash='b' * 64, observed_at=utcnow(), connector_version='test',
                            signature='private-fixture-signature')
        session.add_all([asset, evidence])
        session.flush()
        return asset.id, evidence.id, edge.id


@pytest.mark.parametrize('fault', ['missing-ref', 'hash', 'subject', 'collector', 'environment',
                                  'evidence-tenant', 'device', 'malformed', 'duplicate', 'legacy'])
def test_framework_source_unavailable_is_not_guessed(client, tenant_a, tenant_b, source_view, fault):
    asset_id, evidence_id, _ = source_view
    with session_scope() as session:
        asset = session.get(AgentAsset, asset_id)
        evidence = session.get(Evidence, evidence_id)
        if fault == 'missing-ref':
            asset.evidence_ids = []
        elif fault == 'hash':
            evidence.content_hash = 'd' * 64
        elif fault == 'subject':
            evidence.subject_ref = 'other-role'
        elif fault == 'collector':
            evidence.collector_id = 'other-device'
        elif fault == 'environment':
            evidence.environment_id = None
        elif fault == 'evidence-tenant':
            evidence.tenant_id = tenant_b['X-Dev-Tenant-Id']
        elif fault == 'device':
            asset.discovery_scope = 'missing-device'
        elif fault == 'malformed':
            asset.attributes = {'framework_source': 'private-fixture-malformed'}
        elif fault == 'legacy':
            asset.attributes = {}
        elif fault == 'duplicate':
            values = {column.name: getattr(evidence, column.name) for column in Evidence.__table__.columns
                      if column.name != 'id'}
            # The database rejects ambiguity before a read can encounter it.
            with pytest.raises(IntegrityError), session.begin_nested():
                session.add(Evidence(**values))
                session.flush()
    response = client.get(f'/api/v1/agents/{asset_id}/framework-source', headers=tenant_a)
    assert response.status_code == 200
    expected = {'legacy': 'no_recorded_source', 'duplicate': 'historical_reported_source'}.get(
        fault, 'source_unavailable')
    assert response.json()['status'] == expected
    if fault == 'duplicate':
        assert response.json()['source']['observation_id'] == evidence_id
    else:
        assert response.json()['source'] is None
    assert 'private-fixture' not in response.text


def test_framework_source_access_revocation_and_read_only(client, tenant_a, tenant_b, source_view):
    asset_id, _, edge_id = source_view
    with session_scope() as session:
        session.get(EdgeAgent, edge_id).revoked_at = utcnow()
        before = [session.scalar(select(func.count()).select_from(model))
                  for model in (AuditEvent, OutboxEvent, AgentAsset, Evidence)]
    route = f'/api/v1/agents/{asset_id}/framework-source'
    assert client.get(route, headers=tenant_b).status_code == 404
    assert client.get(route, headers={**tenant_a, 'X-Dev-Roles': 'viewer'}).status_code == 403
    response = client.get(route, headers=tenant_a, params={'tenant_id': 'foreign', 'device_id': 'foreign'})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    source = response.json()['source']
    assert source['device_revoked'] is True and source['device_id'] == edge_id
    assert response.json()['runtime_status'] == 'unverified'
    assert 'private-fixture' not in response.text
    with session_scope() as session:
        after = [session.scalar(select(func.count()).select_from(model))
                 for model in (AuditEvent, OutboxEvent, AgentAsset, Evidence)]
        assert before == after
        assert session.get(AgentAsset, asset_id).status == 'candidate'


def test_framework_source_corrupt_foreign_device_is_hidden(client, tenant_a, tenant_b, source_view):
    asset_id, _, _ = source_view
    identity = 'foreign-source-' + uuid.uuid4().hex
    environment = client.post('/api/v1/environments', headers=tenant_b, json={'name': identity}).json()['id']
    register_edge(client, tenant_b, environment, identity)
    with session_scope() as session:
        foreign = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity))
        foreign_id = foreign.id
        session.get(AgentAsset, asset_id).discovery_scope = foreign_id
    response = client.get(f'/api/v1/agents/{asset_id}/framework-source', headers=tenant_a)
    assert response.status_code == 200 and response.json()['status'] == 'source_unavailable'
    assert response.json()['source'] is None
    assert all(value not in response.text for value in (identity, environment, foreign_id))


def test_framework_inventory_pagination_scope_and_detail_parity(client, tenant_a, tenant_b, source_view):
    asset_id, _, edge_id = source_view
    with session_scope() as session:
        original = session.get(AgentAsset, asset_id)
        extra_ids = []
        for index in range(4):
            asset = AgentAsset(tenant_id=original.tenant_id, name='same-name', framework='openclaw',
                               discovery_scope=edge_id, source_type='fixture', source_locator=f'fixture-{index}')
            session.add(asset)
            session.flush()
            extra_ids.append(asset.id)
    route = '/api/v1/framework-role-inventory'
    assert client.get(route, headers={**tenant_a, 'X-Dev-Roles': 'viewer'}).status_code == 403
    assert client.get(route, headers=tenant_b, params={'device_id': edge_id}).json()['items'] == []
    cursor, observed, pages = None, [], []
    while True:
        params = {'device_id': edge_id, 'limit': 2, 'tenant_id': 'ignored-foreign'}
        if cursor:
            params['cursor'] = cursor
        response = client.get(route, headers=tenant_a, params=params)
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        data = response.json()
        assert data['coverage'] == 'page_of_tenant_assets'
        pages.append(data)
        observed.extend(item['asset_id'] for item in data['items'])
        for item in data['items']:
            detail = client.get(f"/api/v1/agents/{item['asset_id']}/framework-source", headers=tenant_a).json()
            assert item['framework_source'] == detail
            assert detail['effective_permissions'] is None
        cursor = data['next_cursor']
        if cursor is None:
            break
        assert len(pages) < 4
    assert len(pages) == 3
    assert observed == sorted([asset_id, *extra_ids])
    assert len(observed) == len(set(observed))
    mismatch = client.get(route, headers=tenant_a, params={'device_id': edge_id, 'environment_id': 'missing'})
    assert mismatch.json()['items'] == []
    for params in ({'limit': 0}, {'limit': 101}, {'cursor': '../bad'}, {'environment_id': ''}):
        assert client.get(route, headers=tenant_a, params=params).status_code == 422


def test_framework_inventory_bounded_queries(client, tenant_a, source_view):
    from sqlalchemy import event

    from app.framework_source_view import project_framework_sources

    asset_id, _, _ = source_view
    with session_scope() as session:
        asset = session.get(AgentAsset, asset_id)
        assets = [asset]
        evidence = session.scalar(select(Evidence).where(
            Evidence.tenant_id == asset.tenant_id, Evidence.evidence_id == 'source-fixture',
            Evidence.collector_id.in_(select(EdgeAgent.device_identity).where(EdgeAgent.id == asset.discovery_scope))))
        for index in range(99):
            role_key = f'{index:064x}'
            source = json.loads(asset.attributes['framework_source'])
            source['evidence_id'] = f'bounded-{index}'
            clone = AgentAsset(tenant_id=asset.tenant_id, name='same-name', framework='openclaw',
                               discovery_scope=asset.discovery_scope, source_type='openclaw_agent',
                               source_locator='openclaw://agents/v2/' + role_key,
                               attributes={'framework_source': json.dumps(source)},
                               evidence_ids=[source['evidence_id']])
            values = {column.name: getattr(evidence, column.name) for column in Evidence.__table__.columns
                      if column.name != 'id'}
            values.update(evidence_id=source['evidence_id'], subject_ref='openclaw:v2:' + role_key)
            session.add_all([clone, Evidence(**values)])
            assets.append(clone)
        session.flush()
        statements = []

        def capture(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith('SELECT'):
                statements.append(statement)

        connection = session.connection()
        event.listen(connection, 'before_cursor_execute', capture)
        try:
            result = project_framework_sources(session, asset.tenant_id, assets)
            assert len(result) == 100
            assert all(value['status'] == 'historical_reported_source' for value in result.values())
            assert len(statements) == 2
            with pytest.raises(ValueError):
                project_framework_sources(session, 'foreign-tenant', [asset])
            with pytest.raises(ValueError):
                project_framework_sources(session, asset.tenant_id, [asset] * 101)
        finally:
            event.remove(connection, 'before_cursor_execute', capture)
