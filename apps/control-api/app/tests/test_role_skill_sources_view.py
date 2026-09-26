import copy
import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import (
    AgentAsset,
    AuditEvent,
    EdgeAgent,
    EdgeTask,
    Evidence,
    OutboxEvent,
    PermissionFact,
    SkillManifestObservation,
    SkillUploadReceipt,
    utcnow,
)
from app.tests.edge_helpers import register_edge
from app.tests.test_skill_upload import upload_case as upload_case


@pytest.fixture
def role_source_case(upload_case, tenant_a, request):
    body, upload, task_id, edge_id, identity, env = upload_case
    body['schema_version'] = 'enterprise-skill-upload/v2'
    body['observations'][0]['ancestor_sha256'] = ['a' * 64, 'c' * 64]
    # Same name, different location: second is outside the declared roots;
    # third matches the project-agent source. All share a signed batch.
    for locator, ancestor in [('e', 'f'), ('1', 'd')]:
        item = copy.deepcopy(body['observations'][0])
        item['locator_sha256'] = locator * 64
        item['ancestor_sha256'] = [locator * 64, ancestor * 64]
        body['observations'].append(item)
    assert upload(body).status_code == 200
    with session_scope() as session:
        source = {'schema_version': 'enterprise-framework-source/v1', 'framework': 'openclaw',
                  'instance_key': '9' * 64, 'config_sha256': '8' * 64, 'evidence_id': 'source-fixture'}
        roots = {'schema_version': 'enterprise-role-skill-roots/v1', 'basis': 'agent_workspace',
                 'status': 'declared', 'roots': [{'kind': 'workspace_skills', 'locator_sha256': 'c' * 64},
                                               {'kind': 'project_agent_skills', 'locator_sha256': 'd' * 64}]}
        asset = AgentAsset(tenant_id=tenant_a['X-Dev-Tenant-Id'], name='sample', framework='openclaw',
                           source_type='openclaw_agent', source_locator='openclaw://agents/v2/' + '7' * 64,
                           discovery_scope=edge_id, evidence_ids=['source-fixture'],
                           attributes={'framework_source': json.dumps(source), 'skill_source_roots': json.dumps(roots)})
        evidence = Evidence(tenant_id=asset.tenant_id, environment_id=env, collector_id=identity,
                            evidence_id='source-fixture', source_type='openclaw_config',
                            source_locator='fixture-private-path', subject_ref='openclaw:v2:' + '7' * 64,
                            content_hash='8' * 64, observed_at=utcnow(), connector_version='test', signature='fixture')
        if getattr(request, 'param', 'openclaw') == 'hermes':
            asset.framework, asset.source_type = 'hermes', 'hermes_profile'
            asset.source_locator = 'hermes://profiles/v2/' + '7' * 64
            source.update(schema_version='enterprise-framework-source/v2', framework='hermes', instance_key='7' * 64)
            roots = {'schema_version': 'enterprise-role-skill-roots/v2', 'basis': 'hermes_profile_layout',
                     'status': 'layout_candidate', 'roots': [{'kind': 'profile_skills', 'locator_sha256': 'c' * 64}]}
            asset.attributes = {'framework_source': json.dumps(source), 'skill_source_roots': json.dumps(roots)}
            evidence.source_type, evidence.subject_ref = 'manifest', 'hermes:v2:' + '7' * 64
            evidence.source_locator = '7' * 64 + '/config.yaml'
        session.add_all([asset, evidence])
        session.flush()
        return asset.id, edge_id, task_id


