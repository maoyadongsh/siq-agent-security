import json
import uuid

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.evidence_signing import evidence_signed_bytes
from app.models import AgentAsset, EdgeTask, Evidence, PermissionFact
from app.tests.edge_helpers import candidate, create_scan_task, register_edge, signed_batch, signed_evidence


@pytest.mark.parametrize('case', ['declared', 'unresolved', 'legacy', 'no_source', 'extra', 'duplicate_key',
                                 'duplicate_root', 'order', 'hash', 'unknown', 'null', 'none', 'unresolved_roots',
                                 'hermes_origin', 'hermes_layout', 'hermes_bad_kind', 'openclaw_v2'])
def test_role_skill_roots_signed_ingestion(client, tenant_a, case):
    tenant = {**tenant_a, 'X-Dev-Tenant-Id': 'roots-' + uuid.uuid4().hex}
    identity = 'fixture-' + uuid.uuid4().hex
    env = client.post('/api/v1/environments', headers=tenant, json={'name': identity}).json()['id']
    headers, key = register_edge(client, tenant, env, identity)
    hermes = case.startswith('hermes_')
    task_id = create_scan_task(client, tenant, env, 'hermes' if hermes else 'openclaw')
    role_id = 'openclaw:v2:' + 'a' * 64
    evidence = signed_evidence(key, identity, 'ev-roots', source_type='openclaw_config')
    evidence['subject_ref'] = role_id
    evidence['signature'] = key.sign(evidence_signed_bytes(evidence)).hex()
    role = candidate('fixture', ['ev-roots'], source_type='openclaw_agent')
    role.update(candidate_id=role_id, framework='openclaw', source_locator='openclaw://agents/v2/' + 'a' * 64)
    source = {'schema_version': 'enterprise-framework-source/v1', 'framework': 'openclaw',
              'instance_key': 'b' * 64, 'config_sha256': evidence['content_hash'], 'evidence_id': 'ev-roots'}
    if hermes:
        # Valid Hermes provenance must not authorize OpenClaw-specific workspace semantics.
        role.update(candidate_id='hermes:v2:' + 'a' * 64, framework='hermes',
                    source_type='hermes_profile', source_locator='hermes://profiles/v2/' + 'a' * 64)
        source.update(schema_version='enterprise-framework-source/v2', framework='hermes', instance_key='a' * 64)
        evidence.update(source_type='manifest', subject_ref=role['candidate_id'],
                        source_locator='a' * 64 + '/config.yaml')
        evidence['signature'] = key.sign(evidence_signed_bytes(evidence)).hex()
    roots = {'schema_version': 'enterprise-role-skill-roots/v1', 'basis': 'agent_workspace', 'status': 'declared',
             'roots': [{'kind': 'workspace_skills', 'locator_sha256': 'c' * 64},
                       {'kind': 'project_agent_skills', 'locator_sha256': 'd' * 64}]}
    if case in ('hermes_layout', 'hermes_bad_kind', 'openclaw_v2'):
        roots = {'schema_version': 'enterprise-role-skill-roots/v2', 'basis': 'hermes_profile_layout',
                 'status': 'layout_candidate', 'roots': [{'kind': 'profile_skills', 'locator_sha256': 'c' * 64}]}
        if case == 'hermes_bad_kind':
            roots['roots'][0]['kind'] = 'workspace_skills'
    if case == 'unresolved':
        roots.update(basis='none', status='unresolved', roots=[])
    if case == 'extra':
        roots['effective'] = True
    if case == 'duplicate_root':
        roots['roots'][1]['locator_sha256'] = 'c' * 64
    if case == 'order':
        roots['roots'].reverse()
    if case == 'hash':
        roots['roots'][0]['locator_sha256'] = '/fixture/private'
    if case == 'unknown':
        roots['roots'][0]['kind'] = 'runtime_loaded'
    if case == 'null':
        roots['roots'] = None
    if case == 'none':
        roots['basis'] = 'none'
    if case == 'unresolved_roots':
        roots['status'] = 'unresolved'
    raw = json.dumps(roots)
    if case == 'duplicate_key':
        raw = raw[:-1] + ', "basis": "agent_workspace"}'
    role['attributes'] = {'framework_source': json.dumps(source), 'skill_source_roots': raw}
    if case == 'legacy':
        role['attributes'].pop('skill_source_roots')
    if case == 'no_source':
        role['attributes'].pop('framework_source')
    batch = signed_batch(key, task_id, candidates=[role], evidence=[evidence])
    response = client.post('/edge/v1/batches', headers=headers, json=batch)
    valid = case in ('declared', 'unresolved', 'legacy', 'hermes_layout')
    assert response.status_code == (200 if valid else 422), response.text
    if not valid:
        assert response.json()['detail'] == 'role_skill_roots_invalid'
    with session_scope() as session:
        assets = list(session.scalars(select(AgentAsset).where(AgentAsset.tenant_id == tenant['X-Dev-Tenant-Id'])))
        assert len(assets) == int(valid)
        assert session.scalar(select(func.count()).select_from(Evidence).where(
            Evidence.tenant_id == tenant['X-Dev-Tenant-Id'])) == int(valid)
        assert session.scalar(select(func.count()).select_from(PermissionFact).where(
            PermissionFact.tenant_id == tenant['X-Dev-Tenant-Id'])) == 0
        if not valid:
            assert session.get(EdgeTask, task_id).status == 'pending'
        elif case != 'legacy':
            assert assets[0].attributes['skill_source_roots'] == raw
        asset_id = assets[0].id if valid else None
    if valid:
        assert client.post('/edge/v1/batches', headers=headers, json=batch).json()['idempotent']
        projection = client.get(f'/api/v1/agents/{asset_id}/framework-source', headers=tenant).json()
        assert projection['skill_relationship_status'] == 'unresolved'
        assert projection['effective_permissions'] is None
