import json
import uuid

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.evidence_signing import evidence_signed_bytes
from app.models import AgentAsset, EdgeTask, Evidence, PermissionFact
from app.tests.edge_helpers import candidate, create_scan_task, register_edge, signed_batch, signed_evidence


@pytest.mark.parametrize('case', ['valid', 'legacy', 'hash', 'subject', 'type', 'unknown',
                                 'duplicate', 'null', 'uppercase', 'instance', 'connector'])
@pytest.mark.parametrize('framework', ['openclaw', 'hermes'])
def test_framework_source_signed_ingestion(client, tenant_a, case, framework):
    tenant = {**tenant_a, 'X-Dev-Tenant-Id': 'framework-' + uuid.uuid4().hex}
    identity = 'fixture-' + uuid.uuid4().hex
    env = client.post('/api/v1/environments', headers=tenant, json={'name': identity}).json()['id']
    headers, key = register_edge(client, tenant, env, identity)
    other = 'hermes' if framework == 'openclaw' else 'openclaw'
    task_id = create_scan_task(client, tenant, env, other if case == 'connector' else framework)
    role_id = framework + ':v2:' + 'a' * 64
    evidence = signed_evidence(key, identity, 'ev-fixture',
                               source_type='openclaw_config' if framework == 'openclaw' else 'manifest')
    evidence['subject_ref'] = role_id
    if framework == 'hermes':
        evidence['source_locator'] = 'a' * 64 + '/config.yaml'
    role = candidate('fixture', ['ev-fixture'],
                     source_type='openclaw_agent' if framework == 'openclaw' else 'hermes_profile')
    collection = 'agents' if framework == 'openclaw' else 'profiles'
    role.update(candidate_id=role_id, framework=framework, source_locator=f'{framework}://{collection}/v2/' + 'a' * 64)
    version = 'v1' if framework == 'openclaw' else 'v2'
    source = {'schema_version': f'enterprise-framework-source/{version}', 'framework': framework,
              'instance_key': ('b' if framework == 'openclaw' else 'a') * 64,
              'config_sha256': evidence['content_hash'], 'evidence_id': 'ev-fixture'}
    if case == 'hash':
        source['config_sha256'] = 'c' * 64
    if case == 'subject':
        evidence['subject_ref'] = 'other-role'
    if case == 'type':
        evidence['source_type'] = 'manifest' if framework == 'openclaw' else 'openclaw_config'
    if case == 'unknown':
        source['tenant_id'] = 'foreign'
    if case == 'null':
        source['instance_key'] = None
    if case == 'uppercase':
        source['INSTANCE_KEY'] = source.pop('instance_key')
    if case == 'instance':
        source['instance_key'] = '../private'
    raw = json.dumps(source)
    if case == 'duplicate':
        raw = raw[:-1] + ', "framework": "openclaw"}'
    role['attributes'] = {} if case == 'legacy' else {'framework_source': raw}
    evidence['signature'] = key.sign(evidence_signed_bytes(evidence)).hex()
    batch = signed_batch(key, task_id, candidates=[role], evidence=[evidence])
    response = client.post('/edge/v1/batches', headers=headers, json=batch)
    valid = case in ('valid', 'legacy')
    assert response.status_code == (200 if valid else 422)
    if not valid:
        assert response.json()['detail'] == 'framework_source_invalid'
    with session_scope() as session:
        assets = list(session.scalars(select(AgentAsset).where(AgentAsset.tenant_id == tenant['X-Dev-Tenant-Id'])))
        assert len(assets) == int(valid)
        assert session.scalar(select(func.count()).select_from(Evidence).where(
            Evidence.tenant_id == tenant['X-Dev-Tenant-Id'])) == int(valid)
        assert session.scalar(select(func.count()).select_from(PermissionFact).where(
            PermissionFact.tenant_id == tenant['X-Dev-Tenant-Id'])) == 0
        if not valid:
            assert session.get(EdgeTask, task_id).status == 'pending'
        elif case == 'valid':
            assert assets[0].attributes['framework_source'] == raw
            assert assets[0].status == 'candidate'
        asset_id = assets[0].id if valid else None
    if valid:
        replay = client.post('/edge/v1/batches', headers=headers, json=batch)
        assert replay.status_code == 200 and replay.json()['idempotent']
        projection = client.get(f'/api/v1/agents/{asset_id}/framework-source', headers=tenant)
        assert projection.status_code == 200
        assert projection.headers['cache-control'] == 'no-store'
        value = projection.json()
        assert value['runtime_status'] == 'unverified'
        assert value['effective_permissions'] is None
        assert value['skill_relationship_status'] == 'unresolved'
        if case == 'valid':
            assert value['status'] == 'historical_reported_source'
            assert value['source']['instance_key'] == source['instance_key']
            assert value['source']['environment_id'] == env
            assert value['source']['config_sha256'] == evidence['content_hash']
        elif case == 'legacy':
            assert value['status'] == 'no_recorded_source' and value['source'] is None