@pytest.mark.parametrize('role_source_case', ['openclaw', 'hermes'], indirect=True)
def test_role_skill_source_pagination_scope_and_read_only(client, tenant_a, tenant_b, role_source_case):
    asset_id, edge_id, _ = role_source_case
    route = f'/api/v1/agents/{asset_id}/skill-installation-sources'
    models = (AgentAsset, Evidence, PermissionFact, AuditEvent, OutboxEvent, SkillUploadReceipt)
    with session_scope() as session:
        session.get(EdgeAgent, edge_id).revoked_at = utcnow()
        hermes = session.get(AgentAsset, asset_id).framework == 'hermes'
        before = [session.scalar(select(func.count()).select_from(model)) for model in models]
    items, cursor = [], None
    for _ in range(3):
        response = client.get(route, headers=tenant_a, params={'limit': 1, **({'cursor': cursor} if cursor else {})})
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        value = response.json()
        assert value['schema_version'] == f'enterprise-role-skill-sources-view/{"v2" if hermes else "v1"}'
        assert value['status'] == 'historical_comparison'
        assert value['runtime_status'] == 'unverified' and value['effective_permissions'] is None
        assert value['framework_source']['source']['device_revoked']
        assert 'fixture-private' not in response.text and 'signed_payload' not in response.text
        items.extend(value['items'])
        cursor = value['next_cursor']
    assert cursor is None and len(items) == 3
    assert len({item['installation_id'] for item in items}) == 3
    by_locator = {item['locator_sha256']: item for item in items}
    assert by_locator['a' * 64]['relationship_status'] == 'historical_source_match'
    assert by_locator['a' * 64]['matched_sources'][0]['kind'] == ('profile_skills' if hermes else 'workspace_skills')
    if hermes:
        assert by_locator['1' * 64]['relationship_status'] == 'outside_declared_sources'
        assert by_locator['1' * 64]['matched_sources'] == []
    else:
        assert by_locator['1' * 64]['matched_sources'][0]['kind'] == 'project_agent_skills'
    assert by_locator['e' * 64]['relationship_status'] == 'outside_declared_sources'
    assert {item['observation']['name'] for item in items} == {'sample'}
    assert client.get(route, headers=tenant_b).status_code == 404
    assert client.get(route, headers={**tenant_a, 'X-Dev-Roles': 'viewer'}).status_code == 403
    assert client.get(route, headers=tenant_a, params={'tenant_id': tenant_b['X-Dev-Tenant-Id']}).json()['items']
    for params in ({'limit': 0}, {'limit': 101}, {'cursor': 'not-a-cursor'}):
        assert client.get(route, headers=tenant_a, params=params).status_code == 422
    with session_scope() as session:
        assert before == [session.scalar(select(func.count()).select_from(model)) for model in models]
        assert session.get(AgentAsset, asset_id).status == 'candidate'


@pytest.mark.parametrize('fault', ['receipt', 'signature', 'payload', 'task-scope', 'task-device',
                                  'receipt-tenant', 'receipt-device', 'observation', 'roots', 'config', 'device',
                                  'hermes-roots'])
def test_role_skill_source_failure_does_not_guess(client, tenant_a, tenant_b, role_source_case, fault):
    asset_id, edge_id, task_id = role_source_case
    other_identity = 'source-other-' + uuid.uuid4().hex
    if fault == 'receipt-device':
        with session_scope() as session:
            environment_id = session.get(EdgeAgent, edge_id).environment_id
        register_edge(client, tenant_a, environment_id, other_identity)
    with session_scope() as session:
        receipt = session.get(SkillUploadReceipt, task_id)
        task = session.get(EdgeTask, task_id)
        asset = session.get(AgentAsset, asset_id)
        if fault == 'receipt':
            session.delete(receipt)
        elif fault == 'signature':
            receipt.signature = '0' * 128
        elif fault == 'payload':
            receipt.signed_payload += ' '
        elif fault == 'task-scope':
            task.payload = {**task.payload, 'scope': {'roots': ['/different']}}
        elif fault == 'task-device':
            task.payload = {**task.payload, 'target_device_identity': 'different'}
        elif fault == 'receipt-tenant':
            receipt.tenant_id = tenant_b['X-Dev-Tenant-Id']
        elif fault == 'receipt-device':
            # Use a real other registered device to retain database constraints.
            other = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == other_identity))
            assert other is not None
            receipt.edge_agent_id = other.id
        elif fault == 'observation':
            for row in session.scalars(select(SkillManifestObservation).where(
                    SkillManifestObservation.batch_digest == receipt.batch_digest)):
                row.manifest_sha256 = '0' * 64
        elif fault == 'roots':
            asset.attributes = {**asset.attributes, 'skill_source_roots': '{}'}
        elif fault == 'config':
            asset.evidence_ids = []
        elif fault == 'device':
            asset.discovery_scope = 'missing-device'
        elif fault == 'hermes-roots':
            asset.framework, asset.source_type = 'hermes', 'hermes_profile'
            asset.source_locator = 'hermes://profiles/v2/' + '7' * 64
            source = json.loads(asset.attributes['framework_source'])
            source.update(schema_version='enterprise-framework-source/v2', framework='hermes', instance_key='7' * 64)
            asset.attributes = {**asset.attributes, 'framework_source': json.dumps(source)}
            evidence = session.scalar(select(Evidence).where(
                Evidence.tenant_id == asset.tenant_id, Evidence.evidence_id == 'source-fixture',
                Evidence.environment_id == session.get(EdgeAgent, edge_id).environment_id))
            evidence.source_type = 'manifest'
            evidence.subject_ref = 'hermes:v2:' + '7' * 64
            evidence.source_locator = '7' * 64 + '/config.yaml'
    response = client.get(f'/api/v1/agents/{asset_id}/skill-installation-sources', headers=tenant_a)
    assert response.status_code == 200
    value = response.json()
    if fault in ('roots', 'config', 'device', 'hermes-roots'):
        assert value['status'] == 'source_unavailable' and value['items'] == []
        if fault == 'hermes-roots':
            assert value['framework_source']['status'] == 'historical_reported_source'
            assert value['declared_roots'] is None and value['effective_permissions'] is None
    else:
        assert len(value['items']) == 3
        assert all(item['relationship_status'] == 'unresolved' and item['observation'] is None
                   and item['matched_sources'] == [] for item in value['items'])


def test_latest_observation_without_provenance_never_falls_back(client, tenant_a, role_source_case):
    asset_id, _, task_id = role_source_case
    with session_scope() as session:
        receipt = session.get(SkillUploadReceipt, task_id)
        old = session.scalar(select(SkillManifestObservation).where(
            SkillManifestObservation.batch_digest == receipt.batch_digest))
        installation_id = old.installation_id
        values = {column.name: getattr(old, column.name) for column in SkillManifestObservation.__table__.columns
                  if column.name != 'id'}
        values.update(batch_digest='0' * 64, observed_at=old.observed_at + timedelta(seconds=1))
        session.add(SkillManifestObservation(**values))
    value = client.get(f'/api/v1/agents/{asset_id}/skill-installation-sources', headers=tenant_a).json()
    item = next(item for item in value['items'] if item['installation_id'] == installation_id)
    assert item['relationship_status'] == 'unresolved'
    assert item['matched_sources'] == [] and item['observation'] is None


def test_shared_batch_verified_once_and_fields_unchanged(client, tenant_a, role_source_case, monkeypatch):
    from app.routers import role_skill_sources

    asset_id, _, task_id = role_source_case
    calls = []
    original = role_skill_sources.verified_batch

    def checked(*args):
        calls.append(args[0].task_id)
        return original(*args)

    def snapshot(session):
        asset = session.get(AgentAsset, asset_id)
        task = session.get(EdgeTask, task_id)
        receipt = session.get(SkillUploadReceipt, task_id)
        observations = list(session.execute(select(
            SkillManifestObservation.id, SkillManifestObservation.manifest_sha256,
            SkillManifestObservation.observed_at, SkillManifestObservation.batch_digest,
        ).where(SkillManifestObservation.batch_digest == receipt.batch_digest)
            .order_by(SkillManifestObservation.id)))
        return (asset.status, copy.deepcopy(asset.attributes), list(asset.evidence_ids),
                task.status, task.result_digest, receipt.batch_digest, observations)

    monkeypatch.setattr(role_skill_sources, 'verified_batch', checked)
    with session_scope() as session:
        before = snapshot(session)
    response = client.get(f'/api/v1/agents/{asset_id}/skill-installation-sources', headers=tenant_a)
    assert response.status_code == 200 and len(response.json()['items']) == 3
    assert calls == [task_id]
    with session_scope() as session:
        assert snapshot(session) == before
